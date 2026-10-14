"""Comparación de dos rutas de reporte con pedidos sintéticos y SQLite local."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.models import (
    Cliente, DemandaPerdida, Direccion, MovimientoStock, Pedido, StockJornada,
)
from app.services import bi
from scripts import reconciliar_bi_readonly as cli


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine, tables=[
            Cliente.__table__, Direccion.__table__, Pedido.__table__,
            StockJornada.__table__, MovimientoStock.__table__, DemandaPerdida.__table__,
        ]
    )
    with Session(engine) as session:
        yield session
    engine.dispose()


def _pedido(db, identificador, fecha, *, peso=10, cantidad=1, total=7000,
            pendiente=0, legacy_total="70.00", legacy_pendiente="0.00",
            estado="ACTIVO"):
    db.execute(insert(Cliente).values(
        id=identificador, alias=f"persona-{identificador}", telefono="000"
    ))
    db.execute(insert(Direccion).values(
        id=identificador, cliente_id=identificador, texto_original="Dirección sintética"
    ))
    db.execute(insert(Pedido).values(
        id=identificador, cliente_id=identificador, direccion_id=identificador,
        fecha_entrega=fecha, peso_balon_kg=peso, cantidad_balones=cantidad,
        monto_total_centavos=total, monto_pendiente_centavos=pendiente,
        total_soles=Decimal(legacy_total),
        saldo_pendiente=Decimal(legacy_pendiente), estado=estado,
    ))
    db.flush()


def test_reporte_operativo_independiente_reconcilia_y_explica_anomalia(db, monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 14))
    _pedido(db, 1, date(2026, 10, 1), cantidad=2, total=14000)
    _pedido(db, 2, date(2026, 10, 2), total=None, pendiente=None,
            legacy_total="70.25", legacy_pendiente="0.50")
    _pedido(db, 3, date(2026, 10, 2), peso=45, total=10000, pendiente=11000)
    _pedido(db, 4, date(2026, 10, 2), estado="ANULADO")
    _pedido(db, 5, date(2026, 10, 3))

    desde, hasta = date(2026, 10, 1), date(2026, 10, 2)
    corte = bi.construir_corte(db, desde=desde, hasta=hasta)
    operativo = cli._obtener_operativo(db, desde=desde, hasta=hasta, peso=None)
    salida = cli._comparar_operativo(cli._reconciliar(corte), operativo)

    assert salida["estado"] == "requiere_revision"
    assert salida["medidas"]["pedidos_activos"] == 3
    assert salida["medidas"]["balones_vendidos"] == 4
    assert salida["medidas"]["vendido_centavos"] == 21025
    assert salida["calidad"]["pedidos_monto_total_legacy"] == 1
    assert salida["calidad"]["pedidos_pendiente_legacy"] == 1
    assert salida["calidad"]["pedidos_monetarios_anomalos"] == 1
    assert salida["discrepancias_explicadas"] == {
        "vendido_centavos": 10000, "pendiente_centavos": 11000,
        "pedidos_sin_monto_completo": 0, "pedidos_monetarios_anomalos": 1,
    }
    assert "persona-" not in str(salida)
    assert "Dirección" not in str(salida)


def test_peso_y_fecha_se_aplican_igual_en_ambas_rutas(db, monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 14))
    _pedido(db, 1, date(2026, 10, 1), peso=10)
    _pedido(db, 2, date(2026, 10, 2), peso=45, total=10000)
    _pedido(db, 3, date(2026, 10, 3), peso=10)
    desde, hasta = date(2026, 10, 1), date(2026, 10, 2)
    corte = bi.construir_corte(db, desde=desde, hasta=hasta, peso_balon_kg=45)
    operativo = cli._obtener_operativo(db, desde=desde, hasta=hasta, peso=45)
    salida = cli._comparar_operativo(cli._reconciliar(corte), operativo)
    assert salida["estado"] == "ok"
    assert salida["medidas"]["pedidos_activos"] == 1
    assert salida["medidas"]["balones_10kg"] == 0
    assert salida["medidas"]["balones_45kg"] == 1


def test_faltante_no_se_imputa_y_se_marca_incompatible_con_reporte_v4(monkeypatch):
    from app.infrastructure.repositories import reportes as repo_reportes

    pedido = SimpleNamespace(
        peso_balon_kg=10, cantidad_balones=1, monto_total_centavos=None,
        total_soles=None, monto_pendiente_centavos=0, saldo_pendiente=Decimal("0"),
    )
    monkeypatch.setattr(repo_reportes, "listar_pedidos_por_rango", lambda *a, **k: [pedido])
    operativo = cli._obtener_operativo(
        object(), desde=date(2026, 10, 1), hasta=date(2026, 10, 1), peso=None
    )
    assert operativo["pedidos_activos"] == 1
    assert operativo["pedidos_sin_monto_valido"] == 1
    assert operativo["pedidos_con_monto_valido"] == 0
    assert operativo["vendido_centavos"] == 0
    salida_bi = {"resumen": {
        "pedidos_activos": 1, "balones_vendidos": 1, "balones_10kg": 1,
        "balones_45kg": 0, "vendido_centavos": 0, "pendiente_centavos": 0,
        "cobrado_calculado_centavos": 0, "pedidos_con_monto_valido": 0,
    }, "cobertura": {
        "pedidos_sin_monto_valido": 1, "pedidos_monetarios_anomalos": 0,
        "pedidos_monto_total_legacy": 0, "pedidos_pendiente_legacy": 0,
    }}
    comparacion = cli._comparar_operativo(salida_bi, operativo)
    assert comparacion["estado"] == "requiere_revision"
    assert comparacion["discrepancias_explicadas"]["pedidos_sin_monto_completo"] == 1


def test_desacuerdo_no_explicado_falla_la_puerta_con_delta_agregado(db, monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 14))
    _pedido(db, 1, date(2026, 10, 1))
    corte = bi.construir_corte(db, desde=date(2026, 10, 1), hasta=date(2026, 10, 1))
    operativo = cli._obtener_operativo(
        db, desde=date(2026, 10, 1), hasta=date(2026, 10, 1), peso=None
    )
    operativo["vendido_centavos"] += 1
    salida = cli._comparar_operativo(cli._reconciliar(corte), operativo)
    assert salida["estado"] == "difiere"
    assert salida["diferencias_no_explicadas"] == {"vendido_centavos": 1}


def test_calidad_fuentes_mide_cobertura_sin_sumar_demanda_a_ventas(db):
    _pedido(db, 1, date(2026, 10, 1), peso=10)
    _pedido(db, 2, date(2026, 10, 2), peso=45)
    db.execute(update(Cliente).where(Cliente.id == 1).values(canal_captacion="VOLANTE"))
    db.execute(insert(DemandaPerdida).values(
        fecha=date(2026, 10, 1), motivo="SIN_STOCK", cantidad_balones=2,
        peso_balon_kg=10,
    ))
    db.execute(insert(DemandaPerdida).values(
        fecha=date(2026, 10, 2), motivo="SATURADO", cantidad_balones=1,
        peso_balon_kg=45,
    ))
    db.execute(insert(StockJornada).values(
        id=1, fecha=date(2026, 10, 1), stock_inicial=10,
        stock_actual=8, cerrado=True, stock_final_fisico=8,
    ))
    db.execute(insert(MovimientoStock).values(
        stock_jornada_id=1, fecha=date(2026, 10, 1), tipo="SALIDA_PEDIDO",
        cantidad_delta=-2, stock_resultante=8, peso_balon_kg=10,
    ))
    db.flush()

    calidad = cli._medir_calidad_fuentes(
        db, desde=date(2026, 10, 1), hasta=date(2026, 10, 3), peso=10,
        tablas_seguras={"clientes", "demanda_perdida", "stock_jornadas", "movimientos_stock"},
    )
    assert calidad["canal_compradores"] == {
        "estado": "medido", "compradores": 1,
        "con_canal_conocido": 1, "sin_canal": 0,
    }
    assert calidad["altas_clientes_en_ventana"] == "no_medible_sin_fecha_alta"
    assert calidad["demanda_no_atendida"]["eventos_registrados"] == 1
    assert calidad["demanda_no_atendida"]["balones_registrados"] == 2
    assert calidad["demanda_no_atendida"]["dias_con_registro"] == 1
    assert calidad["jornadas_stock"]["dias_rango"] == 3
    assert calidad["jornadas_stock"]["jornadas"] == 1
    assert calidad["jornadas_stock"]["cerradas"] == 1
    assert calidad["movimientos_stock"]["movimientos"] == 1
    assert calidad["movimientos_stock"]["por_tipo_y_peso"][0]["delta_neto"] == -2
    assert "persona-" not in str(calidad)


def test_fuentes_no_autorizadas_no_se_consultan():
    class SesionProhibida:
        def execute(self, *_):
            pytest.fail("Leyó una tabla sin privilegios comprobados")

    calidad = cli._medir_calidad_fuentes(
        SesionProhibida(), desde=date(2026, 10, 1), hasta=date(2026, 10, 2),
        peso=None, tablas_seguras=set(),
    )
    assert all(calidad[fuente]["estado"] == "no_disponible" for fuente in (
        "canal_compradores", "demanda_no_atendida", "jornadas_stock", "movimientos_stock"
    ))


def test_calidad_tabla_rechaza_cualquier_privilegio_de_escritura():
    def fila(tabla, **cambios):
        base = {
            "tabla": tabla, "puede_leer": True, "puede_insertar": False,
            "puede_actualizar": False, "puede_borrar": False,
            "puede_truncar": False,
        }
        return {**base, **cambios}

    seguras = cli._tablas_calidad_seguras([
        fila("clientes"), fila("demanda_perdida", puede_borrar=True),
        fila("stock_jornadas", puede_leer=False),
        fila("movimientos_stock", puede_insertar=True),
    ])
    assert seguras == {"clientes"}
