"""Casos sintéticos del corte BI y de sus consultas; nunca usa PostgreSQL real."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.infrastructure.repositories import bi as repo_bi
from app.models.models import Cliente, Direccion, Pedido
from app.services import bi


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Cliente.__table__, Direccion.__table__, Pedido.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


def _pedido(db, pedido_id, cliente_id, fecha, *, peso=10, cantidad=1,
            total=7000, pendiente=0, estado="ACTIVO", legacy_total="70.00",
            legacy_pendiente="0.00"):
    db.execute(insert(Cliente).values(
        id=cliente_id, alias=f"sintetico-{cliente_id}", telefono="000"
    ).prefix_with("OR IGNORE"))
    db.execute(insert(Direccion).values(
        id=cliente_id, cliente_id=cliente_id, texto_original="Dirección sintética"
    ).prefix_with("OR IGNORE"))
    db.execute(insert(Pedido).values(
        id=pedido_id, cliente_id=cliente_id, direccion_id=cliente_id,
        fecha_entrega=fecha, peso_balon_kg=peso, cantidad_balones=cantidad,
        total_soles=Decimal(legacy_total), saldo_pendiente=Decimal(legacy_pendiente),
        monto_total_centavos=total, monto_pendiente_centavos=pendiente,
        estado=estado, pagado=pendiente == 0,
    ))
    db.flush()


def test_repositorio_filtra_activos_y_peso_pero_historia_incluye_antes_de_desde(db):
    _pedido(db, 1, 1, date(2026, 9, 1))
    _pedido(db, 2, 1, date(2026, 10, 1))
    _pedido(db, 3, 1, date(2026, 10, 1))
    _pedido(db, 4, 1, date(2026, 10, 2), peso=45)
    _pedido(db, 5, 2, date(2026, 10, 1), estado="ANULADO")
    _pedido(db, 6, 3, date(2026, 10, 4))

    todos = repo_bi.listar_activos_en_rango(
        db, desde=date(2026, 10, 1), hasta=date(2026, 10, 2), peso_balon_kg=None
    )
    diez = repo_bi.listar_activos_en_rango(
        db, desde=date(2026, 10, 1), hasta=date(2026, 10, 2), peso_balon_kg=10
    )
    historia = repo_bi.listar_dias_activos_de_compradores(
        db, hasta=date(2026, 10, 2), cliente_ids={1}, peso_balon_kg=10
    )
    assert [(p.cliente_id, p.peso_balon_kg) for p in todos] == [(1, 10), (1, 10), (1, 45)]
    assert len(diez) == 2
    assert historia == [(1, date(2026, 9, 1)), (1, date(2026, 10, 1))]
    assert repo_bi.listar_dias_activos_de_compradores(
        db, hasta=date(2026, 10, 2), cliente_ids=set(), peso_balon_kg=None
    ) == []


def test_corte_con_repositorio_real_agrega_ventas_y_deduplica_dias(db, monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 13))
    _pedido(db, 1, 1, date(2026, 9, 1))
    _pedido(db, 2, 1, date(2026, 10, 1), cantidad=2, total=14000)
    _pedido(db, 3, 1, date(2026, 10, 1))
    _pedido(db, 4, 1, date(2026, 10, 3), peso=45, total=10000)
    _pedido(db, 5, 2, date(2026, 10, 2), estado="ANULADO")
    _pedido(db, 6, 3, date(2026, 10, 3), total=None, pendiente=None,
            legacy_total="70.25", legacy_pendiente="0.50")
    _pedido(db, 7, 4, date(2026, 10, 3), total=7000, pendiente=8000)

    corte = bi.construir_corte(db, desde=date(2026, 10, 1), hasta=date(2026, 10, 3))
    resumen = corte["resumen"]
    assert corte["n_pedidos_base"] == 5
    assert resumen["pedidos_activos"] == 5
    assert resumen["balones_vendidos"] == 6
    assert (resumen["balones_10kg"], resumen["balones_45kg"]) == (5, 1)
    assert (resumen["vendido_centavos"], resumen["pendiente_centavos"]) == (38025, 50)
    assert resumen["pedidos_con_monto_valido"] == 4
    assert resumen["clientes_compradores"] == 3
    assert resumen["primera_compra_observada_en_periodo"] == 2
    assert resumen["compradores_que_volvieron_en_periodo"] == 1
    assert corte["actividad_clientes"]["intervalos_observados"] == 2
    assert corte["actividad_clientes"]["mediana_intervalo_dias"] == 16
    assert corte["actividad_clientes"]["clientes_con_cadencia_explorable"] == 1
    assert corte["actividad_clientes"]["cadencia_clientes"] == {
        "definicion": "mediana_de_intervalos_por_cliente_hasta_hasta_min_3_dias",
        "clientes_elegibles": 1,
        "intervalos_de_elegibles": 2,
        "mediana_de_medianas_dias": 16,
        "p25_medianas_dias": 16,
        "p75_medianas_dias": 16,
    }
    assert corte["cobertura"] == {
        "pedidos_monto_total_legacy": 1,
        "pedidos_pendiente_legacy": 1,
        "pedidos_sin_monto_valido": 0,
        "pedidos_monetarios_anomalos": 1,
    }
    assert [(r["fecha"], r["peso_balon_kg"], r["pedidos_activos"])
            for r in corte["serie_diaria"]] == [
        ("2026-10-01", 10, 2), ("2026-10-03", 10, 2), ("2026-10-03", 45, 1)
    ]
    assert sum(r["vendido_centavos"] for r in corte["serie_diaria"]) == resumen["vendido_centavos"]
    assert [r["fecha"] for r in corte["calendario_diario"]] == [
        "2026-10-01", "2026-10-02", "2026-10-03"
    ]
    assert corte["calendario_diario"][1]["pedidos_activos"] == 0
    assert corte["calendario_diario"][1]["vendido_centavos"] == 0
    assert sum(r["vendido_centavos"] for r in corte["calendario_diario"]) == resumen["vendido_centavos"]
    assert corte["actividad_clientes"]["meses"] == [{"mes": "2026-10", "clientes_compradores": 3}]


def test_corte_filtrado_por_peso_clasifica_historia_del_mismo_peso(db, monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 13))
    _pedido(db, 1, 1, date(2026, 9, 1), peso=10)
    _pedido(db, 2, 1, date(2026, 10, 1), peso=45)
    _pedido(db, 3, 1, date(2026, 10, 3), peso=45)
    corte = bi.construir_corte(
        db, desde=date(2026, 10, 1), hasta=date(2026, 10, 3), peso_balon_kg=45
    )
    assert corte["filtros"]["peso_balon_kg"] == 45
    assert corte["resumen"]["primera_compra_observada_en_periodo"] == 1
    assert corte["resumen"]["compradores_que_volvieron_en_periodo"] == 1
    assert corte["actividad_clientes"]["intervalos_observados"] == 1
    assert corte["actividad_clientes"]["mediana_intervalo_dias"] == 2


def test_cohortes_30_60_90_censura_y_dia_abierto(monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 13))
    pedidos = [
        repo_bi.PedidoBI(cid, dia, 10, 1, 7000, Decimal("70"), 0, Decimal("0"))
        for cid, dia in [
            (1, date(2026, 7, 1)), (2, date(2026, 8, 1)),
            (3, date(2026, 9, 1)), (4, date(2026, 10, 13)),
        ]
    ]
    historia = [
        (1, date(2026, 7, 1)), (1, date(2026, 7, 20)),
        (2, date(2026, 8, 1)), (2, date(2026, 9, 15)),
        (3, date(2026, 9, 1)), (4, date(2026, 10, 13)),
    ]
    monkeypatch.setattr(bi.repo_bi, "listar_activos_en_rango", lambda *a, **k: pedidos)
    monkeypatch.setattr(bi.repo_bi, "listar_dias_activos_de_compradores", lambda *a, **k: historia)
    monkeypatch.setattr(bi, "is_dynamodb_enabled", lambda: False)
    corte = bi.construir_corte(object(), desde=date(2026, 7, 1), hasta=date(2026, 10, 13))
    assert corte["actividad_clientes"]["corte_cohortes_hasta"] == "2026-10-12"
    assert corte["actividad_clientes"]["cohortes_retorno"] == [
        {"ventana_dias": 30, "elegibles": 3, "retornaron": 1, "censurados": 1, "porcentaje": 33.33},
        {"ventana_dias": 60, "elegibles": 2, "retornaron": 2, "censurados": 2, "porcentaje": 100.0},
        {"ventana_dias": 90, "elegibles": 1, "retornaron": 1, "censurados": 3, "porcentaje": 100.0},
    ]
    assert any("día de hoy sigue abierto" in aviso for aviso in corte["avisos"])


def test_montos_faltantes_y_anomalos_no_se_imputan_como_cero(monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 13))
    filas = [
        repo_bi.PedidoBI(1, date(2026, 10, 1), 10, 1, None, None, 0, Decimal("0")),
        repo_bi.PedidoBI(2, date(2026, 10, 1), 10, 1, 7000, Decimal("70"), None, None),
        repo_bi.PedidoBI(3, date(2026, 10, 1), 10, 1, 7000, Decimal("70"), -1, Decimal("0")),
        repo_bi.PedidoBI(4, date(2026, 10, 1), 10, 1, 7000, Decimal("70"), 0, Decimal("0")),
    ]
    monkeypatch.setattr(bi.repo_bi, "listar_activos_en_rango", lambda *a, **k: filas)
    monkeypatch.setattr(bi.repo_bi, "listar_dias_activos_de_compradores", lambda *a, **k: [
        (cid, date(2026, 10, 1)) for cid in range(1, 5)
    ])
    monkeypatch.setattr(bi, "is_dynamodb_enabled", lambda: False)
    corte = bi.construir_corte(object(), desde=date(2026, 10, 1), hasta=date(2026, 10, 1))
    assert corte["resumen"]["pedidos_activos"] == 4
    assert corte["resumen"]["pedidos_con_monto_valido"] == 1
    assert corte["resumen"]["vendido_centavos"] == 7000
    assert corte["cobertura"]["pedidos_sin_monto_valido"] == 2
    assert corte["cobertura"]["pedidos_monetarios_anomalos"] == 1
    assert any("importes excluyen" in aviso for aviso in corte["avisos"])


def test_periodo_sin_pedidos_conserva_filtros_y_calendario(db, monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 13))
    corte = bi.construir_corte(db, desde=date(2026, 10, 1), hasta=date(2026, 10, 2))
    assert corte["filtros"]["desde"] == "2026-10-01"
    assert corte["filtros"]["hasta"] == "2026-10-02"
    assert corte["n_pedidos_base"] == 0
    assert corte["resumen"]["clientes_compradores"] == 0
    assert corte["serie_diaria"] == []  # La v1 no rellena días sin pedidos con ceros.
    assert [(r["fecha"], r["pedidos_activos"]) for r in corte["calendario_diario"]] == [
        ("2026-10-01", 0), ("2026-10-02", 0)
    ]
    assert corte["actividad_clientes"]["meses"] == []
    assert corte["actividad_clientes"]["cadencia_clientes"]["mediana_de_medianas_dias"] is None
    assert all(x["porcentaje"] is None for x in corte["actividad_clientes"]["cohortes_retorno"])


def test_cadencia_por_cliente_evita_sobrepeso_de_comprador_frecuente(monkeypatch):
    monkeypatch.setattr(bi, "fecha_hoy_lima", lambda: date(2026, 10, 14))
    dias_cliente_1 = [date(2026, 9, dia) for dia in (1, 2, 3, 4, 5)]
    dias_cliente_2 = [date(2026, 9, dia) for dia in (1, 11, 21)]
    dias_cliente_3 = [date(2026, 9, dia) for dia in (1, 21)]
    historia = [
        *((1, dia) for dia in dias_cliente_1),
        *((2, dia) for dia in dias_cliente_2),
        *((3, dia) for dia in dias_cliente_3),
    ]
    pedidos = [
        repo_bi.PedidoBI(cid, dia, 10, 1, 7000, Decimal("70"), 0, Decimal("0"))
        for cid, dia in historia
    ]
    monkeypatch.setattr(bi.repo_bi, "listar_activos_en_rango", lambda *a, **k: pedidos)
    monkeypatch.setattr(bi.repo_bi, "listar_dias_activos_de_compradores", lambda *a, **k: historia)
    monkeypatch.setattr(bi, "is_dynamodb_enabled", lambda: False)
    corte = bi.construir_corte(object(), desde=date(2026, 9, 1), hasta=date(2026, 9, 21))
    actividad = corte["actividad_clientes"]
    assert corte["version_definiciones"] == "bi-v1.1"
    assert actividad["intervalos_observados"] == 7
    assert actividad["mediana_intervalo_dias"] == 1  # Legacy: todos los intervalos agrupados.
    assert actividad["cadencia_clientes"] == {
        "definicion": "mediana_de_intervalos_por_cliente_hasta_hasta_min_3_dias",
        "clientes_elegibles": 2,
        "intervalos_de_elegibles": 6,
        "mediana_de_medianas_dias": 5.5,
        "p25_medianas_dias": 3.25,
        "p75_medianas_dias": 7.75,
    }
