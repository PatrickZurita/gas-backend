"""Reportes simples sobre tabla de pedidos DynamoDB (preparacion futura).

No esta cableado a routers. PostgreSQL sigue siendo el backend activo.

Los reportes se calculan en backend sobre el resultado de un Scan
filtrado por `fecha_entrega`. Volumen MVP: 1 usuario y 30-40 pedidos
por dia, por lo que el costo del Scan es despreciable.

Si el volumen crece se debe agregar GSI por `fecha_entrega`.
"""

from dataclasses import dataclass

from app.infrastructure.dynamodb.repositories import pedidos as pedidos_repo


@dataclass(frozen=True)
class ResumenDiario:
    fecha: str
    pedidos: int
    balones_vendidos: int
    total_centavos: int
    cobrado_centavos: int
    deuda_centavos: int


def resumen_diario(fecha: str) -> ResumenDiario:
    items = pedidos_repo.listar_pedidos_por_fecha(fecha)
    total = sum(p.total_centavos for p in items)
    cobrado = sum(p.pagado_centavos for p in items)
    pendiente = sum(p.pendiente_centavos for p in items)
    balones = sum(p.cantidad_balones for p in items)
    return ResumenDiario(
        fecha=fecha,
        pedidos=len(items),
        balones_vendidos=balones,
        total_centavos=total,
        cobrado_centavos=cobrado,
        deuda_centavos=pendiente,
    )


def deudas_por_cliente(fecha: str | None = None) -> dict[str, int]:
    """Suma de `pendiente_centavos` agrupado por `cliente_id`.

    Si `fecha` se especifica, solo considera pedidos de esa fecha. Sin
    fecha hace Scan completo de la tabla (uso esporadico).
    """
    if fecha is None:
        # Scan completo: aceptable en MVP, documentar tradeoff si se usa.
        items = _scan_all_pedidos()
    else:
        items = pedidos_repo.listar_pedidos_por_fecha(fecha)

    deudas: dict[str, int] = {}
    for p in items:
        if p.pendiente_centavos <= 0:
            continue
        deudas[p.cliente_id] = deudas.get(p.cliente_id, 0) + p.pendiente_centavos
    return deudas


def _scan_all_pedidos() -> list:
    # Imports relativos al modulo `pedidos_repo` para que los tests que hacen
    # monkeypatch de `pedidos_repo.get_table` y `pedidos_repo.get_dynamodb_tables`
    # afecten tambien a esta funcion sin necesidad de monkeypatch adicional.
    table = pedidos_repo.get_table(pedidos_repo.get_dynamodb_tables().pedidos)
    items: list = []
    response = table.scan()
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    return [pedidos_repo._pedido_from_item(it) for it in items]
