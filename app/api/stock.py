from datetime import date

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.core.time import fecha_hoy_lima
from app.schemas.stock import (
    StockAjusteIn,
    StockContinuarPreviewOut,
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


def _resolve_fecha(fecha: date | None) -> date:
    return fecha or fecha_hoy_lima()


@router.get("/resumen-hoy", response_model=StockResumenOut)
def obtener_stock_resumen_hoy(db: DbSession) -> StockResumenOut:
    return service_stock.resumen(db, fecha=fecha_hoy_lima())


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


@router.get("/preview-continuar", response_model=StockContinuarPreviewOut)
def preview_continuar(db: DbSession) -> StockContinuarPreviewOut:
    """Devuelve si existe una jornada anterior con stock disponible
    para arrastrar al dia actual. Usado por el frontend antes de
    ofrecer el carry-over al usuario.
    """
    return service_stock.preview_continuar_dia(db, fecha=fecha_hoy_lima())


@router.post(
    "/continuar-de-ayer",
    response_model=StockResumenOut,
    status_code=status.HTTP_201_CREATED,
)
def continuar_de_ayer(db: DbSession) -> StockResumenOut:
    """Crea la jornada de hoy arrastrando el stock por peso de la
    ultima jornada anterior. Evita que el usuario tenga que recontar
    fisicamente el stock cada manana.
    """
    try:
        return service_stock.continuar_de_ayer(db, fecha=fecha_hoy_lima())
    except StockYaIniciadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except StockNoIniciadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
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
            peso_balon_kg=payload.peso_balon_kg,
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
            peso_balon_kg=payload.peso_balon_kg,
        )
    except StockNoIniciadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except StockCerradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
