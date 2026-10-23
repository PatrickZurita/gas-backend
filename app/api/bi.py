"""Private, aggregate-only BI endpoints; no nominal records."""

from __future__ import annotations

import json
from uuid import uuid4
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.bi_auth import PrincipalBI, require_bi_permission, require_bi_principal
from app.core.bi_db import get_bi_db
from app.services.bi import CorteBI, RANGO_MAXIMO_DIAS, construir_corte
from app.core.time import fecha_hoy_lima
from app.infrastructure.repositories import bi as repo_bi
from app.services.bi_geo import agregar_geo_del_corte, fuente_geo_disponible
from app.services.bi_geo_cache import agregar_geo_cache_temporal, cache_geo_disponible
from app.services.bi_excel import exportar_xlsx_agregado
from app.services.bi_presentacion import proyectar_corte_agregado, serializar_corte_json
from app.services.bi_periodos import comparar_periodos
from app.services.bi_semanal import comparar_semanas

router = APIRouter(
    prefix="/bi/v1", tags=["bi"], dependencies=[Depends(require_bi_principal)],
)


@router.get("/comparacion-periodos")
def comparacion_periodos(
    granularidad: Literal["semana", "quincena", "mes"] = "semana",
    peso_balon_kg: Literal["todos", "10", "45"] = "todos",
    _principal: PrincipalBI = Depends(require_bi_permission("ver_agregados")),
    db: Session = Depends(get_bi_db),
) -> Response:
    """Compare the latest two closed calendar periods in one read-only snapshot."""
    resultado = comparar_periodos(
        db, granularidad=granularidad,
        peso_balon_kg=None if peso_balon_kg == "todos" else int(peso_balon_kg),
    )
    return Response(
        content=json.dumps(resultado, ensure_ascii=False, allow_nan=False),
        media_type="application/json", headers={"Cache-Control": "no-store"},
    )


@router.get("/comparacion-semanal")
def comparacion_semanal(
    peso_balon_kg: Literal["todos", "10", "45"] = "todos",
    _principal: PrincipalBI = Depends(require_bi_permission("ver_agregados")),
    db: Session = Depends(get_bi_db),
) -> Response:
    """Two completed Lima weeks from one read-only database snapshot."""
    resultado = comparar_semanas(
        db, peso_balon_kg=None if peso_balon_kg == "todos" else int(peso_balon_kg),
    )
    return Response(
        content=json.dumps(resultado, ensure_ascii=False, allow_nan=False),
        media_type="application/json", headers={"Cache-Control": "no-store"},
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


@router.get("/corte-territorio")
def corte_territorio(
    desde: Annotated[date, Query(description="Día operativo inicial")],
    hasta: Annotated[date, Query(description="Día operativo final")],
    peso_balon_kg: Literal["todos", "10", "45"] = "todos",
    _principal: PrincipalBI = Depends(require_bi_permission("ver_agregados")),
    db: Session = Depends(get_bi_db),
) -> Response:
    """Return BI plus optional private GEO cache in one read-only snapshot.

    An empty cell list may reflect no source or privacy suppression; clients
    must inspect `geo.estado` and coverage before interpreting it.
    """
    if desde > hasta or hasta > fecha_hoy_lima() or (hasta - desde).days + 1 > RANGO_MAXIMO_DIAS:
        raise HTTPException(status_code=422, detail="Filtros BI inválidos.")
    peso = None if peso_balon_kg == "todos" else int(peso_balon_kg)
    # Pass the exact same order rows to BI and GEO. The dependency keeps both
    # operations in one repeatable-read, read-only transaction.
    pedidos = repo_bi.listar_activos_en_rango(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso,
    )
    try:
        corte = construir_corte(
            db, desde=desde, hasta=hasta, peso_balon_kg=peso,
            pedidos_base=pedidos,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Filtros BI inválidos.") from None
    if cache_geo_disponible() or fuente_geo_disponible(db):
        try:
            geo = (
                agregar_geo_cache_temporal(db, pedidos)
                if cache_geo_disponible()
                else agregar_geo_del_corte(db, pedidos)
            )
        except (ValueError, RuntimeError):
            raise HTTPException(
                status_code=503, detail="Fuente geográfica inconsistente."
            ) from None
        if (
            geo["n_pedidos_base"] != corte["resumen"]["pedidos_activos"]
            or geo["balones_base"] != corte["resumen"]["balones_vendidos"]
            or geo["venta_centavos_base"] != corte["resumen"]["vendido_centavos"]
            or geo["pedidos_con_monto_valido_base"] != corte["resumen"]["pedidos_con_monto_valido"]
        ):
            raise HTTPException(status_code=503, detail="Corte geográfico no reconciliado.")
    else:
        geo = {
            "version_definicion_geo": "geo-agregado-v1",
            "estado": "SIN_FUENTE_GEO",
            "n_pedidos_base": corte["n_pedidos_base"],
            "cobertura": None,
            "celdas_h3_res9": [],
            "zonas_validadas": [],
            "privacidad": {"minimo_clientes_por_grupo": 5},
            "avisos": [
                "No hay resultados geográficos actuales validados para este corte."
            ],
        }
    resultado = {
        "corte": proyectar_corte_agregado(corte),
        "geo": geo,
        "snapshot": {
            "alcance": "solicitud",
            "generado_en": corte["generado_en"],
            "identificador": str(uuid4()),
        },
    }
    return Response(
        content=json.dumps(resultado, ensure_ascii=False, allow_nan=False),
        media_type="application/json", headers={"Cache-Control": "no-store"},
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
