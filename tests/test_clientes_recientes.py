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


def _crear_cliente(db, alias: str, telefono: str = "999888777") -> Cliente:
    cliente = Cliente(alias=alias, telefono=telefono, nombre=None)
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


def _crear_pedido(
    db,
    cliente: Cliente,
    *,
    created_at: datetime,
    fecha_entrega: date = date(2026, 1, 16),
    monto_total_centavos: int | None = 5500,
    total_soles: Decimal = Decimal("55.00"),
) -> Pedido:
    pedido = Pedido(
        cliente_id=cliente.id,
        direccion_id=cliente.direcciones[0].id,
        created_at=created_at,
        fecha_entrega=fecha_entrega,
        cantidad_balones=1,
        total_soles=total_soles,
        pagado=True,
        saldo_pendiente=Decimal("0.00"),
        monto_total_centavos=monto_total_centavos,
        monto_pendiente_centavos=0,
    )
    db.add(pedido)
    db.commit()
    db.refresh(pedido)
    return pedido


def test_clientes_recientes_sin_pedidos_retorna_lista_vacia(client):
    response = client.get("/clientes/recientes")

    assert response.status_code == 200
    assert response.json() == []


def test_clientes_recientes_ordena_por_ultimo_pedido(client, db_session):
    antiguo = _crear_cliente(db_session, "Las Higueras 371", "999888777")
    reciente = _crear_cliente(db_session, "Mandarinas 257", "923777321")
    _crear_pedido(
        db_session,
        antiguo,
        created_at=datetime(2026, 1, 16, 10, 0, tzinfo=timezone.utc),
        monto_total_centavos=5500,
    )
    _crear_pedido(
        db_session,
        reciente,
        created_at=datetime(2026, 1, 16, 11, 0, tzinfo=timezone.utc),
        monto_total_centavos=6500,
    )

    response = client.get("/clientes/recientes")

    assert response.status_code == 200
    body = response.json()
    assert [item["alias"] for item in body] == ["Mandarinas 257", "Las Higueras 371"]
    assert body[0]["telefono"] == "923777321"
    assert body[0]["direccion"] == "Mandarinas 257"
    assert body[0]["ultimo_pedido_fecha"] == "2026-01-16"
    assert body[0]["ultimo_total_centavos"] == 6500


def test_clientes_recientes_respeta_limit(client, db_session):
    for index in range(3):
        cliente = _crear_cliente(db_session, f"Cliente {index}", f"99988877{index}")
        _crear_pedido(
            db_session,
            cliente,
            created_at=datetime(2026, 1, 16, 10 + index, 0, tzinfo=timezone.utc),
        )

    response = client.get("/clientes/recientes", params={"limit": 2})

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_clientes_recientes_no_rompe_search_existente(client, db_session):
    _crear_cliente(db_session, "Las Higueras 371")

    response = client.get("/clientes/search", params={"q": "Higueras"})

    assert response.status_code == 200
    assert response.json()[0]["alias"] == "Las Higueras 371"


def test_clientes_recientes_convierte_legacy_total_soles_a_centavos(client, db_session):
    cliente = _crear_cliente(db_session, "Legacy 100")
    _crear_pedido(
        db_session,
        cliente,
        created_at=datetime(2026, 1, 16, 10, 0, tzinfo=timezone.utc),
        monto_total_centavos=None,
        total_soles=Decimal("55.50"),
    )

    response = client.get("/clientes/recientes")

    assert response.status_code == 200
    assert response.json()[0]["ultimo_total_centavos"] == 5550
