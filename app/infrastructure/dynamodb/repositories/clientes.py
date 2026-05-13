from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
import re
import unicodedata

from app.infrastructure.dynamodb.client import get_table, transact_put_items
from app.infrastructure.dynamodb.config import get_dynamodb_tables
from app.infrastructure.dynamodb.id_generation import generate_id


class AliasDuplicadoError(Exception):
    pass


@dataclass(frozen=True)
class DynamoCliente:
    id: str
    alias: str
    telefono: str
    direccion: str


def obtener_cliente_por_id(cliente_id: str) -> DynamoCliente | None:
    table = get_table(get_dynamodb_tables().clientes)
    response = table.get_item(Key={"cliente_id": cliente_id})
    item = response.get("Item")
    if item is None:
        return None
    return _cliente_from_item(item)


def buscar_clientes(q: str, limit: int = 10) -> list[DynamoCliente]:
    try:
        from boto3.dynamodb.conditions import Attr
    except ImportError as exc:
        raise RuntimeError("boto3 is required for DynamoDB storage.") from exc

    table = get_table(get_dynamodb_tables().clientes)
    q_clean = normalizar_alias(q)
    response = table.scan(
        FilterExpression=Attr("alias_normalizado").contains(q_clean)
        | Attr("telefono").contains(q_clean),
        Limit=limit,
    )
    return [_cliente_from_item(item) for item in response.get("Items", [])]


def crear_cliente(alias: str, telefono: str, cliente_id: str) -> DynamoCliente:
    table_name = get_dynamodb_tables().clientes
    now = datetime.now(UTC).isoformat()
    alias_normalizado = normalizar_alias(alias)
    item = {
        "cliente_id": cliente_id,
        "item_type": "CLIENTE",
        "alias": alias.strip(),
        "alias_normalizado": alias_normalizado,
        "telefono": telefono,
        "direccion": alias.strip(),
        "created_at": now,
        "updated_at": now,
    }
    alias_lock = {
        "cliente_id": _alias_lock_id(alias_normalizado),
        "item_type": "ALIAS_UNICO",
        "alias_normalizado": alias_normalizado,
        "cliente_ref": cliente_id,
        "created_at": now,
    }

    try:
        transact_put_items(
            [
                {
                    "table_name": table_name,
                    "item": alias_lock,
                    "condition_expression": "attribute_not_exists(cliente_id)",
                },
                {
                    "table_name": table_name,
                    "item": item,
                    "condition_expression": "attribute_not_exists(cliente_id)",
                },
            ]
        )
    except Exception as exc:
        if _is_conditional_failure(exc):
            raise AliasDuplicadoError(
                "Ya existe un cliente con ese alias/direccion."
            ) from exc
        raise
    return _cliente_from_item(item)


def crear_cliente_con_id_generado(alias: str, telefono: str) -> DynamoCliente:
    cliente_id = generate_id()
    return crear_cliente(alias=alias, telefono=telefono, cliente_id=cliente_id)


def _cliente_from_item(item: dict[str, Any]) -> DynamoCliente:
    return DynamoCliente(
        id=str(item.get("cliente_id", "")),
        alias=str(item.get("alias", "")),
        telefono=str(item.get("telefono", "")),
        direccion=str(item.get("direccion") or item.get("alias", "")),
    )


def normalizar_alias(alias: str) -> str:
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", alias.strip().lower())
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def _alias_lock_id(alias_normalizado: str) -> str:
    return f"alias#{alias_normalizado}"


def _is_conditional_failure(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = response.get("Error", {}).get("Code")
    if code == "ConditionalCheckFailedException":
        return True
    if code != "TransactionCanceledException":
        return False
    reasons = response.get("CancellationReasons", [])
    return any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons)
