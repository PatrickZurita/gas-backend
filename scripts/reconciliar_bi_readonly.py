"""Reconciliación BI local opt-in contra PostgreSQL con un rol sin escritura.

No crea archivos, no imprime DSN ni filas nominales y no se ejecuta al importar.
Uso: python scripts/reconciliar_bi_readonly.py --desde YYYY-MM-DD --hasta YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tempfile
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

_backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_backend_dir))

from openpyxl import load_workbook
from sqlalchemy import case, create_engine, distinct, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROL_ESPERADO = "gas_readonly"
RANGO_MAXIMO_DIAS = 366
_BARRERAS_SQL = """
SELECT current_user AS usuario, session_user AS usuario_sesion,
       current_setting('transaction_read_only') AS solo_lectura,
       current_setting('transaction_isolation') AS aislamiento,
       to_regclass('public.pedidos') IS NOT NULL AS pedidos_existe,
       has_table_privilege(current_user, 'public.pedidos', 'SELECT') AS puede_leer,
       has_table_privilege(current_user, 'public.pedidos', 'INSERT') AS puede_insertar,
       has_table_privilege(current_user, 'public.pedidos', 'UPDATE') AS puede_actualizar,
       has_table_privilege(current_user, 'public.pedidos', 'DELETE') AS puede_borrar,
       has_table_privilege(current_user, 'public.pedidos', 'TRUNCATE') AS puede_truncar,
       has_schema_privilege(current_user, 'public', 'CREATE') AS crea_en_esquema,
       has_database_privilege(current_user, current_database(), 'CREATE') AS crea_en_base,
       r.rolsuper AS superusuario, r.rolcreaterole AS crea_roles,
       r.rolcreatedb AS crea_bases, r.rolbypassrls AS omite_rls
FROM pg_roles AS r WHERE r.rolname = current_user
"""
_TABLAS_CALIDAD = frozenset({
    "clientes", "demanda_perdida", "stock_jornadas", "movimientos_stock"
})
_BARRERAS_TABLAS_SQL = """
SELECT c.relname AS tabla,
       has_table_privilege(current_user, c.oid, 'SELECT') AS puede_leer,
       has_table_privilege(current_user, c.oid, 'INSERT') AS puede_insertar,
       has_table_privilege(current_user, c.oid, 'UPDATE') AS puede_actualizar,
       has_table_privilege(current_user, c.oid, 'DELETE') AS puede_borrar,
       has_table_privilege(current_user, c.oid, 'TRUNCATE') AS puede_truncar
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND c.relname IN ('clientes', 'demanda_perdida', 'stock_jornadas', 'movimientos_stock')
"""


def _validar_fechas(desde_texto: str, hasta_texto: str) -> tuple[date, date]:
    if not all(
        len(valor) == 10 and valor[4] == "-" and valor[7] == "-"
        for valor in (desde_texto, hasta_texto)
    ):
        raise ValueError("Fechas requeridas en formato YYYY-MM-DD")
    desde, hasta = date.fromisoformat(desde_texto), date.fromisoformat(hasta_texto)
    if desde > hasta or hasta > datetime.now(ZoneInfo("America/Lima")).date():
        raise ValueError("Rango inválido o posterior a hoy en Lima")
    if (hasta - desde).days + 1 > RANGO_MAXIMO_DIAS:
        raise ValueError("El rango supera 366 días")
    return desde, hasta


def _validar_dsn(dsn: str):
    """Acepta solo DSN PostgreSQL para el rol analítico; nunca lo devuelve en errores."""
    try:
        url = make_url(dsn.strip())
    except Exception:
        raise ValueError("DSN inválido") from None
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("Se requiere PostgreSQL")
    if url.username != ROL_ESPERADO or not url.password or not url.host or not url.database:
        raise ValueError("Se requiere DSN completo del rol gas_readonly")
    if not url.host.endswith(".neon.tech"):
        raise ValueError("Se requiere un host Neon")
    if set(url.query) - {"sslmode", "channel_binding"}:
        raise ValueError("DSN contiene opciones no admitidas")
    if url.query.get("sslmode", "require") not in {"require", "verify-ca", "verify-full"}:
        raise ValueError("TLS requerido")
    return url.set(
        drivername="postgresql+psycopg",
        query={**url.query, "sslmode": url.query.get("sslmode", "require")},
    )


def _exigir_barreras(estado) -> None:
    if (
        estado["usuario"] != ROL_ESPERADO
        or estado["usuario_sesion"] != ROL_ESPERADO
        or estado["solo_lectura"] != "on"
        or estado["aislamiento"] != "repeatable read"
        or not estado["pedidos_existe"]
        or not estado["puede_leer"]
        or any(
            estado[campo]
            for campo in (
                "puede_insertar", "puede_actualizar", "puede_borrar",
                "puede_truncar", "crea_en_esquema", "crea_en_base",
                "superusuario", "crea_roles", "crea_bases", "omite_rls",
            )
        )
    ):
        raise PermissionError("Barreras de solo lectura no verificadas")


def _tablas_calidad_seguras(filas) -> set[str]:
    """Una tabla opcional solo se lee si existe y el rol es SELECT puro."""
    return {
        fila["tabla"] for fila in filas
        if fila["tabla"] in _TABLAS_CALIDAD
        and fila["puede_leer"]
        and not any(fila[campo] for campo in (
            "puede_insertar", "puede_actualizar", "puede_borrar", "puede_truncar"
        ))
    }


def _obtener_corte(engine, *, desde: date, hasta: date, peso: int | None,
                   calidad_fuentes: bool = False):
    """Compara BI y reporte operativo en el mismo snapshot de solo lectura."""
    with engine.connect() as conexion:
        transaccion = conexion.begin()
        try:
            conexion.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            estado = conexion.exec_driver_sql(_BARRERAS_SQL).mappings().one()
            _exigir_barreras(estado)
            tablas_seguras = set()
            if calidad_fuentes:
                filas = conexion.exec_driver_sql(_BARRERAS_TABLAS_SQL).mappings().all()
                tablas_seguras = _tablas_calidad_seguras(filas)
            with Session(bind=conexion, join_transaction_mode="rollback_only") as db:
                corte = _construir_corte(db, desde=desde, hasta=hasta, peso=peso)
                operativo = _obtener_operativo(db, desde=desde, hasta=hasta, peso=peso)
                calidad = (
                    _medir_calidad_fuentes(
                        db, desde=desde, hasta=hasta, peso=peso,
                        tablas_seguras=tablas_seguras,
                    ) if calidad_fuentes else None
                )
                return corte, operativo, calidad
        finally:
            transaccion.rollback()


def _construir_corte(db, *, desde: date, hasta: date, peso: int | None):
    # Importar la app solo después de aislar el cwd dentro de main.
    from app.services.bi import construir_corte

    return construir_corte(db, desde=desde, hasta=hasta, peso_balon_kg=peso)


def _obtener_operativo(db, *, desde: date, hasta: date, peso: int | None) -> dict:
    """Proyecta el listado V4 operativo, sin stock ni identificadores en salida.

    El repositorio de reportes usa ACTIVO/fecha_entrega inclusiva. Su regla
    monetaria prefiere centavos y cae a soles legacy; los nulos se contabilizan
    antes de llamar los conversores, pues el endpoint V4 no los tolera.
    """
    from app.infrastructure.repositories import reportes as repo_reportes
    from app.services import reportes as service_reportes

    pedidos = repo_reportes.listar_pedidos_por_rango(db, desde=desde, hasta=hasta)
    medidas = {
        "pedidos_activos": 0, "balones_vendidos": 0,
        "balones_10kg": 0, "balones_45kg": 0,
        "vendido_centavos": 0, "pendiente_centavos": 0,
        "cobrado_calculado_centavos": 0, "pedidos_con_monto_valido": 0,
        "pedidos_sin_monto_valido": 0, "pedidos_monetarios_anomalos": 0,
        "pedidos_monto_total_legacy": 0, "pedidos_pendiente_legacy": 0,
        "peso_nulo_legacy": 0,
        "vendido_centavos_bruto_operativo": 0,
        "pendiente_centavos_bruto_operativo": 0,
    }
    filas_validas = []
    for pedido in pedidos:
        peso_operativo = pedido.peso_balon_kg or 10
        if peso is not None and peso_operativo != peso:
            continue
        medidas["peso_nulo_legacy"] += int(pedido.peso_balon_kg is None)
        medidas["pedidos_activos"] += 1
        medidas["balones_vendidos"] += pedido.cantidad_balones
        medidas[f"balones_{peso_operativo}kg"] += pedido.cantidad_balones
        total_legacy = pedido.monto_total_centavos is None
        pendiente_legacy = pedido.monto_pendiente_centavos is None
        medidas["pedidos_monto_total_legacy"] += int(total_legacy and pedido.total_soles is not None)
        medidas["pedidos_pendiente_legacy"] += int(
            pendiente_legacy and pedido.saldo_pendiente is not None
        )
        if (total_legacy and pedido.total_soles is None) or (
            pendiente_legacy and pedido.saldo_pendiente is None
        ):
            medidas["pedidos_sin_monto_valido"] += 1
            continue
        # Misma conversión que el repositorio de reportes, independiente del
        # conversor BI; Numeric(10,2) conserva centavos exactos.
        total = repo_reportes._monto_total_centavos(pedido)
        pendiente = repo_reportes._monto_pendiente_centavos(pedido)
        medidas["vendido_centavos_bruto_operativo"] += total
        medidas["pendiente_centavos_bruto_operativo"] += pendiente
        if total < 0 or pendiente < 0 or pendiente > total:
            medidas["pedidos_monetarios_anomalos"] += 1
            continue
        medidas["pedidos_con_monto_valido"] += 1
        filas_validas.append({
            "fecha_entrega": pedido.fecha_entrega,
            "cantidad_balones": pedido.cantidad_balones,
            "peso_balon_kg": peso_operativo,
            "monto_total_centavos": total,
            "monto_pendiente_centavos": pendiente,
            "pagado": pedido.pagado,
            "metodo_pago": pedido.metodo_pago,
        })
    # _agrupar_por_dia es la misma agregación que usa /reportes/semana y /mes.
    # Se aplica a filas monetariamente válidas para hacer comparable BI.
    por_dia = service_reportes._agrupar_por_dia(filas_validas)
    medidas["vendido_centavos"] = sum(d["vendido_centavos"] for d in por_dia.values())
    medidas["pendiente_centavos"] = sum(d["pendiente_centavos"] for d in por_dia.values())
    medidas["cobrado_calculado_centavos"] = sum(
        d["cobrado_centavos"] for d in por_dia.values()
    )
    return medidas


def _medir_calidad_fuentes(db, *, desde: date, hasta: date, peso: int | None,
                           tablas_seguras: set[str]) -> dict:
    """Mide cobertura BI-08A; cada bloque requiere SELECT puro verificado."""
    from app.models.models import Cliente, DemandaPerdida, MovimientoStock, Pedido, StockJornada

    calidad: dict = {
        "altas_clientes_en_ventana": "no_medible_sin_fecha_alta",
        "rutina_captura_demanda": "requiere_confirmacion_dueno",
    }
    if "clientes" in tablas_seguras:
        stmt = select(
            func.count(distinct(Pedido.cliente_id)),
            func.count(distinct(case(
                (Cliente.canal_captacion.is_not(None), Pedido.cliente_id),
                else_=None,
            ))),
        ).join(Cliente, Pedido.cliente_id == Cliente.id).where(
            Pedido.estado == "ACTIVO",
            Pedido.fecha_entrega >= desde,
            Pedido.fecha_entrega <= hasta,
        )
        if peso is not None:
            stmt = stmt.where(Pedido.peso_balon_kg == peso)
        compradores, con_canal = db.execute(stmt).one()
        calidad["canal_compradores"] = {
            "estado": "medido", "compradores": compradores,
            "con_canal_conocido": con_canal,
            "sin_canal": compradores - con_canal,
        }
    else:
        calidad["canal_compradores"] = {
            "estado": "no_disponible", "motivo": "tabla_sin_select_puro_verificado"
        }

    if "demanda_perdida" in tablas_seguras:
        base = select(
            DemandaPerdida.motivo, DemandaPerdida.peso_balon_kg,
            func.count(), func.sum(DemandaPerdida.cantidad_balones),
        ).where(
            DemandaPerdida.fecha >= desde, DemandaPerdida.fecha <= hasta,
        )
        dias = select(func.count(distinct(DemandaPerdida.fecha))).where(
            DemandaPerdida.fecha >= desde, DemandaPerdida.fecha <= hasta,
        )
        if peso is not None:
            base = base.where(DemandaPerdida.peso_balon_kg == peso)
            dias = dias.where(DemandaPerdida.peso_balon_kg == peso)
        filas = db.execute(base.group_by(
            DemandaPerdida.motivo, DemandaPerdida.peso_balon_kg
        )).all()
        calidad["demanda_no_atendida"] = {
            "estado": "medido", "eventos_registrados": sum(f[2] for f in filas),
            "balones_registrados": sum(f[3] for f in filas),
            "dias_con_registro": db.execute(dias).scalar_one(),
            "por_motivo_y_peso": [
                {"motivo": motivo, "peso_balon_kg": kg,
                 "eventos": eventos, "balones": balones}
                for motivo, kg, eventos, balones in filas
            ],
            "limite": "cero registros no equivale a cero demanda no atendida",
        }
    else:
        calidad["demanda_no_atendida"] = {
            "estado": "no_disponible", "motivo": "tabla_sin_select_puro_verificado"
        }

    if "stock_jornadas" in tablas_seguras:
        jornadas = db.execute(select(
            func.count(),
            func.sum(case((StockJornada.cerrado.is_(True), 1), else_=0)),
            func.sum(case((StockJornada.stock_final_fisico.is_not(None), 1), else_=0)),
        ).where(StockJornada.fecha >= desde, StockJornada.fecha <= hasta)).one()
        calidad["jornadas_stock"] = {
            "estado": "medido", "dias_rango": (hasta - desde).days + 1,
            "jornadas": jornadas[0], "cerradas": jornadas[1] or 0,
            "con_cierre_fisico": jornadas[2] or 0,
            "limite": "sin jornada no significa stock cero",
        }
    else:
        calidad["jornadas_stock"] = {
            "estado": "no_disponible", "motivo": "tabla_sin_select_puro_verificado"
        }

    if "movimientos_stock" in tablas_seguras:
        stmt = select(
            MovimientoStock.tipo, MovimientoStock.peso_balon_kg,
            func.count(), func.sum(MovimientoStock.cantidad_delta),
        ).where(
            MovimientoStock.fecha >= desde, MovimientoStock.fecha <= hasta,
        )
        if peso is not None:
            # Peso NULL se muestra aparte solo en corte de ambos pesos.
            stmt = stmt.where(MovimientoStock.peso_balon_kg == peso)
        filas = db.execute(stmt.group_by(
            MovimientoStock.tipo, MovimientoStock.peso_balon_kg
        )).all()
        calidad["movimientos_stock"] = {
            "estado": "medido", "movimientos": sum(f[2] for f in filas),
            "peso_nulo": sum(f[2] for f in filas if f[1] is None),
            "por_tipo_y_peso": [
                {"tipo": tipo, "peso_balon_kg": kg,
                 "movimientos": cantidad, "delta_neto": delta}
                for tipo, kg, cantidad, delta in filas
            ],
            "limite": "inicio, compras, salidas, ajustes y reversas no son intercambiables",
        }
    else:
        calidad["movimientos_stock"] = {
            "estado": "no_disponible", "motivo": "tabla_sin_select_puro_verificado"
        }
    return calidad


def _comparar_operativo(salida_bi: dict, operativo: dict) -> dict:
    """Contrasta medidas independientes y explica exclusiones sin PII."""
    resumen = salida_bi["resumen"]
    cobertura = salida_bi["cobertura"]
    campos = (
        "pedidos_activos", "balones_vendidos", "balones_10kg", "balones_45kg",
        "vendido_centavos", "pendiente_centavos", "cobrado_calculado_centavos",
        "pedidos_con_monto_valido",
    )
    diferencias = {campo: operativo[campo] - resumen[campo] for campo in campos
                   if operativo[campo] != resumen[campo]}
    for campo in (
        "pedidos_sin_monto_valido", "pedidos_monetarios_anomalos",
        "pedidos_monto_total_legacy", "pedidos_pendiente_legacy",
    ):
        if operativo[campo] != cobertura[campo]:
            diferencias[campo] = operativo[campo] - cobertura[campo]
    requiere_revision = bool(
        operativo["pedidos_sin_monto_valido"]
        or operativo["pedidos_monetarios_anomalos"]
        or operativo["peso_nulo_legacy"]
    )
    estado = (
        "difiere" if diferencias else
        "requiere_revision" if requiere_revision else
        "ok_con_legacy" if (
            operativo["pedidos_monto_total_legacy"]
            or operativo["pedidos_pendiente_legacy"]
        ) else "ok"
    )
    return {
        "estado": estado,
        "fuente": "repositorio_reportes_V4_y_agregador_operativo",
        "mismo_snapshot": True,
        "medidas": {campo: operativo[campo] for campo in campos},
        "calidad": {
            campo: operativo[campo] for campo in (
                "pedidos_sin_monto_valido", "pedidos_monetarios_anomalos",
                "pedidos_monto_total_legacy", "pedidos_pendiente_legacy",
                "peso_nulo_legacy",
            )
        },
        "diferencias_no_explicadas": diferencias,
        "discrepancias_explicadas": {
            "vendido_centavos": (
                operativo["vendido_centavos_bruto_operativo"] - operativo["vendido_centavos"]
            ),
            "pendiente_centavos": (
                operativo["pendiente_centavos_bruto_operativo"] - operativo["pendiente_centavos"]
            ),
            "pedidos_sin_monto_completo": operativo["pedidos_sin_monto_valido"],
            "pedidos_monetarios_anomalos": operativo["pedidos_monetarios_anomalos"],
        },
        "nota": (
            "El reporte operativo suma importes anómalos; BI los excluye. "
            "Las filas sin importe completo no son representables en V4. "
            "Legacy se convierte desde soles; el saldo es actual, no caja histórica."
        ),
    }


def _reconciliar(corte) -> dict:
    """Compara XLSX y JSON en memoria; devuelve solo el resumen permitido."""
    from app.services.bi_excel import exportar_xlsx_agregado
    from app.services.bi_presentacion import serializar_corte_json

    dato = json.loads(serializar_corte_json(corte))
    libro = load_workbook(BytesIO(exportar_xlsx_agregado(corte)), read_only=True)
    try:
        if libro.sheetnames != [
            "Resumen", "Serie diaria", "Calendario diario", "Actividad clientes", "Metadatos"
        ]:
            raise ValueError("Hojas XLSX inesperadas")
        resumen_xlsx = dict(libro["Resumen"].values)
        metadatos_xlsx = dict(libro["Metadatos"].values)
        if any(resumen_xlsx.get(k) != v for k, v in dato["resumen"].items()):
            raise ValueError("Resumen JSON/XLSX difiere")
        for campo in (
            "version_definiciones", "generado_en", "zona_horaria", "fuente",
            "fecha_base", "n_pedidos_base",
        ):
            if metadatos_xlsx.get(campo) != dato[campo]:
                raise ValueError("Metadatos JSON/XLSX difieren")
        for grupo in ("filtros", "cobertura"):
            for campo, valor in dato[grupo].items():
                if metadatos_xlsx.get(f"{grupo}.{campo}") != valor:
                    raise ValueError("Filtros o cobertura JSON/XLSX difieren")
        for numero, aviso in enumerate(dato["avisos"], start=1):
            if metadatos_xlsx.get(f"aviso.{numero}") != aviso:
                raise ValueError("Avisos JSON/XLSX difieren")
        cabecera, *filas = list(libro["Serie diaria"].values)
        serie_xlsx = [dict(zip(cabecera, fila)) for fila in filas]
        if serie_xlsx != dato["serie_diaria"]:
            raise ValueError("Serie JSON/XLSX difiere")
        cabecera_calendario, *filas_calendario = list(libro["Calendario diario"].values)
        calendario_xlsx = [
            dict(zip(cabecera_calendario, fila)) for fila in filas_calendario
        ]
        if calendario_xlsx != dato["calendario_diario"]:
            raise ValueError("Calendario JSON/XLSX difiere")
        if len(calendario_xlsx) != (
            date.fromisoformat(dato["filtros"]["hasta"])
            - date.fromisoformat(dato["filtros"]["desde"])
        ).days + 1:
            raise ValueError("Calendario no cubre el rango completo")
        medidas = (
            "pedidos_activos", "balones_vendidos", "balones_10kg", "balones_45kg",
            "vendido_centavos", "pendiente_centavos", "cobrado_calculado_centavos",
            "pedidos_con_monto_valido",
        )
        if any(
            sum(fila[campo] for fila in dato["serie_diaria"]) != dato["resumen"][campo]
            for campo in medidas
        ):
            raise ValueError("Serie y resumen no reconcilian")
        if any(
            sum(fila[campo] for fila in calendario_xlsx) != dato["resumen"][campo]
            for campo in medidas
        ):
            raise ValueError("Calendario y resumen no reconcilian")
        if dato["resumen"]["vendido_centavos"] != (
            dato["resumen"]["cobrado_calculado_centavos"]
            + dato["resumen"]["pendiente_centavos"]
        ):
            raise ValueError("Importes no reconcilian")
        if dato["n_pedidos_base"] != dato["resumen"]["pedidos_activos"]:
            raise ValueError("Población y resumen no reconcilian")
        if dato["resumen"]["balones_vendidos"] != (
            dato["resumen"]["balones_10kg"] + dato["resumen"]["balones_45kg"]
        ):
            raise ValueError("Balones por peso no reconcilian")
        if dato["resumen"]["pedidos_con_monto_valido"] + (
            dato["cobertura"]["pedidos_sin_monto_valido"]
            + dato["cobertura"]["pedidos_monetarios_anomalos"]
        ) != dato["n_pedidos_base"]:
            raise ValueError("Cobertura monetaria no reconcilia")

        actividad = dato["actividad_clientes"]
        filas_actividad = list(libro["Actividad clientes"].values)
        metricas_actividad = (
            "clientes_con_cadencia_explorable", "intervalos_observados",
            "mediana_intervalo_dias", "corte_cohortes_hasta",
        )
        if any(
            not any(fila[:2] == (campo, actividad[campo]) for fila in filas_actividad)
            for campo in metricas_actividad
        ):
            raise ValueError("Actividad JSON/XLSX difiere")
        if any(
            not any(fila[:2] == (campo, valor) for fila in filas_actividad)
            for campo, valor in actividad["cadencia_clientes"].items()
        ):
            raise ValueError("Cadencia JSON/XLSX difiere")
        if any(
            not any(
                fila[:2] == (mes["mes"], mes["clientes_compradores"])
                for fila in filas_actividad
            )
            for mes in actividad["meses"]
        ):
            raise ValueError("Meses JSON/XLSX difieren")
        if any(
            not any(
                fila[:5] == tuple(cohorte[campo] for campo in (
                    "ventana_dias", "elegibles", "retornaron", "censurados", "porcentaje"
                ))
                for fila in filas_actividad
            )
            for cohorte in actividad["cohortes_retorno"]
        ):
            raise ValueError("Cohortes JSON/XLSX difieren")
        if any(
            cohorte["elegibles"] + cohorte["censurados"]
            != dato["resumen"]["primera_compra_observada_en_periodo"]
            for cohorte in actividad["cohortes_retorno"]
        ):
            raise ValueError("Denominadores de cohortes no reconcilian")
        return {
            "version_definiciones": dato["version_definiciones"],
            "generado_en": dato["generado_en"],
            "filtros": dato["filtros"],
            "n_pedidos_base": dato["n_pedidos_base"],
            "resumen": dato["resumen"],
            "cobertura": dato["cobertura"],
            "checks": {
                "json_xlsx": "ok", "serie_resumen": "ok", "actividad": "ok",
                "cobertura": "ok", "importes": "ok",
            },
        }
    finally:
        libro.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconciliar BI con lectura privada acotada")
    parser.add_argument("--desde", required=True)
    parser.add_argument("--hasta", required=True)
    parser.add_argument("--peso", type=int, choices=(10, 45))
    parser.add_argument("--calidad-fuentes", action="store_true")
    args = parser.parse_args()
    # Settings de la app usa .env relativo al cwd. Aislarlo antes de importar
    # cualquier módulo app y restaurarlo al salir evita lectura accidental.
    directorio_original = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="gas-bi-readonly-") as aislado:
        os.chdir(aislado)
        os.environ["APP_STORAGE_BACKEND"] = "postgres"
        os.environ.pop("DATABASE_URL", None)
        try:
            return _ejecutar(args)
        finally:
            os.chdir(directorio_original)


def _ejecutar(args) -> int:
    try:
        desde, hasta = _validar_fechas(args.desde, args.hasta)
        url = _validar_dsn(getpass.getpass("DSN de gas_readonly (entrada oculta): "))
        engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 5,
                "options": (
                    "-c default_transaction_read_only=on "
                    "-c statement_timeout=15000 "
                    "-c lock_timeout=3000 "
                    "-c idle_in_transaction_session_timeout=20000 "
                    "-c search_path=public"
                ),
            },
        )
        try:
            corte, operativo, calidad = _obtener_corte(
                engine, desde=desde, hasta=hasta, peso=args.peso,
                calidad_fuentes=args.calidad_fuentes,
            )
        finally:
            engine.dispose()
        salida = _reconciliar(corte)
        salida["comparacion_operativa"] = _comparar_operativo(salida, operativo)
        if calidad is not None:
            salida["calidad_fuentes"] = calidad
        print(json.dumps(salida, ensure_ascii=False, allow_nan=False))
        return 0 if salida["comparacion_operativa"]["estado"] in {
            "ok", "ok_con_legacy"
        } else 2
    except Exception:
        print("Reconciliación interrumpida; no se emitieron datos ni detalles de conexión.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
