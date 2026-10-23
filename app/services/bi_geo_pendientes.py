"""Cola nominal de direcciones sin H3, solo para revisión privada del dueño."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import LIMA_TZ, fecha_hoy_lima
from app.infrastructure.repositories import bi as repo_bi
from app.models.models import Cliente, Direccion
from app.services.bi import RANGO_MAXIMO_DIAS, VERSION_DEFINICIONES
from app.services.bi_geo import filas_geo_del_corte, fuente_geo_disponible
from app.services.bi_geo_cache import cache_geo_disponible, filas_geo_cache_temporal
from app.services.bi_nominal import VERSION_NOMINAL, _db_pg, _validar_pagina

ESTADOS_COLA = frozenset({
    "todos", "NO_GEOCODIFICADO", "SIN_RESULTADO", "RECHAZADO_PRECISION",
    "RECHAZADO_BOUNDS", "PENDIENTE_DUENO", "SIN_H3",
})


def pagina_direcciones_pendientes(
    db: Session | None, *, desde: date, hasta: date,
    peso_balon_kg: int | None = None, estado: str = "todos",
    offset: int = 0, limit: int = 100,
) -> dict:
    """Rank affected addresses from the exact GEO source used by Territorio."""
    db = _db_pg(db)
    _validar_pagina(offset, limit)
    if (
        desde > hasta or hasta > fecha_hoy_lima()
        or (hasta - desde).days + 1 > RANGO_MAXIMO_DIAS
        or peso_balon_kg not in (None, 10, 45) or estado not in ESTADOS_COLA
    ):
        raise ValueError("Filtros GEO inválidos")

    pedidos = repo_bi.listar_activos_en_rango(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg,
    )
    if cache_geo_disponible():
        filas_geo, _, _ = filas_geo_cache_temporal(db, pedidos)
        fuente = "cache_local_google_temporal"
    elif fuente_geo_disponible(db):
        filas_geo, _ = filas_geo_del_corte(db, pedidos)
        fuente = "resultados_geo_temporales"
    else:
        raise RuntimeError("Fuente GEO no disponible")
    if len(filas_geo) != len(pedidos) or any(
        int(geo.pedido_id) != pedido.pedido_id
        for pedido, geo in zip(pedidos, filas_geo)
    ):
        raise RuntimeError("Población GEO no reconciliada")

    # Match agregar_geo(): a cell is usable only with accepted precision.
    pendientes = [(pedido, geo) for pedido, geo in zip(pedidos, filas_geo)
                  if not (geo.geocoding_estado == "OK"
                          and geo.geocoding_precision in {"HIGH", "MEDIUM"}
                          and geo.h3_res9 is not None)]
    direccion_ids = {pedido.direccion_id for pedido, _ in pendientes}
    direcciones = {fila.id: fila for fila in db.execute(
        select(Direccion.id, Direccion.cliente_id, Direccion.texto_original,
               Direccion.distrito, Direccion.referencia)
        .where(Direccion.id.in_(direccion_ids))
    ).all()} if direccion_ids else {}
    if set(direcciones) != direccion_ids:
        raise RuntimeError("Direcciones GEO no reconciliadas")
    cliente_ids = {pedido.cliente_id for pedido, _ in pendientes}
    clientes = {fila.id: fila.alias for fila in db.execute(
        select(Cliente.id, Cliente.alias).where(Cliente.id.in_(cliente_ids))
    ).all()} if cliente_ids else {}
    if set(clientes) != cliente_ids:
        raise RuntimeError("Clientes GEO no reconciliados")

    grupos: dict[int, dict] = {}
    compradores_por_direccion: dict[int, set[int]] = {}
    for pedido, geo in pendientes:
        direccion = direcciones[pedido.direccion_id]
        estado_geo = geo.geocoding_estado if geo.geocoding_estado != "OK" else "SIN_H3"
        compradores_por_direccion.setdefault(pedido.direccion_id, set()).add(
            pedido.cliente_id
        )
        grupo = grupos.setdefault(pedido.direccion_id, {
            "direccion_id": pedido.direccion_id,
            "cliente_id": None,
            "alias_cliente": None,
            "texto_original": direccion.texto_original,
            "distrito": direccion.distrito,
            "referencia": direccion.referencia,
            "estado_geo": estado_geo,
            "motivo_tecnico": geo.motivo_tecnico or (
                "PRECISION_BAJA" if geo.geocoding_precision == "LOW" else "H3_AUSENTE"
            ),
            "clientes_afectados": 0,
            "pedidos_afectados": 0,
            "balones_afectados": 0,
            "primera_entrega_registrada": pedido.fecha_entrega.isoformat(),
            "ultima_entrega_registrada": pedido.fecha_entrega.isoformat(),
        })
        if grupo["estado_geo"] != estado_geo or grupo["motivo_tecnico"] != (
            geo.motivo_tecnico or (
                "PRECISION_BAJA" if geo.geocoding_precision == "LOW" else "H3_AUSENTE"
            )
        ):
            raise RuntimeError("Clasificación GEO inconsistente por dirección")
        grupo["pedidos_afectados"] += 1
        grupo["balones_afectados"] += pedido.cantidad_balones
        grupo["primera_entrega_registrada"] = min(
            grupo["primera_entrega_registrada"], pedido.fecha_entrega.isoformat()
        )
        grupo["ultima_entrega_registrada"] = max(
            grupo["ultima_entrega_registrada"], pedido.fecha_entrega.isoformat()
        )

    for direccion_id, grupo in grupos.items():
        compradores = compradores_por_direccion[direccion_id]
        grupo["clientes_afectados"] = len(compradores)
        if len(compradores) == 1:
            grupo["cliente_id"] = next(iter(compradores))
            grupo["alias_cliente"] = clientes[grupo["cliente_id"]]

    filas = sorted(grupos.values(), key=lambda fila: (
        -fila["pedidos_afectados"], -fila["balones_afectados"], fila["direccion_id"]
    ))
    seleccionadas = filas if estado == "todos" else [
        fila for fila in filas if fila["estado_geo"] == estado
    ]
    por_estado_direcciones = Counter(fila["estado_geo"] for fila in filas)
    por_estado_pedidos = Counter(
        geo.geocoding_estado if geo.geocoding_estado != "OK" else "SIN_H3"
        for _, geo in pendientes
    )
    return {
        "metadatos": {
            "version_definiciones": VERSION_DEFINICIONES,
            "version_nominal": VERSION_NOMINAL,
            "version_definicion_geo": "geo-agregado-v1",
            "generado_en": datetime.now(LIMA_TZ).isoformat(),
            "zona_horaria": "America/Lima",
            "fuente": "PostgreSQL",
            "fuente_geo": fuente,
            "fecha_base": "fecha_entrega_registrada",
            "poblacion": "direcciones_con_pedidos_activos_sin_h3_res9",
            "filtros": {
                "desde": desde.isoformat(), "hasta": hasta.isoformat(),
                "peso_balon_kg": peso_balon_kg if peso_balon_kg is not None else "todos",
                "estado": estado, "pedido_estado": "ACTIVO",
            },
            "estado_observacion": "dia_abierto" if hasta == fecha_hoy_lima() else "hasta_dia_cerrado",
            "total_registros": len(seleccionadas),
            "denominadores": {
                "pedidos_activos": len(pedidos),
                "pedidos_con_h3_res9": len(pedidos) - len(pendientes),
                "pedidos_sin_h3_res9": len(pendientes),
                "direcciones_pendientes": len(filas),
                "compradores_afectados": len(cliente_ids),
                "por_estado_direcciones": {s: por_estado_direcciones[s] for s in sorted(ESTADOS_COLA - {"todos"})},
                "por_estado_pedidos": {s: por_estado_pedidos[s] for s in sorted(ESTADOS_COLA - {"todos"})},
            },
            "orden": "pedidos_afectados_desc_balones_afectados_desc_direccion_id_asc",
            "snapshot_garantizado": False,
            "avisos": [
                "No incluye pedidos con H3 en celdas ocultas por privacidad.",
                "El motivo técnico no prueba que el texto sea un alias ni autoriza corregir producción.",
                "La fuente GEO temporal puede vencer; comparar solo cortes con la misma fuente y fecha de generación.",
            ],
        },
        "offset": offset, "limite": limit,
        "filas": seleccionadas[offset:offset + limit],
    }
