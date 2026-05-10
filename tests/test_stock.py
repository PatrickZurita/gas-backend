from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db.base import Base
from app.main import app
from app.models.models import Cliente, Direccion


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


def _crear_cliente(db, alias: str = "Las Higueras 371") -> Cliente:
    cliente = Cliente(alias=alias, telefono="999888777", nombre=None)
    db.add(cliente)
    db.flush()
    db.add(
        Direccion(
            cliente_id=cliente.id,
            texto_original=alias,
            distrito=None,
            referencia=None,
            activa=True,
        )
    )
    db.commit()
    db.refresh(cliente)
    return cliente


def _pedido_payload(cliente_id: int, cantidad_balones: int = 1) -> dict[str, object]:
    return {
        "cliente_id": cliente_id,
        "fecha_entrega": "2026-01-16",
        "cantidad_balones": cantidad_balones,
        "total_soles": 55 * cantidad_balones,
        "pagado": True,
    }


def test_stock_resumen_hoy_sin_jornada_devuelve_no_iniciado(client):
    response = client.get("/stock/dia", params={"fecha": "2026-01-16"})

    assert response.status_code == 200
    assert response.json() == {
        "fecha": "2026-01-16",
        "stock_iniciado": False,
        "stock_inicial": None,
        "entradas": 0,
        "salidas": 0,
        "ajustes": 0,
        "stock_actual": None,
        "stock_final_fisico": None,
        "cerrado": False,
        "movimientos": [],
    }


def test_iniciar_dia_crea_jornada_y_movimiento(client):
    response = client.post(
        "/stock/iniciar-dia",
        json={
            "fecha": "2026-01-16",
            "stock_inicial": 30,
            "observacion": "Inicio de reparto",
        },
    )

    assert response.status_code == 201
    assert response.json()["stock_actual"] == 30

    detalle = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    assert detalle["stock_iniciado"] is True
    assert detalle["stock_inicial"] == 30
    assert detalle["movimientos"][0]["tipo"] == "INICIO_DIA"
    assert detalle["movimientos"][0]["cantidad_delta"] == 30


def test_iniciar_dia_rechaza_fecha_duplicada(client):
    payload = {"fecha": "2026-01-16", "stock_inicial": 30}

    assert client.post("/stock/iniciar-dia", json=payload).status_code == 201
    response = client.post("/stock/iniciar-dia", json=payload)

    assert response.status_code == 409


def test_entrada_aumenta_stock(client):
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": 30},
    )

    response = client.post(
        "/stock/entrada",
        json={
            "fecha": "2026-01-16",
            "cantidad": 10,
            "observacion": "Proveedor dejo balones",
        },
    )

    assert response.status_code == 200
    assert response.json()["cantidad_delta"] == 10
    assert response.json()["stock_actual"] == 40

    resumen = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    assert resumen["entradas"] == 10
    assert resumen["stock_actual"] == 40


def test_ajuste_corrige_stock_fisico(client):
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": 30},
    )

    response = client.post(
        "/stock/ajuste",
        json={
            "fecha": "2026-01-16",
            "stock_fisico": 28,
            "observacion": "Conteo fisico",
        },
    )

    assert response.status_code == 200
    assert response.json()["cantidad_delta"] == -2
    assert response.json()["stock_actual"] == 28

    resumen = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    assert resumen["ajustes"] == -2
    assert resumen["stock_actual"] == 28
    assert resumen["stock_final_fisico"] == 28


def test_pedido_sin_stock_iniciado_no_bloquea_registro(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post("/pedidos", json=_pedido_payload(cliente.id))

    assert response.status_code == 201
    assert response.json()["cliente_id"] == cliente.id

    resumen = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    assert resumen["stock_iniciado"] is False
    assert resumen["movimientos"] == []


def test_pedido_descuenta_stock_y_permite_stock_negativo(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": 1},
    )

    response = client.post("/pedidos", json=_pedido_payload(cliente.id, 2))

    assert response.status_code == 201

    resumen = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    assert resumen["salidas"] == 2
    assert resumen["stock_actual"] == -1
    assert resumen["movimientos"][-1]["tipo"] == "SALIDA_PEDIDO"
    assert resumen["movimientos"][-1]["cantidad_delta"] == -2


def test_reporte_dia_incluye_stock(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": 30},
    )
    client.post("/pedidos", json=_pedido_payload(cliente.id, 2))

    response = client.get("/reportes/dia", params={"fecha": "2026-01-16"})

    assert response.status_code == 200
    stock = response.json()["stock"]
    assert stock["stock_iniciado"] is True
    assert stock["stock_inicial"] == 30
    assert stock["salidas"] == 2
    assert stock["stock_actual"] == 28
