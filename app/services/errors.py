"""Errores de dominio independientes del storage.

Los routers los mapean a HTTP. Los servicios no lanzan errores
especificos de PostgreSQL ni de DynamoDB hacia afuera.
"""


class AliasDuplicadoError(Exception):
    """Alias/direccion ya existe (409)."""


class ClienteNoExisteError(Exception):
    """Cliente no encontrado (404)."""


class StockNoIniciadoError(Exception):
    """Stock del dia no fue iniciado (404)."""


class StockYaIniciadoError(Exception):
    """Stock del dia ya fue iniciado (409)."""


class StockCerradoError(Exception):
    """Stock del dia esta cerrado (409)."""
