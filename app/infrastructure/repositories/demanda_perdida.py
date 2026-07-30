"""Repositorio PostgreSQL de demanda perdida (P1 #2)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import DemandaPerdida


def crear(
    db: Session,
    *,
    fecha: date,
    motivo: str,
    zona_texto: str | None,
    cantidad_balones: int,
    peso_balon_kg: int,
) -> DemandaPerdida:
    registro = DemandaPerdida(
        fecha=fecha,
        motivo=motivo,
        zona_texto=zona_texto,
        cantidad_balones=cantidad_balones,
        peso_balon_kg=peso_balon_kg,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def listar(
    db: Session,
    *,
    desde: date | None = None,
    hasta: date | None = None,
    limit: int = 100,
) -> list[DemandaPerdida]:
    stmt = select(DemandaPerdida)
    if desde is not None:
        stmt = stmt.where(DemandaPerdida.fecha >= desde)
    if hasta is not None:
        stmt = stmt.where(DemandaPerdida.fecha <= hasta)
    stmt = stmt.order_by(
        DemandaPerdida.created_at.desc(), DemandaPerdida.id.desc()
    ).limit(limit)
    return list(db.execute(stmt).scalars().all())


def listar_rango(
    db: Session, *, desde: date, hasta: date
) -> list[DemandaPerdida]:
    """Todos los registros del rango [desde, hasta] por columna `fecha`.

    El resumen agrega por dia operativo Lima (columna date), sin matematica
    de timezone sobre `created_at` (decision D3 de la spec P1).
    """
    stmt = (
        select(DemandaPerdida)
        .where(DemandaPerdida.fecha >= desde, DemandaPerdida.fecha <= hasta)
        .order_by(DemandaPerdida.fecha.asc(), DemandaPerdida.id.asc())
    )
    return list(db.execute(stmt).scalars().all())
