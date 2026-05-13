"""Repositorio DynamoDB de stock global por jornada (preparacion futura).

No esta cableado a routers. PostgreSQL sigue siendo el backend activo.

Reglas:
- Stock global (no por marca/tipo).
- Key principal: `fecha` (string `YYYY-MM-DD`), unica por dia.
- Conteo entero; no se permiten resultados negativos.
- Un solo item por jornada/fecha; los cambios se acumulan via UpdateItem.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.dynamodb.client import get_table
from app.infrastructure.dynamodb.config import get_dynamodb_tables


@dataclass(frozen=True)
class DynamoStockJornada:
    fecha: str
    stock_inicial: int
    stock_actual: int
    cerrado: bool


def abrir_jornada(fecha: str, stock_inicial: int) -> DynamoStockJornada:
    if stock_inicial < 0:
        raise ValueError("stock_inicial no puede ser negativo.")
    now = datetime.now(UTC).isoformat()
    item = {
        "fecha": fecha,
        "stock_inicial": stock_inicial,
        "stock_actual": stock_inicial,
        "cerrado": False,
        "created_at": now,
        "updated_at": now,
    }

    table = get_table(get_dynamodb_tables().stock_jornadas)
    table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(fecha)",
    )
    return _from_item(item)


def obtener_jornada(fecha: str) -> DynamoStockJornada | None:
    table = get_table(get_dynamodb_tables().stock_jornadas)
    response = table.get_item(Key={"fecha": fecha})
    item = response.get("Item")
    return _from_item(item) if item else None


def aplicar_delta(fecha: str, delta: int) -> int:
    """Aplica un delta entero al `stock_actual` de la jornada y devuelve el resultado.

    Si `delta` es positivo se suma (entrada). Si es negativo se resta
    (salida por pedido o ajuste). Lanza si la jornada no existe o esta
    cerrada. La validacion de no-negatividad final se hace en backend
    porque DynamoDB no soporta comparar contra el resultado del ADD en
    `ConditionExpression`.
    """
    table = get_table(get_dynamodb_tables().stock_jornadas)
    now = datetime.now(UTC).isoformat()
    response = table.update_item(
        Key={"fecha": fecha},
        UpdateExpression="ADD stock_actual :d SET updated_at = :now",
        ExpressionAttributeValues={":d": delta, ":now": now, ":closed": False},
        ConditionExpression="attribute_exists(fecha) AND cerrado = :closed",
        ReturnValues="UPDATED_NEW",
    )
    resultante = int(response["Attributes"]["stock_actual"])
    if resultante < 0:
        # Compensar para no dejar la jornada inconsistente. En produccion real
        # esto deberia hacerse con TransactWriteItems condicional sobre el
        # valor previo; en MVP de 1 usuario el riesgo de concurrencia es nulo.
        table.update_item(
            Key={"fecha": fecha},
            UpdateExpression="ADD stock_actual :rollback SET updated_at = :now",
            ExpressionAttributeValues={":rollback": -delta, ":now": now},
        )
        raise ValueError("stock_actual quedaria negativo; operacion revertida.")
    return resultante


def _from_item(item: dict[str, Any]) -> DynamoStockJornada:
    return DynamoStockJornada(
        fecha=str(item.get("fecha", "")),
        stock_inicial=int(item.get("stock_inicial", 0)),
        stock_actual=int(item.get("stock_actual", 0)),
        cerrado=bool(item.get("cerrado", False)),
    )
