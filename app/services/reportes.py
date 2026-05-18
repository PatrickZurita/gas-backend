"""Service `reportes` con dispatch PostgreSQL/DynamoDB."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from typing import TYPE_CHECKING

from app.core.storage import is_dynamodb_enabled
from app.schemas.reportes import (
    PedidoDeudaOut,
    PedidoReporteDiaOut,
    ReporteDeudasOut,
    ReporteDiaOut,
)
from app.services import stock as service_stock

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _require_db(db: "Session | None") -> "Session":
    if db is None:
        raise RuntimeError(
            "Servicio PostgreSQL requiere sesion; "
            "storage actual no esta inyectando una."
        )
    return db


def _ddb_pedido_to_reporte_dia(p) -> PedidoReporteDiaOut:
    try:
        fecha = date_cls.fromisoformat(p.fecha_entrega)
    except ValueError:
        fecha = date_cls.today()
    try:
        created_at = datetime.fromisoformat(p.created_at)
    except ValueError:
        created_at = datetime.utcnow()
    return PedidoReporteDiaOut(
        id=p.id,
        cliente_id=p.cliente_id,
        cliente_alias=p.cliente_alias,
        cantidad_balones=p.cantidad_balones,
        tipo_balon=p.tipo_balon,
        marca_balon=p.marca_balon,
        precio_unitario_centavos=p.precio_unitario_centavos,
        monto_total_centavos=p.total_centavos,
        monto_pendiente_centavos=p.pendiente_centavos,
        pagado=p.pagado,
        fecha_entrega=fecha,
        created_at=created_at,
    )


def _ddb_pedido_to_deuda(p) -> PedidoDeudaOut:
    base = _ddb_pedido_to_reporte_dia(p)
    return PedidoDeudaOut(**base.model_dump())


def reporte_dia(db: "Session | None", *, fecha: date_cls) -> ReporteDiaOut:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import pedidos as ddb_pedidos

        items = ddb_pedidos.listar_pedidos_por_fecha(fecha.isoformat())
        pedidos_out = [_ddb_pedido_to_reporte_dia(p) for p in items]
        monto_total = sum(p.monto_total_centavos for p in pedidos_out)
        monto_pendiente = sum(p.monto_pendiente_centavos for p in pedidos_out)
        return ReporteDiaOut(
            fecha=fecha,
            pedidos_count=len(pedidos_out),
            balones_vendidos=sum(p.cantidad_balones for p in pedidos_out),
            monto_total_centavos=monto_total,
            monto_pagado_centavos=monto_total - monto_pendiente,
            monto_pendiente_centavos=monto_pendiente,
            stock=service_stock.resumen(db, fecha=fecha),
            pedidos=pedidos_out,
        )

    from app.infrastructure.repositories import reportes as repo_reportes

    session = _require_db(db)
    pedidos = repo_reportes.listar_pedidos_por_fecha(session, fecha_entrega=fecha)
    monto_total = sum(p["monto_total_centavos"] for p in pedidos)
    monto_pendiente = sum(p["monto_pendiente_centavos"] for p in pedidos)
    return ReporteDiaOut(
        fecha=fecha,
        pedidos_count=len(pedidos),
        balones_vendidos=sum(p["cantidad_balones"] for p in pedidos),
        monto_total_centavos=monto_total,
        monto_pagado_centavos=monto_total - monto_pendiente,
        monto_pendiente_centavos=monto_pendiente,
        stock=service_stock.resumen(db, fecha=fecha),
        pedidos=pedidos,
    )


def reporte_deudas(db: "Session | None") -> ReporteDeudasOut:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories.reportes import (
            _scan_all_pedidos,
        )

        all_pedidos = _scan_all_pedidos()
        con_deuda = [p for p in all_pedidos if p.pendiente_centavos > 0]
        con_deuda.sort(
            key=lambda p: (p.fecha_entrega, p.created_at),
            reverse=True,
        )
        items = [_ddb_pedido_to_deuda(p) for p in con_deuda]
        return ReporteDeudasOut(
            pedidos_count=len(items),
            monto_pendiente_centavos=sum(p.monto_pendiente_centavos for p in items),
            pedidos=items,
        )

    from app.infrastructure.repositories import reportes as repo_reportes

    session = _require_db(db)
    pedidos = repo_reportes.listar_pedidos_con_deuda(session)
    return ReporteDeudasOut(
        pedidos_count=len(pedidos),
        monto_pendiente_centavos=sum(p["monto_pendiente_centavos"] for p in pedidos),
        pedidos=pedidos,
    )
