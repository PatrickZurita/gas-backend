from types import SimpleNamespace

import pytest

from app.infrastructure.dynamodb.repositories import pedidos, reportes


class FakePedidosTable:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        self.items[Item["pedido_id"]] = Item

    def scan(self, *, FilterExpression=None, Limit=None, **_):
        values = list(self.items.values())
        if FilterExpression is not None:
            values = [item for item in values if FilterExpression._evaluate(item)]
        if Limit is not None:
            values = values[:Limit]
        return {"Items": values}


class _AttrStub:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return _FakeCondition(self.name, value)


class _FakeCondition:
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def _evaluate(self, item):
        return item.get(self.name) == self.value


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
    monkeypatch.setattr(pedidos, "get_table", lambda _: table)
    return table


def test_resumen_diario_agrega_montos(monkeypatch, fake_pedidos):
    ids = iter(["a", "b", "c"])
    monkeypatch.setattr(pedidos, "generate_id", lambda: next(ids))

    pedidos.crear_pedido(
        cliente_id="cli-1", cliente_alias="X", fecha_entrega="2026-05-12",
        cantidad_balones=2, total_centavos=5000, pagado_centavos=5000,
    )
    pedidos.crear_pedido(
        cliente_id="cli-2", cliente_alias="Y", fecha_entrega="2026-05-12",
        cantidad_balones=1, total_centavos=2500, pagado_centavos=1000,
    )
    pedidos.crear_pedido(
        cliente_id="cli-3", cliente_alias="Z", fecha_entrega="2026-05-11",
        cantidad_balones=1, total_centavos=2500, pagado_centavos=0,
    )

    resumen = reportes.resumen_diario("2026-05-12")

    assert resumen.fecha == "2026-05-12"
    assert resumen.pedidos == 2
    assert resumen.balones_vendidos == 3
    assert resumen.total_centavos == 7500
    assert resumen.cobrado_centavos == 6000
    assert resumen.deuda_centavos == 1500


def test_resumen_diario_sin_pedidos(fake_pedidos):
    resumen = reportes.resumen_diario("2026-05-12")
    assert resumen.pedidos == 0
    assert resumen.total_centavos == 0
    assert resumen.deuda_centavos == 0


def test_deudas_por_cliente_por_fecha(monkeypatch, fake_pedidos):
    ids = iter(["a", "b", "c"])
    monkeypatch.setattr(pedidos, "generate_id", lambda: next(ids))
    pedidos.crear_pedido(
        cliente_id="cli-1", cliente_alias="X", fecha_entrega="2026-05-12",
        cantidad_balones=1, total_centavos=2000, pagado_centavos=1000,
    )
    pedidos.crear_pedido(
        cliente_id="cli-1", cliente_alias="X", fecha_entrega="2026-05-12",
        cantidad_balones=1, total_centavos=3000, pagado_centavos=0,
    )
    pedidos.crear_pedido(
        cliente_id="cli-2", cliente_alias="Y", fecha_entrega="2026-05-12",
        cantidad_balones=1, total_centavos=1000, pagado_centavos=1000,
    )

    deudas = reportes.deudas_por_cliente("2026-05-12")
    assert deudas == {"cli-1": 4000}
