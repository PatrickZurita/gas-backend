from types import SimpleNamespace

import pytest

from app.infrastructure.dynamodb.repositories import pedidos


class FakePedidosTable:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        key = Item["pedido_id"]
        if ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        self.items[key] = Item

    def scan(self, *, FilterExpression=None, Limit=None, **_):
        values = list(self.items.values())
        if FilterExpression is not None:
            values = [item for item in values if FilterExpression._evaluate(item)]
        if Limit is not None:
            values = values[:Limit]
        return {"Items": values}


class _FakeCondition:
    def __init__(self, attr_name: str, expected):
        self.attr_name = attr_name
        self.expected = expected

    def _evaluate(self, item: dict) -> bool:
        return item.get(self.attr_name) == self.expected


@pytest.fixture()
def dynamodb_tables():
    return SimpleNamespace(
        clientes="clientes-table",
        pedidos="pedidos-table",
        stock_jornadas="stock-jornadas-table",
        movimientos_stock="movimientos-stock-table",
        contadores=None,
    )


@pytest.fixture()
def fake_pedidos(monkeypatch, dynamodb_tables):
    table = FakePedidosTable()
    monkeypatch.setattr(pedidos, "get_dynamodb_tables", lambda: dynamodb_tables)
    monkeypatch.setattr(pedidos, "get_table", lambda name: table)
    return table


def test_crear_pedido_usa_uuid_string(monkeypatch, fake_pedidos):
    monkeypatch.setattr(pedidos, "generate_id", lambda: "uuid-pedido-1")

    pedido = pedidos.crear_pedido(
        cliente_id="uuid-cli-1",
        cliente_alias="Las Higueras 371",
        fecha_entrega="2026-05-12",
        cantidad_balones=2,
        total_centavos=5000,
        pagado_centavos=3000,
    )

    assert isinstance(pedido.id, str)
    assert pedido.id == "uuid-pedido-1"
    assert pedido.cliente_id == "uuid-cli-1"
    assert pedido.pendiente_centavos == 2000
    assert pedido.pagado is False
    assert "uuid-pedido-1" in fake_pedidos.items


def test_pedido_pagado_completo_marca_pagado_true(monkeypatch, fake_pedidos):
    monkeypatch.setattr(pedidos, "generate_id", lambda: "uuid-pedido-2")

    pedido = pedidos.crear_pedido(
        cliente_id="uuid-cli-1",
        cliente_alias="X",
        fecha_entrega="2026-05-12",
        cantidad_balones=1,
        total_centavos=2500,
        pagado_centavos=2500,
    )

    assert pedido.pagado is True
    assert pedido.pendiente_centavos == 0


def test_listar_pedidos_por_cliente_filtra(monkeypatch, fake_pedidos):
    monkeypatch.setattr(pedidos, "generate_id", iter(["a", "b", "c"]).__next__)
    pedidos.crear_pedido(
        cliente_id="cli-1",
        cliente_alias="X",
        fecha_entrega="2026-05-10",
        cantidad_balones=1,
        total_centavos=1000,
        pagado_centavos=1000,
    )
    pedidos.crear_pedido(
        cliente_id="cli-2",
        cliente_alias="Y",
        fecha_entrega="2026-05-10",
        cantidad_balones=1,
        total_centavos=1000,
        pagado_centavos=0,
    )
    pedidos.crear_pedido(
        cliente_id="cli-1",
        cliente_alias="X",
        fecha_entrega="2026-05-11",
        cantidad_balones=2,
        total_centavos=2000,
        pagado_centavos=2000,
    )

    results = pedidos.listar_pedidos_por_cliente("cli-1")

    assert {p.id for p in results} == {"a", "c"}


def test_listar_pedidos_por_fecha_filtra(monkeypatch, fake_pedidos):
    monkeypatch.setattr(pedidos, "generate_id", iter(["a", "b", "c"]).__next__)
    pedidos.crear_pedido(
        cliente_id="cli-1",
        cliente_alias="X",
        fecha_entrega="2026-05-10",
        cantidad_balones=1,
        total_centavos=1000,
        pagado_centavos=0,
    )
    pedidos.crear_pedido(
        cliente_id="cli-2",
        cliente_alias="Y",
        fecha_entrega="2026-05-11",
        cantidad_balones=1,
        total_centavos=1000,
        pagado_centavos=1000,
    )
    pedidos.crear_pedido(
        cliente_id="cli-3",
        cliente_alias="Z",
        fecha_entrega="2026-05-10",
        cantidad_balones=1,
        total_centavos=1000,
        pagado_centavos=500,
    )

    results = pedidos.listar_pedidos_por_fecha("2026-05-10")
    assert {p.id for p in results} == {"a", "c"}


def test_crear_pedido_rechaza_montos_invalidos(monkeypatch, fake_pedidos):
    monkeypatch.setattr(pedidos, "generate_id", lambda: "x")
    with pytest.raises(ValueError):
        pedidos.crear_pedido(
            cliente_id="cli", cliente_alias="x", fecha_entrega="2026-05-10",
            cantidad_balones=0, total_centavos=100, pagado_centavos=0,
        )
    with pytest.raises(ValueError):
        pedidos.crear_pedido(
            cliente_id="cli", cliente_alias="x", fecha_entrega="2026-05-10",
            cantidad_balones=1, total_centavos=-1, pagado_centavos=0,
        )


class _AttrStub:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return _FakeCondition(self.name, value)
