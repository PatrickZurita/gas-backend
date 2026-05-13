"""Repositorio DynamoDB de pedidos (preparacion futura).

No esta cableado a routers. PostgreSQL sigue siendo el backend activo.

Reglas:
- `pedido_id` es UUID4 string generado por `generate_id()`.
- `cliente_id` es UUID4 string (referencia logica al cliente).
- Dinero siempre en centavos (`int`).
- `fecha_entrega` en formato `YYYY-MM-DD` (string ISO date) para permitir
  Query/Scan por fecha sin parsing en backend.
- Multiples pedidos por `cliente_id`; listar por cliente se hace con
  `Scan` filtrado por bajo volumen MVP (1 usuario, 30-40 pedidos/dia).

El tradeoff de `Scan` por `cliente_id` y por `fecha_entrega` es aceptable
en MVP. Si crece el volumen, agregar GSIs sin cambiar el contrato del
repositorio.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.dynamodb.client import get_table
from app.infrastructure.dynamodb.config import get_dynamodb_tables
from app.infrastructure.dynamodb.id_generation import generate_id


@dataclass(frozen=True)
class DynamoPedido:
    id: str
    cliente_id: str
    cliente_alias: str
    fecha_entrega: str
    cantidad_balones: int
    total_centavos: int
    pagado_centavos: int
    pendiente_centavos: int
    pagado: bool


def crear_pedido(
    *,
    cliente_id: str,
    cliente_alias: str,
    fecha_entrega: str,
    cantidad_balones: int,
    total_centavos: int,
    pagado_centavos: int,
) -> DynamoPedido:
    if cantidad_balones <= 0:
        raise ValueError("cantidad_balones debe ser positivo.")
    if total_centavos < 0 or pagado_centavos < 0:
        raise ValueError("Montos no pueden ser negativos.")

    pendiente_centavos = max(0, total_centavos - pagado_centavos)
    pagado = pendiente_centavos == 0

    pedido_id = generate_id()
    now = datetime.now(UTC).isoformat()
    item = {
        "pedido_id": pedido_id,
        "cliente_id": cliente_id,
        "cliente_alias": cliente_alias,
        "fecha_entrega": fecha_entrega,
        "cantidad_balones": cantidad_balones,
        "total_centavos": total_centavos,
        "pagado_centavos": pagado_centavos,
        "pendiente_centavos": pendiente_centavos,
        "pagado": pagado,
        "created_at": now,
        "updated_at": now,
    }

    table = get_table(get_dynamodb_tables().pedidos)
    table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(pedido_id)",
    )
    return _pedido_from_item(item)


def listar_pedidos_por_cliente(cliente_id: str, limit: int = 50) -> list[DynamoPedido]:
    try:
        from boto3.dynamodb.conditions import Attr
    except ImportError as exc:
        raise RuntimeError("boto3 is required for DynamoDB storage.") from exc

    table = get_table(get_dynamodb_tables().pedidos)
    response = table.scan(
        FilterExpression=Attr("cliente_id").eq(cliente_id),
        Limit=limit,
    )
    return [_pedido_from_item(item) for item in response.get("Items", [])]


def listar_pedidos_por_fecha(fecha_entrega: str, limit: int = 200) -> list[DynamoPedido]:
    try:
        from boto3.dynamodb.conditions import Attr
    except ImportError as exc:
        raise RuntimeError("boto3 is required for DynamoDB storage.") from exc

    table = get_table(get_dynamodb_tables().pedidos)
    response = table.scan(
        FilterExpression=Attr("fecha_entrega").eq(fecha_entrega),
        Limit=limit,
    )
    return [_pedido_from_item(item) for item in response.get("Items", [])]


def _pedido_from_item(item: dict[str, Any]) -> DynamoPedido:
    return DynamoPedido(
        id=str(item.get("pedido_id", "")),
        cliente_id=str(item.get("cliente_id", "")),
        cliente_alias=str(item.get("cliente_alias", "")),
        fecha_entrega=str(item.get("fecha_entrega", "")),
        cantidad_balones=_to_int(item.get("cantidad_balones", 0)),
        total_centavos=_to_int(item.get("total_centavos", 0)),
        pagado_centavos=_to_int(item.get("pagado_centavos", 0)),
        pendiente_centavos=_to_int(item.get("pendiente_centavos", 0)),
        pagado=bool(item.get("pagado", False)),
    )


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
