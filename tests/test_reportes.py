from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

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


def _crear_pedido(
    db,
    cliente: Cliente,
    *,
    fecha_entrega: date,
    total_soles: int,
    saldo_pendiente: int,
    cantidad_balones: int = 1,
    created_at: datetime | None = None,
) -> Pedido:
    direccion_id = cliente.direcciones[0].id
    pedido = Pedido(
        cliente_id=cliente.id,
        direccion_id=direccion_id,
        created_at=created_at or datetime.now(timezone.utc),
        fecha_entrega=fecha_entrega,
        cantidad_balones=cantidad_balones,
        total_soles=total_soles,
        pagado=saldo_pendiente == 0,
        saldo_pendiente=saldo_pendiente,
    )
    db.add(pedido)
    db.commit()
    db.refresh(pedido)
    return pedido


def test_reporte_dia_sin_pedidos_devuelve_totales_en_cero(client):
    response = client.get("/reportes/dia", params={"fecha": "2026-01-16"})

    assert response.status_code == 200
    assert response.json() == {
        "fecha": "2026-01-16",
        "pedidos_count": 0,
        "balones_vendidos": 0,
        "monto_total_centavos": 0,
        "monto_pagado_centavos": 0,
        "monto_pendiente_centavos": 0,
        "stock": {
            "fecha": "2026-01-16",
            "stock_iniciado": False,
            "stock_inicial": None,
            "entradas": 0,
            "salidas": 0,
            "ajustes": 0,
            "stock_actual": None,
            "stock_final_fisico": None,
            "cerrado": False,
        },
        "pedidos": [],
    }


def test_reporte_dia_con_pedidos_pagados_suma_totales_en_centavos(
    client,
    db_session,
):
    cliente = _crear_cliente(db_session)
    fecha = date(2026, 1, 16)
    _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=fecha,
        cantidad_balones=2,
        total_soles=110,
        saldo_pendiente=0,
    )
    _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=fecha,
        cantidad_balones=1,
        total_soles=55,
        saldo_pendiente=0,
    )

    response = client.get("/reportes/dia", params={"fecha": "2026-01-16"})

    assert response.status_code == 200
    body = response.json()
    assert body["pedidos_count"] == 2
    assert body["balones_vendidos"] == 3
    assert body["monto_total_centavos"] == 16500
    assert body["monto_pagado_centavos"] == 16500
    assert body["monto_pendiente_centavos"] == 0
    assert body["pedidos"][0]["cliente_alias"] == "Las Higueras 371"


def test_reporte_dia_con_pedidos_pendientes_calcula_pagado_y_deuda(
    client,
    db_session,
):
    cliente = _crear_cliente(db_session)
    fecha = date(2026, 1, 16)
    _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=fecha,
        cantidad_balones=2,
        total_soles=110,
        saldo_pendiente=110,
    )
    _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=fecha,
        cantidad_balones=1,
        total_soles=55,
        saldo_pendiente=0,
    )

    response = client.get("/reportes/dia", params={"fecha": "2026-01-16"})

    assert response.status_code == 200
    body = response.json()
    assert body["monto_total_centavos"] == 16500
    assert body["monto_pagado_centavos"] == 5500
    assert body["monto_pendiente_centavos"] == 11000


def test_reporte_dia_usa_fecha_entrega_no_created_at(client, db_session):
    cliente = _crear_cliente(db_session)
    fecha_reporte = date(2026, 1, 16)
    otra_fecha = date(2026, 1, 17)
    created_at_reporte = datetime(2026, 1, 16, 10, 0, tzinfo=timezone.utc)
    created_at_otra = datetime(2026, 1, 17, 10, 0, tzinfo=timezone.utc)

    pedido_incluido = _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=fecha_reporte,
        total_soles=55,
        saldo_pendiente=0,
        created_at=created_at_otra,
    )
    _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=otra_fecha,
        total_soles=110,
        saldo_pendiente=0,
        created_at=created_at_reporte,
    )

    response = client.get("/reportes/dia", params={"fecha": "2026-01-16"})

    assert response.status_code == 200
    body = response.json()
    assert body["pedidos_count"] == 1
    assert body["monto_total_centavos"] == 5500
    assert body["pedidos"][0]["id"] == pedido_incluido.id


def test_reporte_dia_rechaza_fecha_invalida(client):
    response = client.get("/reportes/dia", params={"fecha": "16-01-2026"})

    assert response.status_code == 422


def test_resumen_hoy_reutiliza_fecha_local_de_lima(client, db_session):
    cliente = _crear_cliente(db_session)
    fecha_hoy_lima = datetime.now(ZoneInfo("America/Lima")).date()
    _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=fecha_hoy_lima,
        total_soles=55,
        saldo_pendiente=0,
    )

    response = client.get("/reportes/resumen-hoy")

    assert response.status_code == 200
    body = response.json()
    assert body["fecha"] == fecha_hoy_lima.isoformat()
    assert body["pedidos_count"] == 1
    assert body["monto_total_centavos"] == 5500


def test_reporte_deudas_lista_solo_pedidos_pendientes_ordenados_por_fecha(
    client,
    db_session,
):
    cliente = _crear_cliente(db_session)
    pedido_antiguo = _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=date(2026, 1, 15),
        total_soles=55,
        saldo_pendiente=55,
        created_at=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
    )
    pedido_reciente = _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=date(2026, 1, 16),
        total_soles=110,
        saldo_pendiente=110,
        created_at=datetime(2026, 1, 16, 10, 0, tzinfo=timezone.utc),
    )
    _crear_pedido(
        db_session,
        cliente,
        fecha_entrega=date(2026, 1, 17),
        total_soles=55,
        saldo_pendiente=0,
    )

    response = client.get("/reportes/deudas")

    assert response.status_code == 200
    body = response.json()
    assert body["pedidos_count"] == 2
    assert body["monto_pendiente_centavos"] == 16500
    assert [pedido["id"] for pedido in body["pedidos"]] == [
        pedido_reciente.id,
        pedido_antiguo.id,
    ]
    assert all(pedido["monto_pendiente_centavos"] > 0 for pedido in body["pedidos"])
