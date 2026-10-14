"""Isolated, fail-closed PostgreSQL read path for BI HTTP requests."""

from __future__ import annotations

import os
from collections.abc import Generator
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.storage import is_dynamodb_enabled

_ROLE = "gas_readonly"
_BARRERAS_SQL = """
SELECT current_user AS usuario, session_user AS usuario_sesion,
       current_setting('transaction_read_only') AS solo_lectura,
       current_setting('transaction_isolation') AS aislamiento,
       to_regclass('public.pedidos') IS NOT NULL AS pedidos_existe,
       has_table_privilege(current_user, 'public.pedidos', 'SELECT') AS puede_leer,
       has_table_privilege(current_user, 'public.clientes', 'SELECT') AS puede_leer_clientes,
       has_table_privilege(current_user, 'public.direcciones', 'SELECT') AS puede_leer_direcciones,
       has_table_privilege(current_user, 'public.pedidos', 'INSERT') AS puede_insertar,
       has_table_privilege(current_user, 'public.pedidos', 'UPDATE') AS puede_actualizar,
       has_table_privilege(current_user, 'public.pedidos', 'DELETE') AS puede_borrar,
       has_table_privilege(current_user, 'public.pedidos', 'TRUNCATE') AS puede_truncar,
       has_table_privilege(current_user, 'public.pedidos', 'REFERENCES') AS puede_referenciar,
       has_table_privilege(current_user, 'public.pedidos', 'TRIGGER') AS puede_crear_trigger,
       has_schema_privilege(current_user, 'public', 'CREATE') AS crea_en_esquema,
       has_database_privilege(current_user, current_database(), 'CREATE') AS crea_en_base,
       r.rolsuper AS superusuario, r.rolcreaterole AS crea_roles,
       r.rolcreatedb AS crea_bases, r.rolbypassrls AS omite_rls
FROM pg_roles AS r WHERE r.rolname = current_user
"""
_PROHIBIDOS = (
    "puede_insertar", "puede_actualizar", "puede_borrar", "puede_truncar",
    "puede_referenciar", "puede_crear_trigger", "crea_en_esquema",
    "crea_en_base", "superusuario", "crea_roles", "crea_bases", "omite_rls",
)


def _validar_dsn(dsn: str):
    """Do not include the DSN or its password in exceptions."""
    try:
        url = make_url(dsn.strip())
        if (
            url.drivername not in {"postgresql", "postgresql+psycopg"}
            or url.username != _ROLE or not url.password or not url.host
            or not url.database or not url.host.endswith(".neon.tech")
            or set(url.query) - {"sslmode", "channel_binding"}
            or url.query.get("sslmode", "require")
            not in {"require", "verify-ca", "verify-full"}
        ):
            raise ValueError
        return url.set(
            drivername="postgresql+psycopg",
            query={**url.query, "sslmode": url.query.get("sslmode", "require")},
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=503, detail="Fuente BI no configurada.") from None


@lru_cache(maxsize=1)
def _engine():
    dsn = os.getenv("BI_DATABASE_URL", "")
    if not dsn or is_dynamodb_enabled():
        raise HTTPException(status_code=503, detail="Fuente BI no configurada.")
    return create_engine(_validar_dsn(dsn), pool_pre_ping=True)


def _exigir_barreras(estado) -> None:
    if (
        estado["usuario"] != _ROLE or estado["usuario_sesion"] != _ROLE
        or estado["solo_lectura"] != "on"
        or estado["aislamiento"] != "repeatable read"
        or not estado["pedidos_existe"] or not estado["puede_leer"]
        or not estado["puede_leer_clientes"] or not estado["puede_leer_direcciones"]
        or any(estado[campo] for campo in _PROHIBIDOS)
    ):
        raise HTTPException(status_code=503, detail="Fuente BI sin barreras de lectura.")


def get_bi_db() -> Generator[Session, None, None]:
    """Yield one repeatable-read, read-only snapshot, always rolled back."""
    try:
        with _engine().connect() as conexion:
            transaccion = conexion.begin()
            try:
                conexion.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                estado = conexion.exec_driver_sql(_BARRERAS_SQL).mappings().one()
                _exigir_barreras(estado)
                with Session(bind=conexion, join_transaction_mode="rollback_only") as db:
                    yield db
            finally:
                transaccion.rollback()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Fuente BI no disponible.") from exc
