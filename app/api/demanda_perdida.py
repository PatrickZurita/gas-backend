"""Router de demanda perdida (P1 #2): la llamada que NO se pudo atender.

No toca stock ni pedidos: cero efectos sobre las ventas del dia.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.core.time import fecha_hoy_lima
from app.schemas.demanda_perdida import (
    DemandaPerdidaCreate,
    DemandaPerdidaOut,
    DemandaPerdidaResumenOut,
)
from app.services import demanda_perdida as service_demanda_perdida

router = APIRouter(prefix="/demanda-perdida", tags=["demanda-perdida"])

# Default del resumen: ultimos 7 dias operativos Lima (decision D9).
_DIAS_RESUMEN_DEFAULT = 7


@router.post(
    "",
    response_model=DemandaPerdidaOut,
    status_code=status.HTTP_201_CREATED,
)
def registrar_demanda_perdida(
    payload: DemandaPerdidaCreate, db: DbSession
) -> DemandaPerdidaOut:
    """Registra el evento con la fecha operativa de hoy (Lima)."""
    return service_demanda_perdida.registrar(
        db,
        fecha=fecha_hoy_lima(),
        motivo=payload.motivo,
        zona_texto=payload.zona_texto,
        cantidad_balones=payload.cantidad_balones,
        peso_balon_kg=payload.peso_balon_kg,
    )


@router.get(
    "",
    response_model=list[DemandaPerdidaOut],
    status_code=status.HTTP_200_OK,
)
def listar_demanda_perdida(
    db: DbSession,
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
) -> list[DemandaPerdidaOut]:
    """Detalle para auditar registros sueltos, orden created_at DESC."""
    return service_demanda_perdida.listar(
        db, desde=desde, hasta=hasta, limit=limit
    )


@router.get(
    "/resumen",
    response_model=DemandaPerdidaResumenOut,
    status_code=status.HTTP_200_OK,
)
def obtener_resumen_demanda_perdida(
    db: DbSession,
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
) -> DemandaPerdidaResumenOut:
    """Resumen del caso 2do courier. Sin parametros: ultimos 7 dias Lima."""
    hasta_resuelta = hasta or fecha_hoy_lima()
    desde_resuelta = desde or hasta_resuelta - timedelta(
        days=_DIAS_RESUMEN_DEFAULT - 1
    )
    return service_demanda_perdida.resumen(
        db, desde=desde_resuelta, hasta=hasta_resuelta
    )
