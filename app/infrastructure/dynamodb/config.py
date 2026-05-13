import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DynamoDbTables:
    clientes: str
    pedidos: str
    stock_jornadas: str
    movimientos_stock: str
    # Legacy. La estrategia oficial de IDs es UUID4 string; la tabla
    # `contadores` ya no se aprovisiona en la IaC activa. Se mantiene
    # opcional para no romper el dataclass historico.
    contadores: str | None = None


def get_dynamodb_tables() -> DynamoDbTables:
    return DynamoDbTables(
        clientes=_required_env("GAS_CLIENTES_TABLE"),
        pedidos=_required_env("GAS_PEDIDOS_TABLE"),
        stock_jornadas=_required_env("GAS_STOCK_JORNADAS_TABLE"),
        movimientos_stock=_required_env("GAS_MOVIMIENTOS_STOCK_TABLE"),
        contadores=os.getenv("GAS_CONTADORES_TABLE") or None,
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required when APP_STORAGE_BACKEND=dynamodb.")
    return value
