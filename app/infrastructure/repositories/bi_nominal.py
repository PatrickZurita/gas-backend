"""Consultas nominales internas. Ninguna de estas funciones publica una ruta HTTP."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Cliente, Direccion, Pedido


class PedidoNominalDB(NamedTuple):
    id: int
    cliente_id: int
    cliente_alias: str
    direccion_pedido: str
    fecha_entrega: date
    peso_balon_kg: int
    cantidad_balones: int
    monto_total_centavos: int | None
    total_soles: Decimal | None
    monto_pendiente_centavos: int | None
    saldo_pendiente: Decimal | None
    metodo_pago: str | None


class ClienteNominalDB(NamedTuple):
    id: int
    alias: str
    nombre: str | None
    telefono: str
    direccion_activa_observada: str | None
    canal_captacion: str | None


def _predicados_pedidos(desde: date, hasta: date, peso_balon_kg: int | None):
    condiciones = [
        Pedido.estado == "ACTIVO",
        Pedido.fecha_entrega >= desde,
        Pedido.fecha_entrega <= hasta,
    ]
    if peso_balon_kg is not None:
        condiciones.append(Pedido.peso_balon_kg == peso_balon_kg)
    return condiciones


def contar_pedidos(
    db: Session, *, desde: date, hasta: date, peso_balon_kg: int | None
) -> int:
    stmt = select(func.count()).select_from(Pedido).where(
        *_predicados_pedidos(desde, hasta, peso_balon_kg)
    )
    return int(db.scalar(stmt) or 0)


def listar_pedidos(
    db: Session, *, desde: date, hasta: date, peso_balon_kg: int | None,
    offset: int, limit: int,
) -> list[PedidoNominalDB]:
    stmt = (
        select(
            Pedido.id, Pedido.cliente_id, Cliente.alias, Direccion.texto_original,
            Pedido.fecha_entrega, Pedido.peso_balon_kg, Pedido.cantidad_balones,
            Pedido.monto_total_centavos, Pedido.total_soles,
            Pedido.monto_pendiente_centavos, Pedido.saldo_pendiente,
            Pedido.metodo_pago,
        )
        .join(Cliente, Cliente.id == Pedido.cliente_id)
        .join(Direccion, Direccion.id == Pedido.direccion_id)
        .where(*_predicados_pedidos(desde, hasta, peso_balon_kg))
        .order_by(Pedido.fecha_entrega, Pedido.id)
        .offset(offset)
        .limit(limit)
    )
    return [PedidoNominalDB(*fila) for fila in db.execute(stmt).all()]


def contar_clientes_registrados(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Cliente)) or 0)


def _direccion_activa():
    return (
        select(Direccion.texto_original)
        .where(Direccion.cliente_id == Cliente.id, Direccion.activa.is_(True))
        .order_by(Direccion.id)
        .limit(1)
        .correlate(Cliente)
        .scalar_subquery()
    )


def _seleccion_clientes():
    return select(
        Cliente.id, Cliente.alias, Cliente.nombre, Cliente.telefono,
        _direccion_activa(), Cliente.canal_captacion,
    )


def listar_clientes_registrados(
    db: Session, *, offset: int, limit: int
) -> list[ClienteNominalDB]:
    stmt = _seleccion_clientes().order_by(Cliente.id).offset(offset).limit(limit)
    return [ClienteNominalDB(*fila) for fila in db.execute(stmt).all()]


def contar_compradores(
    db: Session, *, desde: date, hasta: date, peso_balon_kg: int | None
) -> int:
    stmt = select(func.count(func.distinct(Pedido.cliente_id))).where(
        *_predicados_pedidos(desde, hasta, peso_balon_kg)
    )
    return int(db.scalar(stmt) or 0)


def listar_compradores(
    db: Session, *, desde: date, hasta: date, peso_balon_kg: int | None,
    offset: int, limit: int,
) -> list[ClienteNominalDB]:
    ids = select(Pedido.cliente_id).where(
        *_predicados_pedidos(desde, hasta, peso_balon_kg)
    )
    stmt = (
        _seleccion_clientes()
        .where(Cliente.id.in_(ids))
        .order_by(Cliente.id)
        .offset(offset)
        .limit(limit)
    )
    return [ClienteNominalDB(*fila) for fila in db.execute(stmt).all()]
