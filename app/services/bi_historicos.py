"""Revisión privada de compradores observados desde el inicio de GAS.

Los segmentos son señales descriptivas para revisión humana, nunca estados de
abandono ni instrucciones de contacto.
"""

from __future__ import annotations

from datetime import date, datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import LIMA_TZ, fecha_hoy_lima
from app.infrastructure.repositories.bi_nominal import _predicados_pedidos
from app.models.models import Cliente, Pedido
from app.services.bi_nominal import _db_pg, _validar_pagina, VERSION_NOMINAL
from app.services.bi import VERSION_DEFINICIONES

INICIO_OBSERVABLE = date(2026, 5, 21)
SEGMENTOS = {"todos", "compra_unica_antigua", "recurrente_pausa_larga",
             "recurrente_pausa_relativa", "sin_senal_prioritaria"}


def _banda(dias: int) -> str:
    if dias < 30:
        return "0_29"
    if dias < 60:
        return "30_59"
    if dias < 90:
        return "60_89"
    if dias < 120:
        return "90_119"
    return "120_mas"


def pagina_compradores_historicos(
    db: Session | None, *, fecha_corte: date, peso_balon_kg: int | None = None,
    segmento: str = "todos", offset: int = 0, limit: int = 100,
) -> dict:
    db = _db_pg(db)
    _validar_pagina(offset, limit)
    if (fecha_corte < INICIO_OBSERVABLE or fecha_corte > fecha_hoy_lima()
            or peso_balon_kg not in (None, 10, 45) or segmento not in SEGMENTOS):
        raise ValueError("Filtro histórico inválido")

    # Un único snapshot read-only de la solicitud; se incluyen compradores sin
    # pedidos recientes. DISTINCT impide convertir dos pedidos del día en dos
    # intervalos de recompra.
    stmt = (
        select(Pedido.cliente_id, Pedido.fecha_entrega)
        .where(*_predicados_pedidos(INICIO_OBSERVABLE, fecha_corte, peso_balon_kg))
        .distinct().order_by(Pedido.cliente_id, Pedido.fecha_entrega)
    )
    historia: dict[int, list[date]] = {}
    for cliente_id, dia in db.execute(stmt):
        historia.setdefault(cliente_id, []).append(dia)

    ids = list(historia)
    clientes = {}
    if ids:
        clientes = {fila.id: fila for fila in db.execute(
            select(Cliente.id, Cliente.alias, Cliente.telefono)
            .where(Cliente.id.in_(ids))
        ).all()}
    if len(clientes) != len(ids):
        raise RuntimeError("Historia sin cliente correspondiente")

    conteos = {s: 0 for s in SEGMENTOS if s != "todos"}
    bandas = {s: 0 for s in ("0_29", "30_59", "60_89", "90_119", "120_mas")}
    con_telefono = 0
    filas = []
    for cliente_id, dias in historia.items():
        edad = (fecha_corte - dias[-1]).days
        intervalos = [(b - a).days for a, b in zip(dias, dias[1:])]
        cadencia = None
        if len(dias) >= 3 and len(intervalos) >= 2:
            cadencia = {"intervalos_observados": len(intervalos),
                        "mediana_intervalo_dias": median(intervalos),
                        "intervalo_min_dias": min(intervalos),
                        "intervalo_max_dias": max(intervalos)}
        if len(dias) == 1 and edad >= 120:
            tipo = "compra_unica_antigua"
        elif len(dias) >= 2 and edad >= 120:
            tipo = "recurrente_pausa_larga"
        elif cadencia and edad >= max(30, 2 * cadencia["mediana_intervalo_dias"]):
            tipo = "recurrente_pausa_relativa"
        else:
            tipo = "sin_senal_prioritaria"
        conteos[tipo] += 1
        bandas[_banda(edad)] += 1
        cliente = clientes[cliente_id]
        telefono_disponible = bool((cliente.telefono or "").strip())
        con_telefono += telefono_disponible
        filas.append({
            "cliente_id": cliente_id, "alias": cliente.alias,
            "telefono": cliente.telefono, "telefono_disponible": telefono_disponible,
            "segmento_revision": tipo, "primera_compra_observada": dias[0].isoformat(),
            "ultima_compra_registrada": dias[-1].isoformat(),
            "dias_sin_compra_registrada": edad, "banda_dias": _banda(edad),
            "dias_compra_observados": len(dias), "cadencia_individual": cadencia,
        })
    filas.sort(key=lambda f: (-f["dias_sin_compra_registrada"], f["cliente_id"]))
    seleccionadas = filas if segmento == "todos" else [
        f for f in filas if f["segmento_revision"] == segmento
    ]
    filtros = {"desde": INICIO_OBSERVABLE.isoformat(),
               "fecha_corte": fecha_corte.isoformat(),
               "peso_balon_kg": peso_balon_kg if peso_balon_kg is not None else "todos",
               "segmento": segmento, "estado": "ACTIVO"}
    return {
        "metadatos": {
            "version_definiciones": VERSION_DEFINICIONES,
            "version_nominal": VERSION_NOMINAL,
            "generado_en": datetime.now(LIMA_TZ).isoformat(),
            "zona_horaria": "America/Lima", "fuente": "PostgreSQL",
            "fecha_base": "fecha_entrega_registrada",
            "poblacion": "compradores_historicos_observables",
            "filtros": filtros, "fecha_corte": fecha_corte.isoformat(),
            "estado_observacion": "dia_abierto" if fecha_corte == fecha_hoy_lima() else "hasta_dia_cerrado",
            "dias_historia_observable": (fecha_corte - INICIO_OBSERVABLE).days + 1,
            "calidad_fecha": "fecha_entrega_registrada_sin_marca_de_carga_tardia",
            "total_registros": len(seleccionadas),
            "denominadores": {"compradores_observados": len(filas),
                              "por_segmento": conteos, "por_banda_dias": bandas,
                              "con_telefono": con_telefono,
                              "sin_telefono": len(filas) - con_telefono},
            "regla_segmentos": {
                "compra_unica_antigua": "un día de compra observado y 120+ días sin nueva compra",
                "recurrente_pausa_larga": "dos o más días de compra y 120+ días sin nueva compra",
                "recurrente_pausa_relativa": "tres o más días de compra, dos o más intervalos, pausa >= max(30 días, 2 veces mediana individual), excluye pausa larga",
            },
            "orden": "dias_sin_compra_desc_cliente_id_asc",
            "snapshot_garantizado": False,
            "avisos": [
                "El historial comienza el 21-may-2026; primera compra observada no prueba alta nueva.",
                "Sin compra registrada no equivale a abandono ni compra con competidor.",
                "El día de hoy puede estar abierto y los pedidos pueden cargarse tarde.",
                "Las señales requieren revisión humana; no autorizan contacto automático.",
            ],
        },
        "offset": offset, "limite": limit,
        "filas": seleccionadas[offset:offset + limit],
    }
