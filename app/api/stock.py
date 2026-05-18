from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.schemas.stock import (
    StockAjusteIn,
    StockDiaOut,
    StockEntradaIn,
    StockIniciarDiaIn,
    StockOperacionOut,
    StockResumenOut,
)
from app.services import stock as service_stock
from app.services.errors import (
    StockCerradoError,
    StockNoIniciadoError,
    StockYaIniciadoError,
)

router = APIRouter(prefix="/stock", tags=["stock"])


def _fecha_hoy_lima() -> date:
    return datetime.now(ZoneInfo("America/Lima")).date()


def _resolve_fecha(fecha: date | None) -> date:
    return fecha or _fecha_hoy_lima()


@router.get("/resumen-hoy", response_model=StockResumenOut)
def obtener_stock_resumen_hoy(db: DbSession) -> StockResumenOut:
    return service_stock.resumen(db, fecha=_fecha_hoy_lima())


@router.get("/dia", response_model=StockDiaOut)
def obtener_stock_dia(db: DbSession, fecha: date) -> StockDiaOut:
    return service_stock.stock_dia(db, fecha=fecha)


@router.post(
    "/iniciar-dia",
    response_model=StockResumenOut,
    status_code=status.HTTP_201_CREATED,
)
def iniciar_dia(payload: StockIniciarDiaIn, db: DbSession) -> StockResumenOut:
    fecha = _resolve_fecha(payload.fecha)
    try:
        return service_stock.iniciar_dia(
            db,
            fecha=fecha,
            stock_inicial=payload.stock_inicial,
            observacion=payload.observacion,
        )
    except StockYaIniciadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.post("/entrada", response_model=StockOperacionOut)
def registrar_entrada(payload: StockEntradaIn, db: DbSession) -> StockOperacionOut:
    fecha = _resolve_fecha(payload.fecha)
    try:
        return service_stock.registrar_entrada(
            db,
            fecha=fecha,
            cantidad=payload.cantidad,
            observacion=payload.observacion,
        )
    except StockNoIniciadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except StockCerradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.post("/ajuste", response_model=StockOperacionOut)
def registrar_ajuste(payload: StockAjusteIn, db: DbSession) -> StockOperacionOut:
    fecha = _resolve_fecha(payload.fecha)
    try:
        return service_stock.registrar_ajuste(
            db,
            fecha=fecha,
            stock_fisico=payload.stock_fisico,
            observacion=payload.observacion,
        )
    except StockNoIniciadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except StockCerradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
