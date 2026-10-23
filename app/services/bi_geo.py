"""Read-only GEO adapter over the exact order population used by BI.

The DB stores no address or customer payload in the public response. Expired
or text-mismatched provider results are treated as unlocated.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Iterable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.time import LIMA_TZ
from app.infrastructure.repositories.bi import PedidoBI
from app.models.models import Direccion, ResultadoGeoTemporal
from app.services.bi import _centavos
from app.services.bi_geo_aggregate import PedidoGeo, agregar_geo


def fingerprint_direccion(texto_original: str) -> str:
    """Stable text version; caller must invalidate on approved correction."""
    normalizado = " ".join(texto_original.casefold().split())
    return sha256(normalizado.encode("utf-8")).hexdigest()


def fuente_geo_disponible(db: Session) -> bool:
    """Allow old deployments to report unavailable instead of querying a missing table."""
    return bool(db.execute(text(
        "SELECT coalesce(has_table_privilege(current_user, "
        "to_regclass('public.resultados_geo_temporales'), 'SELECT'), false)"
    )).scalar_one())


def filas_geo_del_corte(
    db: Session, pedidos: Iterable[PedidoBI]
) -> tuple[list[PedidoGeo], datetime | None]:
    """Resolve GEO rows for aggregate and nominal review in one DB snapshot."""
    base = list(pedidos)
    direccion_ids = {p.direccion_id for p in base}
    if not direccion_ids:
        return [], None

    stmt = (
        select(Direccion.id, Direccion.texto_original, ResultadoGeoTemporal)
        .outerjoin(ResultadoGeoTemporal, ResultadoGeoTemporal.direccion_id == Direccion.id)
        .where(Direccion.id.in_(direccion_ids))
    )
    resultados = {
        direccion_id: (texto_original, resultado)
        for direccion_id, texto_original, resultado in db.execute(stmt).all()
    }
    if set(resultados) != direccion_ids:
        raise RuntimeError("La población geo no coincide con las direcciones del corte BI")

    ahora = datetime.now(LIMA_TZ)
    filas: list[PedidoGeo] = []
    for pedido in base:
        texto_original, resultado = resultados[pedido.direccion_id]
        vigente = (
            resultado is not None
            and resultado.expira_en > ahora
            and resultado.texto_fingerprint == fingerprint_direccion(texto_original)
        )
        estado = resultado.estado if vigente else "NO_GEOCODIFICADO"
        precision = resultado.precision if vigente else None
        h3_res9 = resultado.h3_res9 if vigente else None
        motivo = None
        if resultado is None:
            motivo = "SIN_RESULTADO_TABLA"
        elif resultado.expira_en <= ahora:
            motivo = "RESULTADO_VENCIDO"
        elif resultado.texto_fingerprint != fingerprint_direccion(texto_original):
            motivo = "TEXTO_CAMBIADO"
        elif estado != "OK":
            motivo = estado
        total, _ = _centavos(pedido.monto_total_centavos, pedido.total_soles)
        pendiente, _ = _centavos(pedido.monto_pendiente_centavos, pedido.saldo_pendiente)
        venta_centavos = (
            total if total is not None and pendiente is not None
            and total >= 0 and 0 <= pendiente <= total else None
        )
        filas.append(PedidoGeo(
            pedido_id=str(pedido.pedido_id),
            cliente_id=str(pedido.cliente_id),
            cantidad_balones=pedido.cantidad_balones,
            venta_centavos=venta_centavos,
            geocoding_estado=estado,
            geocoding_precision=precision,
            h3_res9=h3_res9,
            motivo_tecnico=motivo,
        ))

    actualizado = max(
        (r.geocodificado_en for _, r in resultados.values() if r is not None
         and r.expira_en > ahora), default=None,
    )
    return filas, actualizado


def agregar_geo_del_corte(db: Session, pedidos: Iterable[PedidoBI]) -> dict:
    """Load only geo results for the same order rows and transaction snapshot."""
    base = list(pedidos)
    filas, actualizado = filas_geo_del_corte(db, base)
    agregado = agregar_geo(filas, n_pedidos_corte_bi=len(base))
    agregado["balones_base"] = sum(p.cantidad_balones for p in base)
    agregado["venta_centavos_base"] = sum(
        p.venta_centavos for p in filas if p.venta_centavos is not None
    )
    agregado["pedidos_con_monto_valido_base"] = sum(
        p.venta_centavos is not None for p in filas
    )
    agregado["estado"] = "DISPONIBLE"
    agregado["actualizado_geo_hasta"] = actualizado
    if agregado["actualizado_geo_hasta"] is not None:
        agregado["actualizado_geo_hasta"] = agregado["actualizado_geo_hasta"].isoformat()
    return agregado
