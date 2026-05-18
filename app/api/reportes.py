from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.reportes import ReporteDeudasOut, ReporteDiaOut
from app.services import reportes as service_reportes

router = APIRouter(prefix="/reportes", tags=["reportes"])


def _fecha_hoy_lima() -> date:
    return datetime.now(ZoneInfo("America/Lima")).date()


@router.get("/dia", response_model=ReporteDiaOut)
def obtener_reporte_dia(
    db: DbSession,
    fecha: date = Query(..., description="Fecha operativa en formato YYYY-MM-DD"),
) -> ReporteDiaOut:
    return service_reportes.reporte_dia(db, fecha=fecha)


@router.get("/resumen-hoy", response_model=ReporteDiaOut)
def obtener_resumen_hoy(db: DbSession) -> ReporteDiaOut:
    return service_reportes.reporte_dia(db, fecha=_fecha_hoy_lima())


@router.get("/deudas", response_model=ReporteDeudasOut)
def obtener_deudas(db: DbSession) -> ReporteDeudasOut:
    return service_reportes.reporte_deudas(db)
