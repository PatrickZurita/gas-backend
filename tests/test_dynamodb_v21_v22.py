"""Tests V2.1/V2.2 DynamoDB: paridad con PostgreSQL.

Garantiza que anular_pedido y patch_pedido en DDB:
- No lanzan NotImplementedError.
- Cambian estado a ANULADO (anular) o aplican fields (patch).
- Compensan stock con REVERSA_ANULACION cuando hay jornada abierta.
- Son idempotentes para la segunda llamada de anular.
"""

from types import SimpleNamespace

import pytest

from app.infrastructure.dynamodb.repositories import (
    movimientos_stock,
    pedidos as ddb_pedidos,
    stock_jornadas,
)


class FakePedidosTable:
    """Fake DDB pedidos con soporte minimo de update_item/get_item."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def put_item(self, *, Item, ConditionExpression=None):
        key = Item["pedido_id"]
        if ConditionExpression and "attribute_not_exists" in (ConditionExpression or "") and key in self.items:
            raise RuntimeError("ConditionalCheckFailed")
        self.items[key] = Item

    def get_item(self, *, Key):
        item = self.items.get(Key["pedido_id"])
        return {"Item": item} if item else {}

    def update_item(
        self,
        *,
        Key,
        UpdateExpression,
        ExpressionAttributeValues,
        ExpressionAttributeNames=None,
        ConditionExpression=None,
        ReturnValues=None,
    ):
        item = self.items.get(Key["pedido_id"])
        if item is None:
            raise RuntimeError("ConditionalCheckFailed: not found")

        # Soporte minimo: "SET a = :v0, b = :v1" o con alias #k0/#k1.
        # Quitamos el "SET ".
        assignments = UpdateExpression.replace("SET ", "", 1).split(", ")
        for assignment in assignments:
            attr, placeholder = [s.strip() for s in assignment.split("=")]
            if attr.startswith("#") and ExpressionAttributeNames:
                attr = ExpressionAttributeNames[attr]
            item[attr] = ExpressionAttributeValues[placeholder]

        return {"Attributes": dict(item)}

    def scan(self, *, FilterExpression=None, Limit=None, **_):
        values = list(self.items.values())
        if FilterExpression is not None:
            values = [v for v in values if FilterExpression._evaluate(v)]
        if Limit is not None:
            values = values[:Limit]
        return {"Items": values}


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
        self, *, Key, UpdateExpression, ExpressionAttributeValues,
        ConditionExpression=None, ReturnValues=None,
    ):
        item = self.items.get(Key["fecha"])
        if item is None:
            raise RuntimeError("ConditionalCheckFailed")
        if ConditionExpression and "cerrado = :closed" in ConditionExpression:
            if item["cerrado"] is not False:
                raise RuntimeError("ConditionalCheckFailed")
        delta = ExpressionAttributeValues.get(":d", 0)
        rollback = ExpressionAttributeValues.get(":rollback", 0)
        item["stock_actual"] = item["stock_actual"] + delta + rollback
        item["updated_at"] = ExpressionAttributeValues.get(":now", "")
        return {"Attributes": {"stock_actual": item["stock_actual"]}}


class FakeMovsTable:
    def __init__(self):
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


@pytest.fixture()
def tables():
    return SimpleNamespace(
        clientes="clientes",
        pedidos="pedidos",
        stock_jornadas="stock_jornadas",
        movimientos_stock="movimientos_stock",
        contadores=None,
    )


@pytest.fixture()
def ddb_enabled(monkeypatch, tables):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "dynamodb")
    fake_p = FakePedidosTable()
    fake_j = FakeJornadasTable()
    fake_m = FakeMovsTable()
    monkeypatch.setattr(ddb_pedidos, "get_dynamodb_tables", lambda: tables)
    monkeypatch.setattr(ddb_pedidos, "get_table", lambda _: fake_p)
    monkeypatch.setattr(stock_jornadas, "get_dynamodb_tables", lambda: tables)
    monkeypatch.setattr(stock_jornadas, "get_table", lambda _: fake_j)
    monkeypatch.setattr(movimientos_stock, "get_dynamodb_tables", lambda: tables)
    monkeypatch.setattr(movimientos_stock, "get_table", lambda _: fake_m)
    return SimpleNamespace(pedidos=fake_p, jornadas=fake_j, movs=fake_m)


def _crear_pedido_ddb(monkeypatch, *, pedido_id="ped-1", cantidad=2, peso=10):
    monkeypatch.setattr(ddb_pedidos, "generate_id", lambda: pedido_id)
    return ddb_pedidos.crear_pedido(
        cliente_id="cli-1",
        cliente_alias="Cliente X",
        fecha_entrega="2026-01-16",
        cantidad_balones=cantidad,
        total_centavos=5500 * cantidad,
        pagado_centavos=5500 * cantidad,
        peso_balon_kg=peso,
    )


def test_ddb_anular_pedido_no_lanza_not_implemented(monkeypatch, ddb_enabled):
    """V2.1 fix: anular DDB debe funcionar end-to-end."""
    from app.services import pedidos as service_pedidos

    _crear_pedido_ddb(monkeypatch, pedido_id="ped-1", cantidad=2)

    out = service_pedidos.anular_pedido(None, "ped-1", motivo="duplicado")
    assert out.estado == "ANULADO"
    assert out.anulado_motivo == "duplicado"
    assert ddb_enabled.pedidos.items["ped-1"]["estado"] == "ANULADO"


def test_ddb_anular_pedido_compensa_stock_si_jornada_abierta(monkeypatch, ddb_enabled):
    from app.services import pedidos as service_pedidos

    stock_jornadas.abrir_jornada("2026-01-16", 30)
    stock_jornadas.aplicar_delta("2026-01-16", -2)  # simular salida previa
    _crear_pedido_ddb(monkeypatch, pedido_id="ped-1", cantidad=2)

    service_pedidos.anular_pedido(None, "ped-1", motivo="dup")

    jornada = stock_jornadas.obtener_jornada("2026-01-16")
    assert jornada.stock_actual == 30  # reversa +2
    movs = movimientos_stock.listar_movimientos_por_fecha("2026-01-16")
    reversas = [m for m in movs if m.tipo == "REVERSA_ANULACION"]
    assert len(reversas) == 1
    assert reversas[0].cantidad_delta == 2


def test_ddb_anular_pedido_es_idempotente(monkeypatch, ddb_enabled):
    from app.services import pedidos as service_pedidos

    stock_jornadas.abrir_jornada("2026-01-16", 30)
    stock_jornadas.aplicar_delta("2026-01-16", -2)
    _crear_pedido_ddb(monkeypatch, pedido_id="ped-1", cantidad=2)

    service_pedidos.anular_pedido(None, "ped-1", motivo="dup")
    out = service_pedidos.anular_pedido(None, "ped-1", motivo="dup")

    assert out.estado == "ANULADO"
    movs = movimientos_stock.listar_movimientos_por_fecha("2026-01-16")
    reversas = [m for m in movs if m.tipo == "REVERSA_ANULACION"]
    assert len(reversas) == 1  # no se duplica


def test_ddb_anular_pedido_inexistente_lanza_404(monkeypatch, ddb_enabled):
    from app.services import pedidos as service_pedidos
    from app.services.pedidos import PedidoNoExisteError

    with pytest.raises(PedidoNoExisteError):
        service_pedidos.anular_pedido(None, "ped-fantasma")


def test_ddb_patch_pedido_cantidad_recalcula_stock(monkeypatch, ddb_enabled):
    from app.services import pedidos as service_pedidos

    stock_jornadas.abrir_jornada("2026-01-16", 30)
    stock_jornadas.aplicar_delta("2026-01-16", -2)
    _crear_pedido_ddb(monkeypatch, pedido_id="ped-1", cantidad=2)

    out = service_pedidos.patch_pedido(
        None, "ped-1", cantidad_balones=5, motivo_edicion="agrego 3"
    )
    assert out.cantidad_balones == 5

    jornada = stock_jornadas.obtener_jornada("2026-01-16")
    # 30 - 2 (salida orig) + 2 (reversa) - 5 (nueva salida) = 25
    assert jornada.stock_actual == 25


def test_ddb_patch_pedido_anulado_lanza_409(monkeypatch, ddb_enabled):
    from app.services import pedidos as service_pedidos
    from app.services.pedidos import PedidoAnuladoNoEditableError

    _crear_pedido_ddb(monkeypatch, pedido_id="ped-1", cantidad=2)
    service_pedidos.anular_pedido(None, "ped-1")

    with pytest.raises(PedidoAnuladoNoEditableError):
        service_pedidos.patch_pedido(None, "ped-1", cantidad_balones=5)


def test_ddb_pedido_legacy_sin_peso_lee_como_10kg(monkeypatch, ddb_enabled):
    """V2.2 retrocompat: item DDB legacy sin peso_balon_kg → 10."""
    ddb_enabled.pedidos.items["legacy-1"] = {
        "pedido_id": "legacy-1",
        "cliente_id": "cli-1",
        "cliente_alias": "X",
        "fecha_entrega": "2025-12-01",
        "cantidad_balones": 1,
        "total_centavos": 5500,
        "pagado_centavos": 5500,
        "pendiente_centavos": 0,
        "pagado": True,
        "tipo_balon": "NORMAL",
        "marca_balon": "PETROPERU",
        "estado": "ACTIVO",
        "created_at": "2025-12-01T00:00:00",
        # SIN peso_balon_kg ni estado faltante: ambos defensivos.
    }
    pedido = ddb_pedidos.obtener_pedido("legacy-1")
    assert pedido.peso_balon_kg == 10
    assert pedido.estado == "ACTIVO"
