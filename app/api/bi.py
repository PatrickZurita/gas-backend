"""Private, aggregate-only BI endpoints; no nominal records or exports."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.bi_auth import PrincipalBI, require_bi_permission, require_bi_principal
from app.core.bi_db import get_bi_db
from app.services.bi import construir_corte
from app.services.bi_presentacion import serializar_corte_json

router = APIRouter(
    prefix="/bi/v1", tags=["bi"], dependencies=[Depends(require_bi_principal)],
)


@router.get("/corte")
def corte_agregado(
    desde: Annotated[date, Query(description="Día operativo inicial")],
    hasta: Annotated[date, Query(description="Día operativo final")],
    peso_balon_kg: Literal["todos", "10", "45"] = "todos",
    _principal: PrincipalBI = Depends(require_bi_permission("ver_agregados")),
    db: Session = Depends(get_bi_db),
) -> Response:
    """One definition and one database snapshot for the whole web dashboard."""
    try:
        corte = construir_corte(
            db, desde=desde, hasta=hasta,
            peso_balon_kg=None if peso_balon_kg == "todos" else int(peso_balon_kg),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=serializar_corte_json(corte), media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
