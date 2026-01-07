from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Pedido, Direccion, Cliente


def _get_or_create_direccion_default(db: Session, cliente: Cliente) -> Direccion:
    stmt = (
        select(Direccion)
        .where(
            Direccion.cliente_id == cliente.id,
            Direccion.activa.is_(True),
        )
        .order_by(Direccion.id.asc())
        .limit(1)
    )

    direccion = db.execute(stmt).scalars().first()
    if direccion is not None:
        return direccion

    direccion = Direccion(
        cliente_id=cliente.id,
        texto_original=cliente.alias,  # dirección por defecto
        distrito=None,
        referencia=None,
        activa=True,
    )
    db.add(direccion)
    db.flush()  # obtiene direccion.id sin commit todavía
    return direccion

def buscar_pedidos_por_cliente(db: Session, cliente_id: int, limit: int = 50) -> list[Pedido]:
    stmt = (
        select(Pedido)
        .where(Pedido.cliente_id == cliente_id)
        .order_by(Pedido.fecha_pedido.desc(), Pedido.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())

def crear_pedido(
    db: Session,
    cliente: Cliente,
    fecha_pedido: date,
    cantidad_balones: int,
    total_soles: Decimal,
    pagado: bool = True,
    saldo_pendiente: Decimal = Decimal("0.00"),
    observacion: str | None = None,
) -> Pedido:
    try:
        direccion = _get_or_create_direccion_default(db, cliente)

        pedido = Pedido(
            cliente_id=cliente.id,
            direccion_id=direccion.id,
            fecha_pedido=fecha_pedido,
            cantidad_balones=cantidad_balones,
            total_soles=total_soles,
            pagado=pagado,
            saldo_pendiente=saldo_pendiente,
        )

        db.add(pedido)
        db.commit()
        db.refresh(pedido)
        return pedido
    except Exception:
        db.rollback()
        raise