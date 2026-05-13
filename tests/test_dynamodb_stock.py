from types import SimpleNamespace

import pytest

from app.infrastructure.dynamodb.repositories import (
    movimientos_stock,
    stock_jornadas,
)


class FakeJornadasTable:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        key = Item["fecha"]
        if ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        self.items[key] = Item

    def get_item(self, *, Key):
        item = self.items.get(Key["fecha"])
        return {"Item": item} if item else {}

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
            raise RuntimeError("ConditionalCheckFailed: not found")
        if ConditionExpression and "cerrado = :closed" in ConditionExpression:
            if item["cerrado"] is not False:
                raise RuntimeError("ConditionalCheckFailed: closed")
        delta = ExpressionAttributeValues.get(":d", 0)
        rollback = ExpressionAttributeValues.get(":rollback", 0)
        item["stock_actual"] = item["stock_actual"] + delta + rollback
        item["updated_at"] = ExpressionAttributeValues.get(":now", "")
        return {"Attributes": {"stock_actual": item["stock_actual"]}}


class FakeMovimientosTable:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        key = Item["movimiento_id"]
        if ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        self.items[key] = Item

    def scan(self, *, FilterExpression=None, Limit=None, **_):
        items = list(self.items.values())
        if FilterExpression is not None:
            items = [it for it in items if FilterExpression._evaluate(it)]
        if Limit is not None:
            items = items[:Limit]
        return {"Items": items}


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
def fake_jornadas(monkeypatch, dynamodb_tables):
    table = FakeJornadasTable()
    monkeypatch.setattr(stock_jornadas, "get_dynamodb_tables", lambda: dynamodb_tables)
    monkeypatch.setattr(stock_jornadas, "get_table", lambda _: table)
    return table


@pytest.fixture()
def fake_movs(monkeypatch, dynamodb_tables):
    table = FakeMovimientosTable()
    monkeypatch.setattr(movimientos_stock, "get_dynamodb_tables", lambda: dynamodb_tables)
    monkeypatch.setattr(movimientos_stock, "get_table", lambda _: table)
    return table


def test_abrir_jornada_persiste_stock_inicial(fake_jornadas):
    jornada = stock_jornadas.abrir_jornada("2026-05-12", 30)
    assert jornada.fecha == "2026-05-12"
    assert jornada.stock_inicial == 30
    assert jornada.stock_actual == 30
    assert jornada.cerrado is False
    assert "2026-05-12" in fake_jornadas.items


def test_aplicar_delta_positivo_suma(fake_jornadas):
    stock_jornadas.abrir_jornada("2026-05-12", 30)
    resultante = stock_jornadas.aplicar_delta("2026-05-12", 5)
    assert resultante == 35


def test_aplicar_delta_negativo_resta(fake_jornadas):
    stock_jornadas.abrir_jornada("2026-05-12", 30)
    resultante = stock_jornadas.aplicar_delta("2026-05-12", -2)
    assert resultante == 28


def test_aplicar_delta_negativo_excesivo_revierte(fake_jornadas):
    stock_jornadas.abrir_jornada("2026-05-12", 1)
    with pytest.raises(ValueError):
        stock_jornadas.aplicar_delta("2026-05-12", -5)
    # tras rollback el stock vuelve a 1
    assert fake_jornadas.items["2026-05-12"]["stock_actual"] == 1


def test_registrar_movimiento_entrada_genera_uuid_string(monkeypatch, fake_movs):
    monkeypatch.setattr(movimientos_stock, "generate_id", lambda: "uuid-mov-1")

    mov = movimientos_stock.registrar_movimiento(
        fecha="2026-05-12",
        tipo="ENTRADA",
        cantidad_delta=10,
        stock_resultante=40,
    )

    assert isinstance(mov.id, str)
    assert mov.id == "uuid-mov-1"
    assert mov.tipo == "ENTRADA"
    assert mov.cantidad_delta == 10
    assert mov.pedido_id is None
    assert "uuid-mov-1" in fake_movs.items


def test_registrar_movimiento_salida_con_pedido(monkeypatch, fake_movs):
    monkeypatch.setattr(movimientos_stock, "generate_id", lambda: "uuid-mov-2")

    mov = movimientos_stock.registrar_movimiento(
        fecha="2026-05-12",
        tipo="SALIDA_PEDIDO",
        cantidad_delta=-2,
        stock_resultante=28,
        pedido_id="uuid-pedido-1",
    )

    assert mov.pedido_id == "uuid-pedido-1"
    assert fake_movs.items["uuid-mov-2"]["pedido_id"] == "uuid-pedido-1"


def test_registrar_movimiento_tipo_invalido(fake_movs):
    with pytest.raises(ValueError):
        movimientos_stock.registrar_movimiento(
            fecha="2026-05-12",
            tipo="OTRO",
            cantidad_delta=1,
            stock_resultante=1,
        )
