"""Service `demanda_perdida` con dispatch PostgreSQL/DynamoDB.

P1 #2: registra la llamada que NO se pudo atender. No toca pedidos,
stock_jornadas ni movimientos_stock: cero efectos sobre ventas del dia.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import TYPE_CHECKING

from app.core.storage import is_dynamodb_enabled
from app.schemas.demanda_perdida import (
    MOTIVO_FUERA_DE_ZONA,
    MOTIVO_OTRO,
    MOTIVO_SATURADO,
    MOTIVO_SIN_STOCK,
    DemandaPerdidaMotivoResumen,
    DemandaPerdidaOut,
    DemandaPerdidaResumenOut,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Orden canonico para el resumen por motivo (deterministico).
_ORDEN_MOTIVOS = (
    MOTIVO_SIN_STOCK,
    MOTIVO_FUERA_DE_ZONA,
    MOTIVO_SATURADO,
    MOTIVO_OTRO,
)


def _require_db(db: "Session | None") -> "Session":
    if db is None:
        raise RuntimeError(
            "Servicio PostgreSQL requiere sesion; "
            "storage actual no esta inyectando una."
        )
    return db


def _raise_ddb_not_implemented() -> None:
    # Decision D11 (spec P1): AWS en standby, la rama DynamoDB es deuda
    # explicita y visible. Paridad enumerada en la spec P1 §6.
    raise NotImplementedError(
        "demanda_perdida no esta implementado en el backend DynamoDB "
        "(AWS en standby, spec P1 §6 / D11)."
    )


def registrar(
    db: "Session | None",
    *,
    fecha: date_cls,
    motivo: str,
    zona_texto: str | None,
    cantidad_balones: int,
    peso_balon_kg: int,
) -> DemandaPerdidaOut:
    if is_dynamodb_enabled():
        _raise_ddb_not_implemented()

    from app.infrastructure.repositories import demanda_perdida as pg

    session = _require_db(db)
    registro = pg.crear(
        session,
        fecha=fecha,
        motivo=motivo,
        zona_texto=zona_texto,
        cantidad_balones=cantidad_balones,
        peso_balon_kg=peso_balon_kg,
    )
    return DemandaPerdidaOut.model_validate(registro, from_attributes=True)


def listar(
    db: "Session | None",
    *,
    desde: date_cls | None = None,
    hasta: date_cls | None = None,
    limit: int = 100,
) -> list[DemandaPerdidaOut]:
    if is_dynamodb_enabled():
        _raise_ddb_not_implemented()

    from app.infrastructure.repositories import demanda_perdida as pg

    session = _require_db(db)
    rows = pg.listar(session, desde=desde, hasta=hasta, limit=limit)
    return [
        DemandaPerdidaOut.model_validate(r, from_attributes=True) for r in rows
    ]


def resumen(
    db: "Session | None", *, desde: date_cls, hasta: date_cls
) -> DemandaPerdidaResumenOut:
    """EL numero del caso 2do courier: balones perdidos por rango y motivo.

    Agrega por la columna `fecha` (dia operativo Lima), sin matematica de
    timezone sobre `created_at` (decision D3 de la spec P1).
    """
    if is_dynamodb_enabled():
        _raise_ddb_not_implemented()

    from app.infrastructure.repositories import demanda_perdida as pg

    session = _require_db(db)
    rows = pg.listar_rango(session, desde=desde, hasta=hasta)

    eventos_total = 0
    balones_total = 0
    balones_10kg = 0
    balones_45kg = 0
    por_motivo: dict[str, dict[str, int]] = {}
    for r in rows:
        eventos_total += 1
        balones_total += r.cantidad_balones
        if r.peso_balon_kg == 45:
            balones_45kg += r.cantidad_balones
        else:
            balones_10kg += r.cantidad_balones
        bucket = por_motivo.setdefault(r.motivo, {"eventos": 0, "balones": 0})
        bucket["eventos"] += 1
        bucket["balones"] += r.cantidad_balones

    return DemandaPerdidaResumenOut(
        desde=desde,
        hasta=hasta,
        eventos_total=eventos_total,
        balones_total=balones_total,
        balones_10kg=balones_10kg,
        balones_45kg=balones_45kg,
        por_motivo=[
            DemandaPerdidaMotivoResumen(
                motivo=motivo,
                eventos=por_motivo[motivo]["eventos"],
                balones=por_motivo[motivo]["balones"],
            )
            for motivo in _ORDEN_MOTIVOS
            if motivo in por_motivo
        ],
    )
