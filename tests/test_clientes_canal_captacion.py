"""Tests P1 #1: `clientes.canal_captacion`.

Cubre el contrato de la spec P1 (§7 canal): alta con canal, alta sin canal
(retrocompatibilidad con la app desplegada), validacion 422, normalizacion
case-insensitive y presencia del campo en TODAS las salidas que serializan
cliente (regresion directa del anti-patron V2.8).
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db.base import Base
from app.main import app
from app.models.models import Cliente, Direccion, Pedido


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


def _payload(
    alias: str = "Las Higueras 371",
    telefono: str = "999888777",
    **extra: object,
) -> dict[str, object]:
    return {"alias": alias, "telefono": telefono, **extra}


def test_crear_cliente_con_canal_devuelve_el_campo(client):
    response = client.post(
        "/clientes/", json=_payload(canal_captacion="VOLANTE")
    )

    assert response.status_code == 201
    body = response.json()
    assert body["canal_captacion"] == "VOLANTE"
    assert body["alias"] == "Las Higueras 371"


def test_crear_cliente_sin_canal_sigue_funcionando(client):
    """Retrocompatibilidad: la app Flutter desplegada no envia el campo."""
    response = client.post("/clientes/", json=_payload())

    assert response.status_code == 201
    assert response.json()["canal_captacion"] is None


def test_crear_cliente_canal_invalido_devuelve_422(client):
    response = client.post(
        "/clientes/", json=_payload(canal_captacion="TIKTOK")
    )

    assert response.status_code == 422


def test_crear_cliente_canal_case_insensitive_guarda_mayusculas(client):
    response = client.post(
        "/clientes/", json=_payload(canal_captacion="volante")
    )

    assert response.status_code == 201
    assert response.json()["canal_captacion"] == "VOLANTE"


@pytest.mark.parametrize(
    "canal",
    ["VOLANTE", "FACEBOOK", "RECOMENDACION", "CARTEL", "ANTIGUO", "OTRO"],
)
def test_crear_cliente_acepta_todos_los_canales_validos(client, canal):
    response = client.post(
        "/clientes/",
        json=_payload(alias=f"Cliente {canal}", canal_captacion=canal),
    )

    assert response.status_code == 201
    assert response.json()["canal_captacion"] == canal


def test_canal_persiste_en_base(client, db_session):
    client.post("/clientes/", json=_payload(canal_captacion="FACEBOOK"))

    cliente = db_session.query(Cliente).one()
    assert cliente.canal_captacion == "FACEBOOK"


def test_canal_sale_en_catalogo_search_y_detalle(client):
    """Anti-patron V2.8: el campo debe salir en TODAS las salidas."""
    creado = client.post(
        "/clientes/", json=_payload(canal_captacion="CARTEL")
    ).json()

    catalogo = client.get("/clientes")
    assert catalogo.status_code == 200
    assert catalogo.json()[0]["canal_captacion"] == "CARTEL"

    search = client.get("/clientes/search", params={"q": "Higueras"})
    assert search.status_code == 200
    assert search.json()[0]["canal_captacion"] == "CARTEL"

    detalle = client.get(f"/clientes/{creado['id']}")
    assert detalle.status_code == 200
    assert detalle.json()["canal_captacion"] == "CARTEL"


def test_canal_sale_en_clientes_recientes(client, db_session):
    """Anti-patron V2.8: `ClienteRecienteOut` tambien lleva el campo."""
    cliente = Cliente(
        alias="Mandarinas 257",
        telefono="923777321",
        nombre=None,
        canal_captacion="RECOMENDACION",
    )
    db_session.add(cliente)
    db_session.flush()
    direccion = Direccion(
        cliente_id=cliente.id,
        texto_original=cliente.alias,
        distrito=None,
        referencia=None,
        activa=True,
    )
    db_session.add(direccion)
    db_session.flush()
    db_session.add(
        Pedido(
            cliente_id=cliente.id,
            direccion_id=direccion.id,
            created_at=datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc),
            fecha_entrega=date(2026, 7, 29),
            cantidad_balones=1,
            total_soles=Decimal("55.00"),
            pagado=True,
            saldo_pendiente=Decimal("0.00"),
            monto_total_centavos=5500,
            monto_pendiente_centavos=0,
        )
    )
    db_session.commit()

    response = client.get("/clientes/recientes")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["alias"] == "Mandarinas 257"
    assert body[0]["canal_captacion"] == "RECOMENDACION"


def test_cliente_legacy_sin_canal_sale_none(client, db_session):
    """Legacy queda NULL (D10): sin backfill, sin atribuir sin evidencia."""
    cliente = Cliente(alias="Cliente Legacy", telefono="911222333", nombre=None)
    db_session.add(cliente)
    db_session.commit()

    response = client.get(f"/clientes/{cliente.id}")

    assert response.status_code == 200
    assert response.json()["canal_captacion"] is None
