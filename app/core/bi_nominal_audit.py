"""Local-only, fail-closed audit for nominal BI requests.

The database contains only a pseudonymous actor reference and aggregate request
metadata. A `prepared` export records HTTP preparation, not browser storage.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

from fastapi import HTTPException, Request

_ACCIONES = {
    ("GET", "/bi/v1/clientes"): "listar_clientes",
    ("GET", "/bi/v1/clientes/pausas"): "listar_pausas_clientes",
    ("GET", "/bi/v1/clientes/historicos"): "listar_compradores_historicos",
    ("GET", "/bi/v1/geo/direcciones-pendientes"): "listar_direcciones_geo_pendientes",
    ("GET", "/bi/v1/pedidos"): "listar_pedidos",
    ("POST", "/bi/v1/clientes/export"): "preparar_clientes_xlsx",
    ("POST", "/bi/v1/pedidos/export"): "preparar_pedidos_xlsx",
}
_ERROR = "Acceso nominal local no disponible."


def _rechazar() -> HTTPException:
    return HTTPException(status_code=503, detail=_ERROR)


def _loopback(valor: str | None) -> bool:
    try:
        return ipaddress.ip_address(valor or "").is_loopback
    except ValueError:
        return False


def _exigir_local(request: Request) -> str:
    if (
        os.getenv("BI_NOMINAL_LOCAL_ENABLED") != "1"
        or os.getenv("APP_ENV") != "dev"
        or request.client is None or not _loopback(request.client.host)
        or not _loopback(request.url.hostname)
        or request.headers.get("forwarded")
        or request.headers.get("x-forwarded-for")
    ):
        raise _rechazar()
    accion = _ACCIONES.get((request.method, request.url.path))
    if accion is None:
        raise _rechazar()
    return accion


def _ruta_auditoria() -> Path:
    ruta_raw = os.getenv("BI_NOMINAL_AUDIT_DB_PATH", "")
    ruta = Path(ruta_raw)
    try:
        if not ruta_raw or not ruta.is_absolute() or ruta.suffix != ".sqlite3":
            raise ValueError
        parent = ruta.parent
        parent_stat = parent.lstat()
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or stat.S_IMODE(parent_stat.st_mode) != 0o700
            or parent_stat.st_uid != os.getuid()
        ):
            raise ValueError
        try:
            fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        archivo_stat = ruta.lstat()
        if (
            not stat.S_ISREG(archivo_stat.st_mode)
            or archivo_stat.st_nlink != 1
            or stat.S_IMODE(archivo_stat.st_mode) != 0o600
            or archivo_stat.st_uid != os.getuid()
        ):
            raise ValueError
    except (OSError, ValueError):
        raise _rechazar() from None
    return ruta


def _conexion() -> sqlite3.Connection:
    try:
        db = sqlite3.connect(_ruta_auditoria(), timeout=3)
        db.execute("""
            CREATE TABLE IF NOT EXISTS eventos_nominales (
                id INTEGER PRIMARY KEY,
                creado_en TEXT NOT NULL,
                accion TEXT NOT NULL,
                resultado TEXT NOT NULL,
                actor_ref TEXT,
                filtros TEXT,
                filas INTEGER,
                bytes_preparados INTEGER
            )
        """)
        db.commit()
        return db
    except (OSError, sqlite3.Error):
        raise _rechazar() from None


@dataclass
class AuditoriaNominal:
    evento_id: int
    terminada: bool = False

    def terminar(
        self, resultado: str, *, google_sub: str | None = None,
        filtros: dict[str, str | int] | None = None, filas: int | None = None,
        bytes_preparados: int | None = None,
    ) -> None:
        actor_ref = (
            hashlib.sha256(google_sub.encode("utf-8")).hexdigest()
            if google_sub else None
        )
        try:
            with closing(_conexion()) as db, db:
                cursor = db.execute(
                    """UPDATE eventos_nominales
                       SET resultado=?, actor_ref=?, filtros=?, filas=?, bytes_preparados=?
                       WHERE id=? AND resultado='attempt'""",
                    (resultado, actor_ref, json.dumps(filtros, sort_keys=True) if filtros else None,
                     filas, bytes_preparados, self.evento_id),
                )
                if cursor.rowcount != 1:
                    raise sqlite3.DatabaseError
        except (OSError, sqlite3.Error):
            raise _rechazar() from None
        self.terminada = True


def iniciar_auditoria_nominal(request: Request) -> Generator[AuditoriaNominal, None, None]:
    accion = _exigir_local(request)
    ahora = datetime.now(timezone.utc)
    try:
        with closing(_conexion()) as db, db:
            db.execute(
                "DELETE FROM eventos_nominales WHERE creado_en < ?",
                ((ahora - timedelta(days=90)).isoformat(),),
            )
            cursor = db.execute(
                "INSERT INTO eventos_nominales (creado_en, accion, resultado) VALUES (?, ?, 'attempt')",
                (ahora.isoformat(), accion),
            )
            evento_id = cursor.lastrowid
    except (OSError, sqlite3.Error):
        raise _rechazar() from None
    auditoria = AuditoriaNominal(evento_id=evento_id)
    try:
        yield auditoria
    except HTTPException as exc:
        if not auditoria.terminada:
            auditoria.terminar("denied" if exc.status_code in (401, 403) else "failed")
        raise
    except Exception:
        if not auditoria.terminada:
            auditoria.terminar("failed")
        raise
    if not auditoria.terminada:
        auditoria.terminar("failed")
        raise _rechazar()
