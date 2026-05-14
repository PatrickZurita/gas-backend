"""Helpers para normalizar IDs entre Pydantic flexible y SQLAlchemy int."""

def to_pg_id(value: int | str) -> int:
    """Convierte un ID flexible a int para PostgreSQL.

    Acepta int directo o string numerico. Rechaza UUIDs porque
    PostgreSQL no los reconoce como FK valida en este esquema.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(
                f"ID '{value}' no es valido para PostgreSQL "
                "(esperaba int o string numerico)"
            ) from exc
    raise TypeError(f"ID debe ser int o str, no {type(value).__name__}")
