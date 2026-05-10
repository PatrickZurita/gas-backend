from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.infrastructure.repositories import stock as repo_stock
from app.schemas.stock import (
    StockAjusteIn,
    StockDiaOut,
    StockEntradaIn,
    StockIniciarDiaIn,
    StockOperacionOut,
    StockResumenOut,
)

router = APIRouter(prefix="/stock", tags=["stock"])


def _fecha_hoy_lima() -> date:
    return datetime.now(ZoneInfo("America/Lima")).date()


def _resolve_fecha(fecha: date | None) -> date:
    return fecha or _fecha_hoy_lima()


@router.get("/resumen-hoy", response_model=StockResumenOut)
def obtener_stock_resumen_hoy(db: DbSession) -> StockResumenOut:
    return StockResumenOut(**repo_stock.construir_resumen(db, _fecha_hoy_lima()))


@router.get("/dia", response_model=StockDiaOut)
def obtener_stock_dia(db: DbSession, fecha: date) -> StockDiaOut:
    resumen = repo_stock.construir_resumen(db, fecha)
    jornada = repo_stock.obtener_jornada_por_fecha(db, fecha)
    movimientos = [] if jornada is None else repo_stock.listar_movimientos(db, jornada.id)
    return StockDiaOut(**resumen, movimientos=movimientos)


@router.post(
    "/iniciar-dia",
    response_model=StockResumenOut,
    status_code=status.HTTP_201_CREATED,
)
def iniciar_dia(payload: StockIniciarDiaIn, db: DbSession) -> StockResumenOut:
    fecha = _resolve_fecha(payload.fecha)
    if repo_stock.obtener_jornada_por_fecha(db, fecha) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El stock del dia ya fue iniciado.",
        )

    repo_stock.iniciar_dia(
        db,
        fecha=fecha,
        stock_inicial=payload.stock_inicial,
        observacion=payload.observacion,
    )
    return StockResumenOut(**repo_stock.construir_resumen(db, fecha))


@router.post("/entrada", response_model=StockOperacionOut)
def registrar_entrada(payload: StockEntradaIn, db: DbSession) -> StockOperacionOut:
    fecha = _resolve_fecha(payload.fecha)
    jornada = repo_stock.obtener_jornada_por_fecha(db, fecha)
    if jornada is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El stock del dia no fue iniciado.",
        )
    if jornada.cerrado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El stock del dia esta cerrado.",
        )

    movimiento = repo_stock.registrar_entrada(
        db,
        jornada=jornada,
        cantidad=payload.cantidad,
        observacion=payload.observacion,
    )
    return StockOperacionOut(
        fecha=fecha,
        tipo=movimiento.tipo,
        cantidad_delta=movimiento.cantidad_delta,
        stock_actual=movimiento.stock_resultante,
        observacion=movimiento.observacion,
    )


@router.post("/ajuste", response_model=StockOperacionOut)
def registrar_ajuste(payload: StockAjusteIn, db: DbSession) -> StockOperacionOut:
    fecha = _resolve_fecha(payload.fecha)
    jornada = repo_stock.obtener_jornada_por_fecha(db, fecha)
    if jornada is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El stock del dia no fue iniciado.",
        )
    if jornada.cerrado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El stock del dia esta cerrado.",
        )

    movimiento = repo_stock.registrar_ajuste_a_stock_fisico(
        db,
        jornada=jornada,
        stock_fisico=payload.stock_fisico,
        observacion=payload.observacion,
    )
    return StockOperacionOut(
        fecha=fecha,
        tipo=repo_stock.TIPO_AJUSTE,
        cantidad_delta=0 if movimiento is None else movimiento.cantidad_delta,
        stock_actual=payload.stock_fisico,
        observacion=payload.observacion,
    )
