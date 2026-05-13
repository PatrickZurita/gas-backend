from types import SimpleNamespace

import pytest

from app.infrastructure.dynamodb import id_generation
from app.infrastructure.dynamodb.repositories import clientes


class FakeConditionalFailure(Exception):
    response = {
        "Error": {"Code": "TransactionCanceledException"},
        "CancellationReasons": [{"Code": "ConditionalCheckFailed"}],
    }


class FakeDynamoStore:
    def __init__(self):
        self.items_by_table: dict[str, dict[str, dict]] = {}

    def transact_put_items(self, puts: list[dict]):
        for put in puts:
            table = self.items_by_table.setdefault(put["table_name"], {})
            key = put["item"]["cliente_id"]
            if key in table:
                raise FakeConditionalFailure()

        for put in puts:
            table = self.items_by_table.setdefault(put["table_name"], {})
            table[put["item"]["cliente_id"]] = put["item"]


@pytest.fixture()
def dynamodb_tables():
    return SimpleNamespace(
        clientes="clientes-table",
        pedidos="pedidos-table",
        stock_jornadas="stock-jornadas-table",
        movimientos_stock="movimientos-stock-table",
        contadores=None,
    )


def test_generate_id_devuelve_string_no_vacio():
    generated = id_generation.generate_id()

    assert isinstance(generated, str)
    assert generated != ""


def test_generate_id_es_unico_entre_invocaciones():
    a = id_generation.generate_id()
    b = id_generation.generate_id()

    assert a != b


def test_normalizacion_de_alias_direccion():
    assert clientes.normalizar_alias("  Las   HÍGUERAS  371 ") == "las higueras 371"
    assert clientes.normalizar_alias("AV.  La Molina") == "av. la molina"


def test_crear_cliente_usa_id_string_generado_por_uuid(monkeypatch, dynamodb_tables):
    store = FakeDynamoStore()
    monkeypatch.setattr(clientes, "get_dynamodb_tables", lambda: dynamodb_tables)
    monkeypatch.setattr(clientes, "generate_id", lambda: "uuid-cliente-1")
    monkeypatch.setattr(clientes, "transact_put_items", store.transact_put_items)

    cliente = clientes.crear_cliente_con_id_generado(
        alias="Las Higueras 371",
        telefono="999888777",
    )

    assert isinstance(cliente.id, str)
    assert cliente.id == "uuid-cliente-1"
    assert cliente.alias == "Las Higueras 371"
    assert "uuid-cliente-1" in store.items_by_table["clientes-table"]
    assert "alias#las higueras 371" in store.items_by_table["clientes-table"]


def test_crear_cliente_con_alias_duplicado_falla(monkeypatch, dynamodb_tables):
    store = FakeDynamoStore()
    next_ids = iter(["uuid-cliente-1", "uuid-cliente-2"])
    monkeypatch.setattr(clientes, "get_dynamodb_tables", lambda: dynamodb_tables)
    monkeypatch.setattr(clientes, "generate_id", lambda: next(next_ids))
    monkeypatch.setattr(clientes, "transact_put_items", store.transact_put_items)

    clientes.crear_cliente_con_id_generado(
        alias="Las Higueras 371",
        telefono="999888777",
    )

    with pytest.raises(clientes.AliasDuplicadoError):
        clientes.crear_cliente_con_id_generado(
            alias=" las   higueras 371 ",
            telefono="999111222",
        )


def test_repositorio_clientes_no_depende_de_contadores():
    import inspect

    fuente = inspect.getsource(clientes)

    assert "from app.infrastructure.dynamodb.repositories.contadores" not in fuente
    assert "siguiente_id" not in fuente
