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


def test_catalogos_devuelven_tipos_y_marcas(client):
    tipos = client.get("/catalogos/tipos-balon")
    marcas = client.get("/catalogos/marcas-balon")

    assert tipos.status_code == 200
    assert tipos.json() == {
        "items": [
            {"codigo": "NORMAL", "nombre": "Normal"},
            {"codigo": "PREMIUM", "nombre": "Premium"},
        ]
    }
    assert marcas.status_code == 200
    assert marcas.json() == {
        "items": [
            {"codigo": "SOLGAS", "nombre": "Solgas"},
            {"codigo": "PETROPERU", "nombre": "Petroperu"},
        ]
    }


def test_pedido_legacy_usa_defaults_petroperu_normal(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["marca_balon"] == "PETROPERU"
    assert body["tipo_balon"] == "NORMAL"
    assert body["precio_unitario_centavos"] == 5500
    assert body["monto_total_centavos"] == 5500
    assert body["monto_pendiente_centavos"] == 0
    assert body["total_soles"] == "55.00"


def test_pedido_nuevo_registra_marca_tipo_y_precio_real(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "marca_balon": "SOLGAS",
            "tipo_balon": "PREMIUM",
            "precio_unitario_centavos": 6500,
            "pagado": False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["marca_balon"] == "SOLGAS"
    assert body["tipo_balon"] == "PREMIUM"
    assert body["precio_unitario_centavos"] == 6500
    assert body["monto_total_centavos"] == 6500
    assert body["monto_pendiente_centavos"] == 6500
    assert body["saldo_pendiente"] == "65.00"


def test_pedido_acepta_total_soles_con_centimos(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": "55.50",
            "pagado": False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["total_soles"] == "55.50"
    assert body["saldo_pendiente"] == "55.50"
    assert body["precio_unitario_centavos"] == 5550
    assert body["monto_total_centavos"] == 5550
    assert body["monto_pendiente_centavos"] == 5550


def test_pedido_rechaza_marca_o_tipo_invalidos(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "marca_balon": "OTRA",
            "tipo_balon": "NORMAL",
            "precio_unitario_centavos": 6500,
            "pagado": True,
        },
    )

    assert response.status_code == 422


def test_reporte_usa_centavos_exactos_y_expone_marca_tipo(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "marca_balon": "SOLGAS",
            "tipo_balon": "NORMAL",
            "monto_total_centavos": 110050,
            "monto_pendiente_centavos": 50,
            "pagado": False,
        },
    )

    response = client.get("/reportes/dia", params={"fecha": "2026-01-16"})

    assert response.status_code == 200
    body = response.json()
    pedido = body["pedidos"][0]
    assert body["monto_total_centavos"] == 110050
    assert body["monto_pendiente_centavos"] == 50
    assert body["monto_pagado_centavos"] == 110000
    assert pedido["marca_balon"] == "SOLGAS"
    assert pedido["tipo_balon"] == "NORMAL"
    assert pedido["monto_total_centavos"] == 110050
