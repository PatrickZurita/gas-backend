"""Capa de servicios storage-agnostica.

Cada modulo expone operaciones de negocio y elige PostgreSQL o DynamoDB
segun `app.core.storage.is_dynamodb_enabled()`. Los routers solo conocen
servicios; nunca importan repositorios directamente.

Errores de dominio:
- `AliasDuplicadoError` -> 409 en routers.
- `ClienteNoExisteError` -> 404 en routers.
- `StockNoIniciadoError` / `StockYaIniciadoError` / `StockCerradoError` -> 4xx.
"""

from app.services.errors import (
    AliasDuplicadoError,
    ClienteNoExisteError,
    StockCerradoError,
    StockNoIniciadoError,
    StockYaIniciadoError,
)

__all__ = [
    "AliasDuplicadoError",
    "ClienteNoExisteError",
    "StockCerradoError",
    "StockNoIniciadoError",
    "StockYaIniciadoError",
]
