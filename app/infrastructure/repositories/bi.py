"""Lecturas BI v1; los identificadores no salen en resultados agregados."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Pedido


class PedidoBI(NamedTuple):
    cliente_id: int
    fecha_entrega: date
    peso_balon_kg: int
    cantidad_balones: int
    monto_total_centavos: int | None
    total_soles: Decimal | None
    monto_pendiente_centavos: int | None
    saldo_pendiente: Decimal | None


def listar_activos_en_rango(
    db: Session, *, desde: date, hasta: date, peso_balon_kg: int | None
) -> list[PedidoBI]:
    stmt = select(
        Pedido.cliente_id,
        Pedido.fecha_entrega,
        Pedido.peso_balon_kg,
        Pedido.cantidad_balones,
        Pedido.monto_total_centavos,
        Pedido.total_soles,
        Pedido.monto_pendiente_centavos,
        Pedido.saldo_pendiente,
    ).where(
        Pedido.estado == "ACTIVO",
        Pedido.fecha_entrega >= desde,
        Pedido.fecha_entrega <= hasta,
    )
    if peso_balon_kg is not None:
        stmt = stmt.where(Pedido.peso_balon_kg == peso_balon_kg)
    stmt = stmt.order_by(Pedido.fecha_entrega, Pedido.id)
    return [PedidoBI(*row) for row in db.execute(stmt).all()]


def listar_dias_activos_de_compradores(
    db: Session, *, hasta: date, cliente_ids: set[int], peso_balon_kg: int | None
) -> list[tuple[int, date]]:
    """Historia hasta el corte de compradores del rango, sin alias ni domicilio."""
    if not cliente_ids:
        return []
    stmt = select(Pedido.cliente_id, Pedido.fecha_entrega).where(
        Pedido.estado == "ACTIVO",
        Pedido.fecha_entrega <= hasta,
        Pedido.cliente_id.in_(cliente_ids),
    )
    if peso_balon_kg is not None:
        stmt = stmt.where(Pedido.peso_balon_kg == peso_balon_kg)
    stmt = stmt.distinct().order_by(Pedido.cliente_id, Pedido.fecha_entrega)
    return [(cliente_id, fecha) for cliente_id, fecha in db.execute(stmt).all()]
