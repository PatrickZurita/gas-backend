"""Private, aggregate-only BI endpoints; no nominal records."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.bi_auth import PrincipalBI, require_bi_permission, require_bi_principal
from app.core.bi_db import get_bi_db
from app.services.bi import CorteBI, construir_corte
from app.services.bi_excel import exportar_xlsx_agregado
from app.services.bi_presentacion import serializar_corte_json

router = APIRouter(
    prefix="/bi/v1", tags=["bi"], dependencies=[Depends(require_bi_principal)],
)


def _corte_desde_filtros(
    db: Session, *, desde: date, hasta: date,
    peso_balon_kg: Literal["todos", "10", "45"],
) -> CorteBI:
    """Share validation and the read-only snapshot dependency between formats."""
    try:
        return construir_corte(
            db, desde=desde, hasta=hasta,
            peso_balon_kg=None if peso_balon_kg == "todos" else int(peso_balon_kg),
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Filtros BI inválidos.") from None


@router.get("/corte")
def corte_agregado(
    desde: Annotated[date, Query(description="Día operativo inicial")],
    hasta: Annotated[date, Query(description="Día operativo final")],
    peso_balon_kg: Literal["todos", "10", "45"] = "todos",
    _principal: PrincipalBI = Depends(require_bi_permission("ver_agregados")),
    db: Session = Depends(get_bi_db),
) -> Response:
    """One definition and one database snapshot for the whole web dashboard."""
    corte = _corte_desde_filtros(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg,
    )
    return Response(
        content=serializar_corte_json(corte), media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/corte.xlsx")
def descargar_corte_agregado(
    desde: Annotated[date, Query(description="Día operativo inicial")],
    hasta: Annotated[date, Query(description="Día operativo final")],
    peso_balon_kg: Literal["todos", "10", "45"] = "todos",
    _principal: PrincipalBI = Depends(require_bi_permission("exportar_agregados")),
    db: Session = Depends(get_bi_db),
) -> Response:
    """Return only the aggregate workbook, generated in memory for this request."""
    corte = _corte_desde_filtros(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg,
    )
    filename = f"gas-bi-{desde.isoformat()}_{hasta.isoformat()}-{peso_balon_kg}.xlsx"
    return Response(
        content=exportar_xlsx_agregado(corte),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-BI-Generado-En": corte["generado_en"],
        },
    )
