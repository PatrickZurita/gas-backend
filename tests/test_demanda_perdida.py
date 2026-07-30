"""Tests P1 #2: `demanda_perdida` (la llamada que NO se pudo atender).

Cubre el contrato de la spec P1 (§7 demanda perdida): alta minima de dos
toques con defaults, validaciones 422, listado detalle, resumen agregado por
rango de fechas y el invariante clave de aislamiento: registrar demanda
perdida NO altera reportes ni stock del dia.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.time import fecha_hoy_lima
from app.db.base import Base
from app.main import app
from app.models.models import DemandaPerdida


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db_session(db_session_factory):
    db = db_session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session_factory):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _sembrar_evento(
    db,
    *,
    fecha: date,
    motivo: str = "SIN_STOCK",
    cantidad_balones: int = 1,
    peso_balon_kg: int = 10,
    zona_texto: str | None = None,
) -> DemandaPerdida:
    registro = DemandaPerdida(
        fecha=fecha,
        motivo=motivo,
        cantidad_balones=cantidad_balones,
        peso_balon_kg=peso_balon_kg,
        zona_texto=zona_texto,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


# ---------------------------------------------------------------------------
# POST /demanda-perdida — detalle
# ---------------------------------------------------------------------------


def test_registrar_solo_motivo_aplica_defaults_y_fecha_lima(client):
    """Payload minimo real desde la UI (dos toques)."""
    response = client.post("/demanda-perdida", json={"motivo": "SIN_STOCK"})

    assert response.status_code == 201
    body = response.json()
    assert body["motivo"] == "SIN_STOCK"
    assert body["cantidad_balones"] == 1
    assert body["peso_balon_kg"] == 10
    assert body["zona_texto"] is None
    assert body["fecha"] == fecha_hoy_lima().isoformat()
    assert body["id"] is not None
    assert body["created_at"] is not None


def test_registrar_con_opcionales(client):
    response = client.post(
        "/demanda-perdida",
        json={
            "motivo": "FUERA_DE_ZONA",
            "zona_texto": "  Musa, La Molina  ",
            "cantidad_balones": 3,
            "peso_balon_kg": 45,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["motivo"] == "FUERA_DE_ZONA"
    assert body["zona_texto"] == "Musa, La Molina"
    assert body["cantidad_balones"] == 3
    assert body["peso_balon_kg"] == 45


def test_registrar_motivo_case_insensitive(client):
    response = client.post("/demanda-perdida", json={"motivo": "saturado"})

    assert response.status_code == 201
    assert response.json()["motivo"] == "SATURADO"


def test_registrar_motivo_invalido_devuelve_422(client):
    response = client.post("/demanda-perdida", json={"motivo": "NO_CONTESTA"})

    assert response.status_code == 422


def test_registrar_peso_invalido_devuelve_422(client):
    response = client.post(
        "/demanda-perdida", json={"motivo": "SIN_STOCK", "peso_balon_kg": 20}
    )

    assert response.status_code == 422


def test_registrar_cantidad_cero_devuelve_422(client):
    response = client.post(
        "/demanda-perdida", json={"motivo": "SIN_STOCK", "cantidad_balones": 0}
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /demanda-perdida — listado detalle
# ---------------------------------------------------------------------------


def test_listar_ordena_created_at_desc_y_filtra_por_fecha(client, db_session):
    hoy = fecha_hoy_lima()
    _sembrar_evento(db_session, fecha=hoy - timedelta(days=10), motivo="OTRO")
    _sembrar_evento(db_session, fecha=hoy, motivo="SIN_STOCK")
    _sembrar_evento(db_session, fecha=hoy, motivo="SATURADO")

    todos = client.get("/demanda-perdida")
    assert todos.status_code == 200
    assert [item["motivo"] for item in todos.json()] == [
        "SATURADO",
        "SIN_STOCK",
        "OTRO",
    ]

    filtrado = client.get(
        "/demanda-perdida",
        params={"desde": hoy.isoformat(), "hasta": hoy.isoformat()},
    )
    assert filtrado.status_code == 200
    assert [item["motivo"] for item in filtrado.json()] == [
        "SATURADO",
        "SIN_STOCK",
    ]


def test_listar_respeta_limit(client, db_session):
    hoy = fecha_hoy_lima()
    for _ in range(3):
        _sembrar_evento(db_session, fecha=hoy)

    response = client.get("/demanda-perdida", params={"limit": 2})

    assert response.status_code == 200
    assert len(response.json()) == 2


# ---------------------------------------------------------------------------
# GET /demanda-perdida/resumen — agregado
# ---------------------------------------------------------------------------


def test_resumen_agrega_por_rango_motivo_y_peso(client, db_session):
    desde = date(2026, 7, 20)
    hasta = date(2026, 7, 26)
    _sembrar_evento(
        db_session, fecha=date(2026, 7, 20), motivo="SIN_STOCK",
        cantidad_balones=2, peso_balon_kg=10,
    )
    _sembrar_evento(
        db_session, fecha=date(2026, 7, 22), motivo="SIN_STOCK",
        cantidad_balones=1, peso_balon_kg=45,
    )
    _sembrar_evento(
        db_session, fecha=date(2026, 7, 26), motivo="FUERA_DE_ZONA",
        cantidad_balones=1, peso_balon_kg=10,
    )
    # Fuera de rango: no deben contar.
    _sembrar_evento(
        db_session, fecha=date(2026, 7, 19), motivo="SATURADO",
        cantidad_balones=5, peso_balon_kg=10,
    )
    _sembrar_evento(
        db_session, fecha=date(2026, 7, 27), motivo="SIN_STOCK",
        cantidad_balones=4, peso_balon_kg=45,
    )

    response = client.get(
        "/demanda-perdida/resumen",
        params={"desde": desde.isoformat(), "hasta": hasta.isoformat()},
    )

    assert response.status_code == 200
    assert response.json() == {
        "desde": "2026-07-20",
        "hasta": "2026-07-26",
        "eventos_total": 3,
        "balones_total": 4,
        "balones_10kg": 3,
        "balones_45kg": 1,
        "por_motivo": [
            {"motivo": "SIN_STOCK", "eventos": 2, "balones": 3},
            {"motivo": "FUERA_DE_ZONA", "eventos": 1, "balones": 1},
        ],
    }


def test_resumen_sin_parametros_usa_ultimos_7_dias_lima(client, db_session):
    hoy = fecha_hoy_lima()
    _sembrar_evento(db_session, fecha=hoy, cantidad_balones=2)
    _sembrar_evento(db_session, fecha=hoy - timedelta(days=6), cantidad_balones=1)
    # Octavo dia hacia atras: queda fuera del default.
    _sembrar_evento(db_session, fecha=hoy - timedelta(days=7), cantidad_balones=9)

    response = client.get("/demanda-perdida/resumen")

    assert response.status_code == 200
    body = response.json()
    assert body["desde"] == (hoy - timedelta(days=6)).isoformat()
    assert body["hasta"] == hoy.isoformat()
    assert body["eventos_total"] == 2
    assert body["balones_total"] == 3


def test_resumen_vacio_devuelve_ceros(client):
    response = client.get("/demanda-perdida/resumen")

    assert response.status_code == 200
    body = response.json()
    assert body["eventos_total"] == 0
    assert body["balones_total"] == 0
    assert body["balones_10kg"] == 0
    assert body["balones_45kg"] == 0
    assert body["por_motivo"] == []


# ---------------------------------------------------------------------------
# Invariante clave: aislamiento de ventas y stock
# ---------------------------------------------------------------------------


def test_registrar_demanda_perdida_no_altera_reportes_ni_stock(client):
    """Registrar demanda perdida NO toca pedidos, stock ni reportes del dia."""
    hoy = fecha_hoy_lima().isoformat()

    # Dia operativo real: stock iniciado + una venta activa.
    assert (
        client.post(
            "/stock/iniciar-dia",
            json={"fecha": hoy, "stock_inicial": 20},
        ).status_code
        == 201
    )
    cliente = client.post(
        "/clientes/",
        json={"alias": "Las Higueras 371", "telefono": "999888777"},
    ).json()
    assert (
        client.post(
            "/pedidos",
            json={
                "cliente_id": cliente["id"],
                "fecha_entrega": hoy,
                "cantidad_balones": 2,
                "total_soles": 110,
                "pagado": True,
            },
        ).status_code
        == 201
    )

    reporte_antes = client.get("/reportes/resumen-hoy").json()
    stock_antes = client.get("/stock/resumen-hoy").json()

    respuesta = client.post(
        "/demanda-perdida",
        json={"motivo": "SIN_STOCK", "cantidad_balones": 5},
    )
    assert respuesta.status_code == 201

    reporte_despues = client.get("/reportes/resumen-hoy").json()
    stock_despues = client.get("/stock/resumen-hoy").json()

    assert reporte_despues == reporte_antes
    assert stock_despues == stock_antes
