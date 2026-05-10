from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Cliente, Pedido


class PedidoReporteRow(TypedDict):
    id: int
    cliente_id: int
    cliente_alias: str
    cantidad_balones: int
    tipo_balon: str
    marca_balon: str
    precio_unitario_centavos: int | None
    monto_total_centavos: int
    monto_pendiente_centavos: int
    pagado: bool
    fecha_entrega: date
    created_at: datetime


def _soles_a_centavos(monto_soles: Decimal) -> int:
    return int((Decimal(monto_soles) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _monto_total_centavos(pedido: Pedido) -> int:
    return (
        pedido.monto_total_centavos
        if pedido.monto_total_centavos is not None
        else _soles_a_centavos(pedido.total_soles)
    )


def _monto_pendiente_centavos(pedido: Pedido) -> int:
    return (
        pedido.monto_pendiente_centavos
        if pedido.monto_pendiente_centavos is not None
        else _soles_a_centavos(pedido.saldo_pendiente)
    )


def _pedido_to_reporte_row(pedido: Pedido, cliente_alias: str) -> PedidoReporteRow:
    return {
        "id": pedido.id,
        "cliente_id": pedido.cliente_id,
        "cliente_alias": cliente_alias,
        "cantidad_balones": pedido.cantidad_balones,
        "tipo_balon": pedido.tipo_balon,
        "marca_balon": pedido.marca_balon,
        "precio_unitario_centavos": pedido.precio_unitario_centavos,
        "monto_total_centavos": _monto_total_centavos(pedido),
        "monto_pendiente_centavos": _monto_pendiente_centavos(pedido),
        "pagado": pedido.pagado,
        "fecha_entrega": pedido.fecha_entrega,
        "created_at": pedido.created_at,
    }


def listar_pedidos_por_fecha(
    db: Session,
    fecha_entrega: date,
) -> list[PedidoReporteRow]:
    stmt = (
        select(Pedido, Cliente.alias)
        .join(Cliente, Pedido.cliente_id == Cliente.id)
        .where(Pedido.fecha_entrega == fecha_entrega)
        .order_by(Pedido.created_at.desc(), Pedido.id.desc())
    )

    return [
        _pedido_to_reporte_row(pedido, cliente_alias)
        for pedido, cliente_alias in db.execute(stmt).all()
    ]


def listar_pedidos_con_deuda(db: Session) -> list[PedidoReporteRow]:
    stmt = (
        select(Pedido, Cliente.alias)
        .join(Cliente, Pedido.cliente_id == Cliente.id)
        .where(Pedido.saldo_pendiente > 0)
        .order_by(
            Pedido.fecha_entrega.desc(),
            Pedido.created_at.desc(),
            Pedido.id.desc(),
        )
    )

    return [
        _pedido_to_reporte_row(pedido, cliente_alias)
        for pedido, cliente_alias in db.execute(stmt).all()
    ]
