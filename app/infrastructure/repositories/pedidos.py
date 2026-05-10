from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Pedido, Direccion, Cliente
from app.infrastructure.repositories import stock as repo_stock


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
        .order_by(Pedido.created_at.desc(), Pedido.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())

def crear_pedido(
    db: Session,
    cliente: Cliente,
    fecha_entrega: date,
    cantidad_balones: int,
    total_soles: Decimal,
    tipo_balon: str = "NORMAL",
    marca_balon: str = "PETROPERU",
    precio_unitario_centavos: int | None = None,
    monto_total_centavos: int | None = None,
    pagado: bool = True,
    saldo_pendiente: Decimal | None = None,
    monto_pendiente_centavos: int | None = None,
    observacion: str | None = None,
) -> Pedido:
    try:
        direccion = _get_or_create_direccion_default(db, cliente)

        pedido = Pedido(
            cliente_id=cliente.id,
            direccion_id=direccion.id,
            fecha_entrega=fecha_entrega,
            cantidad_balones=cantidad_balones,
            total_soles=total_soles,
            tipo_balon=tipo_balon,
            marca_balon=marca_balon,
            precio_unitario_centavos=precio_unitario_centavos,
            monto_total_centavos=monto_total_centavos,
            pagado=pagado,
            saldo_pendiente=(
                saldo_pendiente
                if saldo_pendiente is not None
                else (0 if pagado else total_soles)
            ),
            monto_pendiente_centavos=monto_pendiente_centavos,
        )

        db.add(pedido)
        db.flush()
        repo_stock.registrar_salida_pedido_si_jornada_existe(
            db,
            fecha=fecha_entrega,
            cantidad_balones=cantidad_balones,
            pedido_id=pedido.id,
            marca_balon=marca_balon,
            tipo_balon=tipo_balon,
        )
        db.commit()
        db.refresh(pedido)
        return pedido

    except Exception:
        db.rollback()
        raise
