"""DynamoDB ID generation helper.

Estrategia oficial de IDs para la capa DynamoDB futura: UUID4 string.

La tabla `contadores` quedo descartada como estrategia principal.
Ver docs/decisions/ADR-dynamodb-id-strategy.md.
"""

from uuid import uuid4


def generate_id() -> str:
    """Genera un identificador opaco para DynamoDB.

    Devuelve la representacion string de un UUID4. Se usa para
    `cliente_id`, `pedido_id`, `movimiento_stock_id` y cualquier
    otra key DynamoDB futura del MVP.
    """
    return str(uuid4())
