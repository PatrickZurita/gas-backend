"""Cálculo BI v1 compartido por futuras salidas JSON y Excel.

No publica rutas ni datos nominales. Un resultado corresponde a un corte de
lectura; sin transacción de snapshot no se promete identidad entre consultas
realizadas en momentos diferentes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import median, quantiles
from typing import TypedDict

from sqlalchemy.orm import Session

from app.core.storage import is_dynamodb_enabled
from app.core.time import LIMA_TZ, fecha_hoy_lima
from app.infrastructure.repositories import bi as repo_bi

VERSION_DEFINICIONES = "bi-v1.1"
RANGO_MAXIMO_DIAS = 366
VENTANAS_RETORNO_DIAS = (30, 60, 90)


class FiltrosBI(TypedDict):
    desde: str
    hasta: str
    peso_balon_kg: int | str
    estado: str


class SerieDiariaBI(TypedDict):
    fecha: str
    peso_balon_kg: int
    pedidos_activos: int
    balones_vendidos: int
    balones_10kg: int
    balones_45kg: int
    vendido_centavos: int
    pendiente_centavos: int
    cobrado_calculado_centavos: int
    pedidos_con_monto_valido: int


class CohorteRetornoBI(TypedDict):
    ventana_dias: int
    elegibles: int
    retornaron: int
    censurados: int
    porcentaje: float | None


class ResumenBI(TypedDict):
    pedidos_activos: int
    balones_vendidos: int
    balones_10kg: int
    balones_45kg: int
    vendido_centavos: int
    pendiente_centavos: int
    cobrado_calculado_centavos: int
    pedidos_con_monto_valido: int
    clientes_compradores: int
    primera_compra_observada_en_periodo: int
    compradores_que_volvieron_en_periodo: int


class ActividadClientesBI(TypedDict):
    meses: list[dict[str, str | int]]
    clientes_con_cadencia_explorable: int
    intervalos_observados: int
    mediana_intervalo_dias: float | int | None
    cadencia_clientes: CadenciaClientesBI
    corte_cohortes_hasta: str
    cohortes_retorno: list[CohorteRetornoBI]


class CadenciaClientesBI(TypedDict):
    definicion: str
    clientes_elegibles: int
    intervalos_de_elegibles: int
    mediana_de_medianas_dias: float | int | None
    p25_medianas_dias: float | int | None
    p75_medianas_dias: float | int | None


class CorteBI(TypedDict):
    version_definiciones: str
    generado_en: str
    zona_horaria: str
    fuente: str
    fecha_base: str
    filtros: FiltrosBI
    n_pedidos_base: int
    resumen: ResumenBI
    serie_diaria: list[SerieDiariaBI]
    calendario_diario: list[dict[str, str | int]]
    actividad_clientes: ActividadClientesBI
    cobertura: dict[str, int]
    avisos: list[str]


def _centavos(valor: int | None, legacy: Decimal | None) -> tuple[int | None, bool]:
    if valor is not None:
        return valor, False
    if legacy is None:
        return None, False
    return int((legacy * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), True


def _medidas() -> dict[str, int]:
    return {
        "pedidos_activos": 0,
        "balones_vendidos": 0,
        "balones_10kg": 0,
        "balones_45kg": 0,
        "vendido_centavos": 0,
        "pendiente_centavos": 0,
        "cobrado_calculado_centavos": 0,
        "pedidos_con_monto_valido": 0,
    }


def construir_corte(
    db: Session | None, *, desde: date, hasta: date, peso_balon_kg: int | None = None
) -> CorteBI:
    """Construye resumen, serie diaria y actividad con un filtro único.

    `None` en peso significa todos; los valores permitidos son 10 y 45 kg.
    Pedidos monetariamente anómalos cuentan como actividad y unidades, pero
    no aportan importes al total. La cobertura informa esa exclusión.
    """
    if desde > hasta:
        raise ValueError("desde debe ser anterior o igual a hasta")
    hoy_lima = fecha_hoy_lima()
    if hasta > hoy_lima:
        raise ValueError("hasta no puede ser posterior a hoy en Lima")
    if (hasta - desde).days + 1 > RANGO_MAXIMO_DIAS:
        raise ValueError(f"El rango máximo es {RANGO_MAXIMO_DIAS} días")
    if peso_balon_kg not in (None, 10, 45):
        raise ValueError("peso_balon_kg debe ser 10, 45 o todos")
    if is_dynamodb_enabled() or db is None:
        raise RuntimeError("BI v1 solo está disponible para PostgreSQL")

    pedidos = repo_bi.listar_activos_en_rango(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg
    )
    compradores = {p.cliente_id for p in pedidos}
    historia: dict[int, list[date]] = defaultdict(list)
    for cliente_id, fecha in repo_bi.listar_dias_activos_de_compradores(
        db, hasta=hasta, cliente_ids=compradores, peso_balon_kg=peso_balon_kg
    ):
        historia[cliente_id].append(fecha)

    resumen = _medidas()
    serie: dict[tuple[date, int], dict[str, int]] = defaultdict(_medidas)
    clientes_mes: dict[str, set[int]] = defaultdict(set)
    cobertura = {
        "pedidos_monto_total_legacy": 0,
        "pedidos_pendiente_legacy": 0,
        "pedidos_sin_monto_valido": 0,
        "pedidos_monetarios_anomalos": 0,
    }

    for pedido in pedidos:
        grupo = serie[(pedido.fecha_entrega, pedido.peso_balon_kg)]
        clientes_mes[pedido.fecha_entrega.strftime("%Y-%m")].add(pedido.cliente_id)
        for bucket in (resumen, grupo):
            bucket["pedidos_activos"] += 1
            bucket["balones_vendidos"] += pedido.cantidad_balones
            bucket[f"balones_{pedido.peso_balon_kg}kg"] += pedido.cantidad_balones

        total, total_legacy = _centavos(pedido.monto_total_centavos, pedido.total_soles)
        pendiente, pendiente_legacy = _centavos(
            pedido.monto_pendiente_centavos, pedido.saldo_pendiente
        )
        cobertura["pedidos_monto_total_legacy"] += int(total_legacy)
        cobertura["pedidos_pendiente_legacy"] += int(pendiente_legacy)
        if total is None or pendiente is None:
            cobertura["pedidos_sin_monto_valido"] += 1
            continue
        if total < 0 or pendiente < 0 or pendiente > total:
            cobertura["pedidos_monetarios_anomalos"] += 1
            continue
        for bucket in (resumen, grupo):
            bucket["pedidos_con_monto_valido"] += 1
            bucket["vendido_centavos"] += total
            bucket["pendiente_centavos"] += pendiente
            bucket["cobrado_calculado_centavos"] += total - pendiente

    primeras = {cliente_id: dias[0] for cliente_id, dias in historia.items() if dias}
    primeros_en_rango = {
        cliente_id for cliente_id, fecha in primeras.items() if desde <= fecha <= hasta
    }
    compradores_que_volvieron = sum(
        any(desde <= dia <= hasta and dia > dias[0] for dia in dias[1:])
        for dias in historia.values()
    )
    intervalos = [
        (actual - anterior).days
        for dias in historia.values()
        for anterior, actual in zip(dias, dias[1:])
        if desde <= actual <= hasta
    ]
    # Una mediana por comprador elegible evita que el comprador más frecuente
    # pese más veces que los demás en el resumen de cadencia individual.
    intervalos_elegibles = [
        [(actual - anterior).days for anterior, actual in zip(dias, dias[1:])]
        for dias in historia.values()
        if len(dias) >= 3
    ]
    medianas_por_cliente = [median(valores) for valores in intervalos_elegibles]
    if len(medianas_por_cliente) >= 2:
        p25, _, p75 = quantiles(medianas_por_cliente, n=4, method="inclusive")
    elif medianas_por_cliente:
        p25 = p75 = medianas_por_cliente[0]
    else:
        p25 = p75 = None
    cadencia_clientes: CadenciaClientesBI = {
        "definicion": "mediana_de_intervalos_por_cliente_hasta_hasta_min_3_dias",
        "clientes_elegibles": len(medianas_por_cliente),
        "intervalos_de_elegibles": sum(map(len, intervalos_elegibles)),
        "mediana_de_medianas_dias": (
            median(medianas_por_cliente) if medianas_por_cliente else None
        ),
        "p25_medianas_dias": p25,
        "p75_medianas_dias": p75,
    }
    serie_por_fecha: dict[date, dict[str, int]] = defaultdict(_medidas)
    for (dia, _peso), medidas in serie.items():
        for campo, valor in medidas.items():
            serie_por_fecha[dia][campo] += valor
    calendario_diario = [
        {"fecha": (desde + timedelta(days=offset)).isoformat(),
         **serie_por_fecha[desde + timedelta(days=offset)]}
        for offset in range((hasta - desde).days + 1)
    ]
    corte_cohortes = min(hasta, hoy_lima - timedelta(days=1))
    ventanas: list[CohorteRetornoBI] = []
    for w in VENTANAS_RETORNO_DIAS:
        elegibles = [
            cid for cid in primeros_en_rango
            if primeras[cid] + timedelta(days=w) <= corte_cohortes
        ]
        retornaron = sum(
            any(
                primeras[cid] < dia <= primeras[cid] + timedelta(days=w)
                for dia in historia[cid][1:]
            )
            for cid in elegibles
        )
        ventanas.append(
            {
                "ventana_dias": w,
                "elegibles": len(elegibles),
                "retornaron": retornaron,
                "censurados": len(primeros_en_rango) - len(elegibles),
                "porcentaje": (
                    round(100 * retornaron / len(elegibles), 2)
                    if elegibles else None
                ),
            }
        )

    avisos = [
        "fecha_entrega es el día operativo registrado; created_at no mide la hora de demanda.",
        "La carga tardía puede asignar fecha_entrega al día de registro si el operador no la corrige.",
        "El saldo pendiente es el actual al consultar, no el saldo histórico al cierre del día.",
        "Primera compra observada puede omitir compras anteriores al sistema.",
        "El peso 10 kg histórico puede provenir del valor por defecto de una migración.",
        "La cifra exacta de pedidos con peso 10 kg heredado no se puede recuperar del modelo actual.",
        "Los intervalos cuentan retornos en el rango; la compra anterior puede ser previa a desde.",
        "La mediana de intervalos es agrupada; cadencia_clientes usa una mediana por comprador elegible.",
        "Los ceros del calendario indican ausencia de pedidos activos registrados, no ausencia de demanda real.",
        "Consultas sucesivas pueden cambiar por ediciones: este corte no garantiza snapshot atómico.",
    ]
    if cobertura["pedidos_sin_monto_valido"] or cobertura["pedidos_monetarios_anomalos"]:
        avisos.append(
            "Los importes excluyen filas sin montos válidos o con saldo fuera de rango."
        )
    if hasta == hoy_lima:
        avisos.append(
            "El día de hoy sigue abierto; cohortes completas se evalúan hasta ayer."
        )

    return {
        "version_definiciones": VERSION_DEFINICIONES,
        "generado_en": datetime.now(LIMA_TZ).isoformat(),
        "zona_horaria": "America/Lima",
        "fuente": "PostgreSQL/pedidos",
        "fecha_base": "fecha_entrega_registrada",
        "filtros": {
            "desde": desde.isoformat(),
            "hasta": hasta.isoformat(),
            "peso_balon_kg": peso_balon_kg or "todos",
            "estado": "ACTIVO",
        },
        "n_pedidos_base": len(pedidos),
        "resumen": {
            **resumen,
            "clientes_compradores": len(compradores),
            "primera_compra_observada_en_periodo": len(primeros_en_rango),
            "compradores_que_volvieron_en_periodo": compradores_que_volvieron,
        },
        "serie_diaria": [
            {"fecha": dia.isoformat(), "peso_balon_kg": peso, **medidas}
            for (dia, peso), medidas in sorted(serie.items())
        ],
        "calendario_diario": calendario_diario,
        "actividad_clientes": {
            "meses": [
                {"mes": mes, "clientes_compradores": len(ids)}
                for mes, ids in sorted(clientes_mes.items())
            ],
            "clientes_con_cadencia_explorable": len(medianas_por_cliente),
            "intervalos_observados": len(intervalos),
            "mediana_intervalo_dias": median(intervalos) if intervalos else None,
            "cadencia_clientes": cadencia_clientes,
            "corte_cohortes_hasta": corte_cohortes.isoformat(),
            "cohortes_retorno": ventanas,
        },
        "cobertura": cobertura,
        "avisos": avisos,
    }
