from datetime import date

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.core.time import fecha_hoy_lima
from app.schemas.reportes import ReporteDeudasOut, ReporteDiaOut
from app.services import reportes as service_reportes

router = APIRouter(prefix="/reportes", tags=["reportes"])


@router.get("/dia", response_model=ReporteDiaOut)
def obtener_reporte_dia(
    db: DbSession,
    fecha: date = Query(..., description="Fecha operativa en formato YYYY-MM-DD"),
) -> ReporteDiaOut:
    return service_reportes.reporte_dia(db, fecha=fecha)


@router.get("/resumen-hoy", response_model=ReporteDiaOut)
def obtener_resumen_hoy(db: DbSession) -> ReporteDiaOut:
    return service_reportes.reporte_dia(db, fecha=fecha_hoy_lima())


@router.get("/deudas", response_model=ReporteDeudasOut)
def obtener_deudas(db: DbSession) -> ReporteDeudasOut:
    return service_reportes.reporte_deudas(db)
