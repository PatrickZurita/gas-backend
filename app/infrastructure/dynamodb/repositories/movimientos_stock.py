"""Repositorio DynamoDB de movimientos de stock (preparacion futura).

No esta cableado a routers. PostgreSQL sigue siendo el backend activo.

Reglas:
- `movimiento_id` es UUID4 string.
- Stock global; sin desglose por marca/tipo.
- Tipos permitidos: INICIO_DIA, ENTRADA, SALIDA_PEDIDO, AJUSTE.
- `pedido_id` opcional (solo aplica a SALIDA_PEDIDO).
- Coordinacion con `stock_jornadas` la hace el caso de uso, no el repositorio.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.dynamodb.client import get_table
from app.infrastructure.dynamodb.config import get_dynamodb_tables
from app.infrastructure.dynamodb.id_generation import generate_id

TIPOS_VALIDOS = frozenset({"INICIO_DIA", "ENTRADA", "SALIDA_PEDIDO", "AJUSTE"})


@dataclass(frozen=True)
class DynamoMovimientoStock:
    id: str
    fecha: str
    tipo: str
    cantidad_delta: int
    stock_resultante: int
    pedido_id: str | None


def registrar_movimiento(
    *,
    fecha: str,
    tipo: str,
    cantidad_delta: int,
    stock_resultante: int,
    pedido_id: str | None = None,
    observacion: str | None = None,
) -> DynamoMovimientoStock:
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"Tipo invalido: {tipo}")
    if stock_resultante < 0:
        raise ValueError("stock_resultante no puede ser negativo.")

    mov_id = generate_id()
    now = datetime.now(UTC).isoformat()
    item: dict[str, Any] = {
        "movimiento_id": mov_id,
        "fecha": fecha,
        "tipo": tipo,
        "cantidad_delta": cantidad_delta,
        "stock_resultante": stock_resultante,
        "created_at": now,
    }
    if pedido_id is not None:
        item["pedido_id"] = pedido_id
    if observacion is not None:
        item["observacion"] = observacion

    table = get_table(get_dynamodb_tables().movimientos_stock)
    table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(movimiento_id)",
    )
    return _from_item(item)


def listar_movimientos_por_fecha(fecha: str, limit: int = 200) -> list[DynamoMovimientoStock]:
    try:
        from boto3.dynamodb.conditions import Attr
    except ImportError as exc:
        raise RuntimeError("boto3 is required for DynamoDB storage.") from exc

    table = get_table(get_dynamodb_tables().movimientos_stock)
    response = table.scan(
        FilterExpression=Attr("fecha").eq(fecha),
        Limit=limit,
    )
    return [_from_item(item) for item in response.get("Items", [])]


def _from_item(item: dict[str, Any]) -> DynamoMovimientoStock:
    pedido_id = item.get("pedido_id")
    return DynamoMovimientoStock(
        id=str(item.get("movimiento_id", "")),
        fecha=str(item.get("fecha", "")),
        tipo=str(item.get("tipo", "")),
        cantidad_delta=int(item.get("cantidad_delta", 0)),
        stock_resultante=int(item.get("stock_resultante", 0)),
        pedido_id=str(pedido_id) if pedido_id is not None else None,
    )
