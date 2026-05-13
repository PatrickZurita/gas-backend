"""LEGACY / NOT RECOMMENDED.

Estrategia previa de IDs basada en una tabla DynamoDB `contadores` con
`UpdateItem ADD ultimo_valor :incremento`. Quedo descartada como
estrategia principal en favor de UUID4 string generados por aplicacion.

Ver:
- docs/decisions/ADR-dynamodb-id-strategy.md
- docs/backend/GAS-DYNAMODB-ID-AND-UNIQUE-ALIAS-DECISION.md

Este modulo se mantiene temporalmente para no romper imports historicos
y porque la tabla `gas-<env>-contadores` ya no se crea en la IaC activa.
No usar en codigo nuevo. La funcion `siguiente_id` permanece como
referencia y dependera de que la tabla exista en runtime (no es el caso
en la IaC vigente).
"""

from decimal import Decimal
from typing import Any

from app.infrastructure.dynamodb.client import get_table
from app.infrastructure.dynamodb.config import get_dynamodb_tables


def siguiente_id(entidad: str) -> int:
    """Deprecated. No usar en codigo nuevo.

    Conserva la firma historica. Si se invoca sin la tabla `contadores`
    aprovisionada, fallara en runtime con error de DynamoDB.
    """
    table = get_table(get_dynamodb_tables().contadores)
    response = table.update_item(
        Key={"contador_id": entidad},
        UpdateExpression="ADD ultimo_valor :incremento",
        ExpressionAttributeValues={":incremento": 1},
        ReturnValues="UPDATED_NEW",
    )
    return _to_int(response["Attributes"]["ultimo_valor"])


def _to_int(value: Any) -> int:
    if isinstance(value, Decimal):
        return int(value)
    return int(value)
