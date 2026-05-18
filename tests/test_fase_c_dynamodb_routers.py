"""Tests Fase C: routers despachan a DynamoDB sin abrir PostgreSQL.

Cuando `APP_STORAGE_BACKEND=dynamodb`:
- `/health` responde 200 sin DB.
- `get_db()` cede `None` (no abre `SessionLocal`).
- Routers usan los repositorios DynamoDB. Aqui los stubeamos con fakes
  para no depender de boto3/DDB real.
- Si algun codepath PostgreSQL se ejecuta accidentalmente, `SessionLocal`
  fallaria por falta de `DATABASE_URL` (verificado con stub explicito).
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.infrastructure.dynamodb.repositories import clientes as ddb_clientes
from app.infrastructure.dynamodb.repositories import (
    movimientos_stock as ddb_movs,
)
from app.infrastructure.dynamodb.repositories import pedidos as ddb_pedidos
from app.infrastructure.dynamodb.repositories import (
    stock_jornadas as ddb_jornadas,
)
from app.infrastructure.dynamodb.repositories import reportes as ddb_reportes
from app.main import app


# ---------------------------------------------------------------------------
# Fakes DynamoDB
# ---------------------------------------------------------------------------


class _FakeClientesTable:
    """Tabla DDB clientes con soporte para alias_lock + TransactWriteItems."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        key = Item["cliente_id"]
        if ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        self.items[key] = Item

    def get_item(self, *, Key):
        item = self.items.get(Key["cliente_id"])
        return {"Item": item} if item is not None else {}

    def scan(self, *, FilterExpression=None, Limit=None, **_):
        values = [
            v for v in self.items.values() if v.get("item_type") != "ALIAS_UNICO"
        ]
        if FilterExpression is not None:
            values = [v for v in values if FilterExpression._evaluate(v)]
        if Limit is not None:
            values = values[:Limit]
        return {"Items": values}


class _FakePedidosTable:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        key = Item["pedido_id"]
        if ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        self.items[key] = Item

    def scan(self, *, FilterExpression=None, Limit=None, ExclusiveStartKey=None, **_):
        values = list(self.items.values())
        if FilterExpression is not None:
            values = [v for v in values if FilterExpression._evaluate(v)]
        if Limit is not None:
            values = values[:Limit]
        return {"Items": values}


class _FakeStockJornadasTable:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        key = Item["fecha"]
        if ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        self.items[key] = Item

    def get_item(self, *, Key):
        item = self.items.get(Key["fecha"])
        return {"Item": item} if item is not None else {}

    def update_item(
        self,
        *,
        Key,
        UpdateExpression,
        ExpressionAttributeValues,
        ConditionExpression=None,
        ReturnValues=None,
    ):
        item = self.items.get(Key["fecha"])
        if item is None:
            raise RuntimeError("ConditionalCheckFailed: jornada no existe")
        if ConditionExpression and item.get("cerrado", False):
            raise RuntimeError("ConditionalCheckFailed: cerrado")
        delta = ExpressionAttributeValues[":d"]
        item["stock_actual"] = int(item.get("stock_actual", 0)) + int(delta)
        item["updated_at"] = ExpressionAttributeValues[":now"]
        return {"Attributes": {"stock_actual": item["stock_actual"]}}


class _FakeMovimientosTable:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        self.items[Item["movimiento_id"]] = Item

    def scan(self, *, FilterExpression=None, Limit=None, **_):
        values = list(self.items.values())
        if FilterExpression is not None:
            values = [v for v in values if FilterExpression._evaluate(v)]
        if Limit is not None:
            values = values[:Limit]
        return {"Items": values}


def _fake_transact_put_items(puts: list[dict], *, tables_by_name: dict) -> None:
    """Simula `transact_write_items` aplicando los puts en orden y revirtiendo
    si alguno falla por ConditionExpression."""
    applied: list[tuple[object, str]] = []
    for put in puts:
        table = tables_by_name[put["table_name"]]
        item = put["item"]
        cond = put.get("condition_expression")
        try:
            table.put_item(Item=item, ConditionExpression=cond)
        except RuntimeError as exc:
            # Rollback de los previos
            for prev_table, prev_key in applied:
                prev_table.items.pop(prev_key, None)
            # Simular forma TransactionCanceledException con response.dict
            err = Exception("TransactionCanceledException")
            err.response = {  # type: ignore[attr-defined]
                "Error": {"Code": "TransactionCanceledException"},
                "CancellationReasons": [{"Code": "ConditionalCheckFailed"}],
            }
            raise err from exc
        # capturar key segun tabla
        if "cliente_id" in item:
            applied.append((table, item["cliente_id"]))
        elif "pedido_id" in item:
            applied.append((table, item["pedido_id"]))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dynamodb_mode(monkeypatch):
    """Activa modo DynamoDB y verifica que no se abra PostgreSQL."""
    monkeypatch.setenv("APP_STORAGE_BACKEND", "dynamodb")

    # Sentinel: si algo intenta abrir SessionLocal, falla la prueba.
    from app.db import session as db_session

    def _fail_session_local():  # pragma: no cover - solo se invoca si hay regresion
        raise AssertionError(
            "SessionLocal() fue llamada en modo DynamoDB. Hay un router "
            "que no respeta el switch."
        )

    monkeypatch.setattr(db_session, "SessionLocal", _fail_session_local)


@pytest.fixture()
def ddb_tables(monkeypatch):
    """Wirea fakes a todos los repositorios DynamoDB."""
    clientes_table = _FakeClientesTable()
    pedidos_table = _FakePedidosTable()
    jornadas_table = _FakeStockJornadasTable()
    movs_table = _FakeMovimientosTable()

    tables_ns = SimpleNamespace(
        clientes="clientes-table",
        pedidos="pedidos-table",
        stock_jornadas="stock-jornadas-table",
        movimientos_stock="movimientos-stock-table",
        contadores=None,
    )

    tables_by_name = {
        "clientes-table": clientes_table,
        "pedidos-table": pedidos_table,
        "stock-jornadas-table": jornadas_table,
        "movimientos-stock-table": movs_table,
    }

    def _get_table(name):
        return tables_by_name[name]

    monkeypatch.setattr(ddb_clientes, "get_dynamodb_tables", lambda: tables_ns)
    monkeypatch.setattr(ddb_clientes, "get_table", _get_table)
    monkeypatch.setattr(
        ddb_clientes,
        "transact_put_items",
        lambda puts: _fake_transact_put_items(puts, tables_by_name=tables_by_name),
    )

    monkeypatch.setattr(ddb_pedidos, "get_dynamodb_tables", lambda: tables_ns)
    monkeypatch.setattr(ddb_pedidos, "get_table", _get_table)

    monkeypatch.setattr(ddb_jornadas, "get_dynamodb_tables", lambda: tables_ns)
    monkeypatch.setattr(ddb_jornadas, "get_table", _get_table)

    monkeypatch.setattr(ddb_movs, "get_dynamodb_tables", lambda: tables_ns)
    monkeypatch.setattr(ddb_movs, "get_table", _get_table)

    # IDs deterministas
    counter = {"n": 0}

    def _next_id():
        counter["n"] += 1
        return f"uuid-{counter['n']}"

    monkeypatch.setattr(ddb_clientes, "generate_id", _next_id)
    monkeypatch.setattr(ddb_pedidos, "generate_id", _next_id)
    monkeypatch.setattr(ddb_movs, "generate_id", _next_id)

    return SimpleNamespace(
        clientes=clientes_table,
        pedidos=pedidos_table,
        jornadas=jornadas_table,
        movimientos=movs_table,
    )


@pytest.fixture()
def client(dynamodb_mode, ddb_tables):
    app.dependency_overrides.clear()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_responde_sin_db_en_modo_dynamodb(dynamodb_mode):
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_db_yield_none_en_modo_dynamodb(dynamodb_mode):
    gen = deps.get_db()
    value = next(gen)
    assert value is None
    # cerrar el generador para asegurar no abre nada extra
    try:
        next(gen)
    except StopIteration:
        pass


def test_crear_cliente_no_abre_postgres(client, ddb_tables):
    response = client.post(
        "/clientes/",
        json={"alias": "Las Higueras 371", "telefono": "999888777"},
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], str)
    assert body["alias"] == "Las Higueras 371"


def test_crear_cliente_alias_duplicado_devuelve_409(client, ddb_tables):
    first = client.post(
        "/clientes/", json={"alias": "Las Higueras 371", "telefono": "111111"}
    )
    assert first.status_code == 201

    second = client.post(
        "/clientes/", json={"alias": "Las Higueras 371", "telefono": "222222"}
    )
    assert second.status_code == 409


def test_obtener_cliente_404_si_no_existe(client, ddb_tables):
    response = client.get("/clientes/uuid-inexistente")
    assert response.status_code == 404


def test_buscar_clientes_no_abre_postgres(client, ddb_tables):
    client.post("/clientes/", json={"alias": "Las Higueras 371", "telefono": "111111"})
    response = client.get("/clientes/search", params={"q": "Higueras"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(isinstance(c["id"], str) for c in data)


def test_listar_clientes_recientes_no_abre_postgres(client, ddb_tables):
    response = client.get("/clientes/recientes", params={"limit": 5})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_crear_pedido_para_cliente_existente(client, ddb_tables):
    cli = client.post(
        "/clientes/", json={"alias": "Casa A", "telefono": "111111"}
    ).json()
    assert "id" in cli, cli
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cli["id"],
            "fecha_entrega": "2026-05-15",
            "cantidad_balones": 1,
            "monto_total_centavos": 5500,
            "pagado": True,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], str)
    assert isinstance(body["cliente_id"], str)
    assert body["cliente_id"] == cli["id"]
    assert body["monto_total_centavos"] == 5500
    assert body["monto_pendiente_centavos"] == 0


def test_crear_pedido_404_si_cliente_no_existe(client, ddb_tables):
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": "uuid-fantasma",
            "fecha_entrega": "2026-05-15",
            "cantidad_balones": 1,
            "monto_total_centavos": 5500,
            "pagado": True,
        },
    )
    assert response.status_code == 404


def test_listar_pedidos_por_cliente(client, ddb_tables):
    cli = client.post(
        "/clientes/", json={"alias": "Casa B", "telefono": "222222"}
    ).json()
    client.post(
        "/pedidos",
        json={
            "cliente_id": cli["id"],
            "fecha_entrega": "2026-05-15",
            "cantidad_balones": 1,
            "monto_total_centavos": 5500,
            "pagado": True,
        },
    )
    response = client.get("/pedidos", params={"cliente_id": cli["id"]})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["cliente_id"] == cli["id"]


def test_reporte_dia_no_abre_postgres(client, ddb_tables):
    cli = client.post(
        "/clientes/", json={"alias": "Casa C", "telefono": "333333"}
    ).json()
    client.post(
        "/pedidos",
        json={
            "cliente_id": cli["id"],
            "fecha_entrega": "2026-05-15",
            "cantidad_balones": 2,
            "monto_total_centavos": 11000,
            "monto_pendiente_centavos": 5000,
            "pagado": False,
        },
    )
    response = client.get("/reportes/dia", params={"fecha": "2026-05-15"})
    assert response.status_code == 200
    body = response.json()
    assert body["pedidos_count"] == 1
    assert body["monto_total_centavos"] == 11000
    assert body["monto_pendiente_centavos"] == 5000
    assert body["monto_pagado_centavos"] == 6000


def test_reporte_deudas_no_abre_postgres(client, ddb_tables):
    cli = client.post(
        "/clientes/", json={"alias": "Casa D", "telefono": "444444"}
    ).json()
    client.post(
        "/pedidos",
        json={
            "cliente_id": cli["id"],
            "fecha_entrega": "2026-05-15",
            "cantidad_balones": 1,
            "monto_total_centavos": 5500,
            "monto_pendiente_centavos": 5500,
            "pagado": False,
        },
    )
    response = client.get("/reportes/deudas")
    assert response.status_code == 200
    body = response.json()
    assert body["pedidos_count"] >= 1
    assert body["monto_pendiente_centavos"] >= 5500


def test_stock_resumen_sin_iniciar(client, ddb_tables):
    response = client.get("/stock/resumen-hoy")
    assert response.status_code == 200
    body = response.json()
    assert body["stock_iniciado"] is False


def test_stock_iniciar_dia_y_entrada_y_ajuste(client, ddb_tables):
    iniciar = client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-05-15", "stock_inicial": 10},
    )
    assert iniciar.status_code == 201
    assert iniciar.json()["stock_actual"] == 10

    # iniciar de nuevo -> 409
    again = client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-05-15", "stock_inicial": 10},
    )
    assert again.status_code == 409

    entrada = client.post(
        "/stock/entrada", json={"fecha": "2026-05-15", "cantidad": 5}
    )
    assert entrada.status_code == 200
    assert entrada.json()["stock_actual"] == 15

    ajuste = client.post(
        "/stock/ajuste", json={"fecha": "2026-05-15", "stock_fisico": 12}
    )
    assert ajuste.status_code == 200
    assert ajuste.json()["stock_actual"] == 12
    assert ajuste.json()["cantidad_delta"] == -3


def test_stock_entrada_404_si_no_iniciado(client, ddb_tables):
    response = client.post(
        "/stock/entrada", json={"fecha": "2026-05-20", "cantidad": 1}
    )
    assert response.status_code == 404


def test_stock_dia_lista_movimientos(client, ddb_tables):
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-05-15", "stock_inicial": 10},
    )
    client.post("/stock/entrada", json={"fecha": "2026-05-15", "cantidad": 3})

    response = client.get("/stock/dia", params={"fecha": "2026-05-15"})
    assert response.status_code == 200
    body = response.json()
    assert body["stock_actual"] == 13
    tipos = [m["tipo"] for m in body["movimientos"]]
    assert "INICIO_DIA" in tipos
    assert "ENTRADA" in tipos


def test_pedido_side_effect_resta_stock_si_jornada_existe(client, ddb_tables):
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-05-15", "stock_inicial": 10},
    )
    cli = client.post(
        "/clientes/", json={"alias": "Casa E", "telefono": "555555"}
    ).json()
    client.post(
        "/pedidos",
        json={
            "cliente_id": cli["id"],
            "fecha_entrega": "2026-05-15",
            "cantidad_balones": 3,
            "monto_total_centavos": 16500,
            "pagado": True,
        },
    )
    resumen = client.get(
        "/stock/dia", params={"fecha": "2026-05-15"}
    ).json()
    assert resumen["stock_actual"] == 7
    tipos = [m["tipo"] for m in resumen["movimientos"]]
    assert "SALIDA_PEDIDO" in tipos


def test_ddb_reportes_scan_all_usa_tabla_fake(monkeypatch, dynamodb_mode, ddb_tables):
    """`_scan_all_pedidos` debe poder leer items de la tabla fake sin paginacion."""
    # Reusar el fake de pedidos via ddb_tables.pedidos
    monkeypatch.setattr(
        ddb_reportes,
        "get_table",
        lambda name: ddb_tables.pedidos,
        raising=False,
    )
    monkeypatch.setattr(
        ddb_reportes,
        "get_dynamodb_tables",
        lambda: SimpleNamespace(pedidos="pedidos-table"),
        raising=False,
    )
    # Sembrar un item via repo
    ddb_pedidos.crear_pedido(
        cliente_id="cli-1",
        cliente_alias="Casa F",
        fecha_entrega="2026-05-15",
        cantidad_balones=1,
        total_centavos=5500,
        pagado_centavos=5500,
    )
    items = ddb_reportes._scan_all_pedidos()
    assert any(p.cliente_id == "cli-1" for p in items)
