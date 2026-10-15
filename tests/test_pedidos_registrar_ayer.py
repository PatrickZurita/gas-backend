"""BI-11: registro de ayer y stock en transacciones sintéticas SQLite."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db.base import Base
from app.infrastructure.repositories import stock as repo_stock
from app.main import app
from app.models.models import Cliente, MovimientoStock, Pedido, StockJornada
from app.services import pedidos as service_pedidos

HOY = date(2026, 10, 15)
AYER = date(2026, 10, 14)


@pytest.fixture
def contexto(monkeypatch):
    monkeypatch.setattr(service_pedidos, "fecha_hoy_lima", lambda: HOY)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sesiones = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        with sesiones() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with sesiones() as db:
        cliente = Cliente(alias="Cliente sintético BI-11", telefono="000-TEST")
        db.add(cliente)
        db.commit()
        cliente_id = cliente.id
    try:
        yield TestClient(app), sesiones, cliente_id
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _pedido(cliente_id: int, *, cantidad: int = 2) -> dict:
    return {
        "cliente_id": cliente_id, "registrar_ayer": True,
        "cantidad_balones": cantidad, "precio_unitario_centavos": 7000,
        "peso_balon_kg": 10, "pagado": True,
    }


def _iniciar(client: TestClient, fecha: date, stock: int = 25) -> None:
    respuesta = client.post(
        "/stock/iniciar-dia",
        json={"fecha": fecha.isoformat(), "stock_inicial": stock},
    )
    assert respuesta.status_code == 201


def _stock(client: TestClient, fecha: date) -> dict:
    respuesta = client.get("/stock/dia", params={"fecha": fecha.isoformat()})
    assert respuesta.status_code == 200
    return respuesta.json()


def _conteos(sesiones) -> tuple[int, int]:
    with sesiones() as db:
        return (
            db.scalar(select(func.count()).select_from(Pedido)),
            db.scalar(select(func.count()).select_from(MovimientoStock)),
        )


def test_ayer_entrega_ayer_y_descuenta_jornada_hoy_abierta(contexto):
    client, sesiones, cliente_id = contexto
    _iniciar(client, HOY)
    respuesta = client.post("/pedidos", json=_pedido(cliente_id))
    assert respuesta.status_code == 201
    pedido = respuesta.json()
    assert pedido["fecha_entrega"] == AYER.isoformat()
    assert _stock(client, HOY)["stock_actual"] == 23
    assert _stock(client, HOY)["salidas"] == 2
    assert _stock(client, AYER)["stock_iniciado"] is False
    hoy_movimientos = _stock(client, HOY)["movimientos"]
    assert hoy_movimientos[-1]["pedido_id"] == pedido["id"]
    assert hoy_movimientos[-1]["tipo"] == "SALIDA_PEDIDO"
    reporte_ayer = client.get("/reportes/dia", params={"fecha": AYER.isoformat()})
    assert reporte_ayer.status_code == 200
    assert reporte_ayer.json()["pedidos_count"] == 1
    assert reporte_ayer.json()["balones_vendidos"] == 2
    assert _conteos(sesiones)[0] == 1


def test_ayer_descuenta_jornada_ayer_si_hoy_no_existe(contexto):
    client, sesiones, cliente_id = contexto
    _iniciar(client, AYER)
    respuesta = client.post("/pedidos", json=_pedido(cliente_id))
    assert respuesta.status_code == 201
    assert respuesta.json()["fecha_entrega"] == AYER.isoformat()
    assert _stock(client, AYER)["stock_actual"] == 23
    assert _stock(client, AYER)["salidas"] == 2
    assert _stock(client, HOY)["stock_iniciado"] is False
    assert _conteos(sesiones)[0] == 1


def test_ayer_sin_jornada_devuelve_409_sin_pedido_ni_movimiento(contexto):
    client, sesiones, cliente_id = contexto
    respuesta = client.post("/pedidos", json=_pedido(cliente_id))
    assert respuesta.status_code == 409
    assert _conteos(sesiones) == (0, 0)


def test_fallo_de_salida_tras_insertar_pedido_hace_rollback(contexto, monkeypatch):
    client, sesiones, cliente_id = contexto
    _iniciar(client, HOY)
    antes = _conteos(sesiones)
    monkeypatch.setattr(repo_stock, "registrar_salida_pedido_si_jornada_existe",
                        lambda *args, **kwargs: None)
    respuesta = client.post("/pedidos", json=_pedido(cliente_id))
    assert respuesta.status_code == 409
    assert _conteos(sesiones) == antes
    assert _stock(client, HOY)["stock_actual"] == 25


def test_ayer_jornada_hoy_cerrada_rechaza_y_no_usa_ayer(contexto):
    client, sesiones, cliente_id = contexto
    _iniciar(client, AYER)
    _iniciar(client, HOY)
    with sesiones() as db:
        db.scalar(select(StockJornada).where(StockJornada.fecha == HOY)).cerrado = True
        db.commit()
    respuesta = client.post("/pedidos", json=_pedido(cliente_id))
    assert respuesta.status_code == 409
    assert _conteos(sesiones)[0] == 0
    assert _stock(client, AYER)["stock_actual"] == 25


def test_ayer_retroactivo_no_anula_ni_edita_con_stock_asociado_cerrado(contexto):
    client, sesiones, cliente_id = contexto
    _iniciar(client, HOY)
    crear = client.post("/pedidos", json=_pedido(cliente_id))
    assert crear.status_code == 201
    pedido_id = crear.json()["id"]
    antes = _conteos(sesiones)
    with sesiones() as db:
        db.scalar(select(StockJornada).where(StockJornada.fecha == HOY)).cerrado = True
        db.commit()
    anular = client.post(f"/pedidos/{pedido_id}/anular", json={"motivo": "duplicado"})
    editar = client.patch(f"/pedidos/{pedido_id}", json={"cantidad_balones": 3})
    assert anular.status_code == 409
    assert editar.status_code == 409
    assert _conteos(sesiones) == antes
    assert _stock(client, HOY)["stock_actual"] == 23
    with sesiones() as db:
        pedido = db.get(Pedido, pedido_id)
        assert pedido.estado == "ACTIVO"
        assert pedido.cantidad_balones == 2
        assert pedido.anulado_at is None
