"""Nominal BI access restricted to an audited local owner session."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.bi_auth import PrincipalBI, require_bi_permission
from app.core.bi_db import get_bi_db
from app.core.bi_nominal_audit import AuditoriaNominal, iniciar_auditoria_nominal
from app.services.bi import construir_corte
from app.services.bi_nominal import (
    pagina_clientes_registrados, pagina_pedidos, pagina_pausas_clientes,
    preparar_exportacion_clientes_registrados, preparar_exportacion_pedidos,
)
from app.services.bi_nominal_excel import (
    exportar_xlsx_clientes_registrados, exportar_xlsx_pedidos_nominales,
)

router = APIRouter(
    prefix="/bi/v1", tags=["bi-nominal-local"],
    dependencies=[Depends(iniciar_auditoria_nominal)],
)
Peso = Literal["todos", "10", "45"]


def _peso(valor: Peso) -> int | None:
    return None if valor == "todos" else int(valor)


def _pagina_o_422(operacion, *args, **kwargs):
    try:
        return operacion(*args, **kwargs)
    except ValueError:
        raise HTTPException(status_code=422, detail="Filtros o límite BI inválidos.") from None


def _snapshot(resultado: dict) -> dict:
    resultado["metadatos"]["snapshot_garantizado"] = True
    resultado["metadatos"]["snapshot_alcance"] = "solicitud"
    return resultado


def _validar_paridad_pedidos(extracto: dict, corte: dict) -> None:
    pedidos = extracto["pedidos"]
    validos = [fila for fila in pedidos if fila["estado_monto"] == "valido"]
    resumen = corte["resumen"]
    cobertura = corte["cobertura"]
    comparaciones = (
        (extracto["metadatos"]["total_registros"], corte["n_pedidos_base"]),
        (extracto["metadatos"]["clientes_compradores"], resumen["clientes_compradores"]),
        (extracto["cobertura"]["pedidos_con_monto_valido"], resumen["pedidos_con_monto_valido"]),
        (sum(fila["monto_total_centavos"] for fila in validos), resumen["vendido_centavos"]),
        (sum(fila["monto_pendiente_centavos"] for fila in validos), resumen["pendiente_centavos"]),
        (sum(fila["cobrado_calculado_centavos"] for fila in validos), resumen["cobrado_calculado_centavos"]),
    )
    if any(izquierda != derecha for izquierda, derecha in comparaciones) or any(
        extracto["cobertura"][campo] != cobertura[campo]
        for campo in (
            "pedidos_monto_total_legacy", "pedidos_pendiente_legacy",
            "pedidos_sin_monto_valido", "pedidos_monetarios_anomalos",
        )
    ):
        raise HTTPException(status_code=503, detail="No se pudo conciliar el corte BI.")


@router.get("/clientes")
def listar_clientes_nominales(
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    auditoria: AuditoriaNominal = Depends(iniciar_auditoria_nominal),
    principal: PrincipalBI = Depends(require_bi_permission("ver_nominales")),
    db: Session = Depends(get_bi_db),
) -> dict:
    resultado = _snapshot(_pagina_o_422(
        pagina_clientes_registrados, db, offset=offset, limit=limit,
    ))
    auditoria.terminar("served", google_sub=principal.google_sub,
                      filtros={"offset": offset, "limit": limit},
                      filas=len(resultado["filas"]))
    return resultado


@router.get("/pedidos")
def listar_pedidos_nominales(
    desde: Annotated[date, Query()],
    hasta: Annotated[date, Query()],
    peso_balon_kg: Peso = "todos",
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    auditoria: AuditoriaNominal = Depends(iniciar_auditoria_nominal),
    principal: PrincipalBI = Depends(require_bi_permission("ver_nominales")),
    db: Session = Depends(get_bi_db),
) -> dict:
    resultado = _snapshot(_pagina_o_422(
        pagina_pedidos, db, desde=desde, hasta=hasta,
        peso_balon_kg=_peso(peso_balon_kg), offset=offset, limit=limit,
    ))
    auditoria.terminar("served", google_sub=principal.google_sub,
                      filtros={"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                               "peso_balon_kg": peso_balon_kg, "offset": offset,
                               "limit": limit}, filas=len(resultado["filas"]))
    return resultado


@router.get("/clientes/pausas")
def listar_pausas_clientes(
    desde: Annotated[date, Query()],
    hasta: Annotated[date, Query()],
    peso_balon_kg: Peso = "todos",
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    auditoria: AuditoriaNominal = Depends(iniciar_auditoria_nominal),
    principal: PrincipalBI = Depends(require_bi_permission("ver_nominales")),
    db: Session = Depends(get_bi_db),
) -> dict:
    resultado = _snapshot(_pagina_o_422(
        pagina_pausas_clientes, db, desde=desde, hasta=hasta,
        peso_balon_kg=_peso(peso_balon_kg), offset=offset, limit=limit,
    ))
    auditoria.terminar(
        "served", google_sub=principal.google_sub,
        filtros={"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                 "peso_balon_kg": peso_balon_kg, "offset": offset,
                 "limit": limit},
        filas=len(resultado["filas"]),
    )
    return resultado


def _respuesta_excel(contenido: bytes, *, nombre: str, generado_en: str) -> Response:
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "Cache-Control": "no-store",
            "X-BI-Generado-En": generado_en,
        },
    )


@router.post("/clientes/export")
def exportar_clientes_nominales(
    auditoria: AuditoriaNominal = Depends(iniciar_auditoria_nominal),
    principal: PrincipalBI = Depends(require_bi_permission("exportar_nominales")),
    db: Session = Depends(get_bi_db),
) -> Response:
    extracto = _snapshot(_pagina_o_422(preparar_exportacion_clientes_registrados, db))
    contenido = _pagina_o_422(exportar_xlsx_clientes_registrados, extracto)
    auditoria.terminar("prepared", google_sub=principal.google_sub,
                      filas=len(extracto["clientes"]), bytes_preparados=len(contenido))
    return _respuesta_excel(contenido, nombre="gas-clientes-registrados.xlsx",
                           generado_en=extracto["metadatos"]["generado_en"])


@router.post("/pedidos/export")
def exportar_pedidos_nominales(
    desde: Annotated[date, Query()],
    hasta: Annotated[date, Query()],
    peso_balon_kg: Peso = "todos",
    auditoria: AuditoriaNominal = Depends(iniciar_auditoria_nominal),
    principal: PrincipalBI = Depends(require_bi_permission("exportar_nominales")),
    db: Session = Depends(get_bi_db),
) -> Response:
    peso = _peso(peso_balon_kg)
    extracto = _snapshot(_pagina_o_422(
        preparar_exportacion_pedidos, db, desde=desde, hasta=hasta,
        peso_balon_kg=peso,
    ))
    corte = _pagina_o_422(
        construir_corte, db, desde=desde, hasta=hasta, peso_balon_kg=peso,
    )
    _validar_paridad_pedidos(extracto, corte)
    contenido = _pagina_o_422(exportar_xlsx_pedidos_nominales, extracto)
    auditoria.terminar(
        "prepared", google_sub=principal.google_sub,
        filtros={"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                 "peso_balon_kg": peso_balon_kg},
        filas=len(extracto["pedidos"]), bytes_preparados=len(contenido),
    )
    nombre = f"gas-pedidos-{desde.isoformat()}_{hasta.isoformat()}-{peso_balon_kg}.xlsx"
    return _respuesta_excel(contenido, nombre=nombre,
                           generado_en=extracto["metadatos"]["generado_en"])
