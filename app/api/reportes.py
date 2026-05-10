from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.infrastructure.repositories import reportes as repo_reportes
from app.infrastructure.repositories import stock as repo_stock
from app.schemas.reportes import ReporteDeudasOut, ReporteDiaOut

router = APIRouter(prefix="/reportes", tags=["reportes"])


def _fecha_hoy_lima() -> date:
    return datetime.now(ZoneInfo("America/Lima")).date()


def _build_reporte_dia(db: Session, fecha: date) -> ReporteDiaOut:
    pedidos = repo_reportes.listar_pedidos_por_fecha(db, fecha_entrega=fecha)
    monto_total_centavos = sum(pedido["monto_total_centavos"] for pedido in pedidos)
    monto_pendiente_centavos = sum(
        pedido["monto_pendiente_centavos"] for pedido in pedidos
    )

    return ReporteDiaOut(
        fecha=fecha,
        pedidos_count=len(pedidos),
        balones_vendidos=sum(pedido["cantidad_balones"] for pedido in pedidos),
        monto_total_centavos=monto_total_centavos,
        monto_pagado_centavos=monto_total_centavos - monto_pendiente_centavos,
        monto_pendiente_centavos=monto_pendiente_centavos,
        stock=repo_stock.construir_resumen(db, fecha),
        pedidos=pedidos,
    )


@router.get("/dia", response_model=ReporteDiaOut)
def obtener_reporte_dia(
    db: DbSession,
    fecha: date = Query(..., description="Fecha operativa en formato YYYY-MM-DD"),
) -> ReporteDiaOut:
    return _build_reporte_dia(db, fecha)


@router.get("/resumen-hoy", response_model=ReporteDiaOut)
def obtener_resumen_hoy(db: DbSession) -> ReporteDiaOut:
    return _build_reporte_dia(db, _fecha_hoy_lima())


@router.get("/deudas", response_model=ReporteDeudasOut)
def obtener_deudas(db: DbSession) -> ReporteDeudasOut:
    pedidos = repo_reportes.listar_pedidos_con_deuda(db)
    return ReporteDeudasOut(
        pedidos_count=len(pedidos),
        monto_pendiente_centavos=sum(
            pedido["monto_pendiente_centavos"] for pedido in pedidos
        ),
        pedidos=pedidos,
    )
