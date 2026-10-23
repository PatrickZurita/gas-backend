"""Local private Google cache adapter; never emits raw addresses or points.

This is optional for a local BI server. It reads a private, expiring JSON cache
created outside Git; it does not call Google or write to production.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.repositories.bi import PedidoBI
from app.models.models import Direccion
from app.services.bi import _centavos
from app.services.bi_geo_aggregate import PedidoGeo, agregar_geo

_WORKSPACE = Path(__file__).resolve().parents[3]
_CACHE = _WORKSPACE / "analytics-local/private/google-geocoding-temporal.json"
_BOUNDARY = _WORKSPACE / "docs/analytics/geo/la-molina-inei-2017.geojson"


def _normalizar(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _dentro_anillo(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > lat) != (y2 > lat):
            crossing = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < crossing:
                inside = not inside
        previous = current
    return inside


def _dentro_poligono(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    return _dentro_anillo(lon, lat, rings[0]) and not any(
        _dentro_anillo(lon, lat, hole) for hole in rings[1:]
    )


def cache_geo_disponible() -> bool:
    return _CACHE.is_file() and _BOUNDARY.is_file()


def filas_geo_cache_temporal(
    db: Session, pedidos: list[PedidoBI]
) -> tuple[list[PedidoGeo], list[datetime], str | None]:
    """Resolve GEO rows once for aggregate and nominal review in the same snapshot."""
    try:
        import h3
    except ImportError:
        raise RuntimeError("H3 no instalado") from None
    if not cache_geo_disponible():
        raise RuntimeError("Cache GEO local no disponible")
    if _CACHE.is_symlink() or _CACHE.stat().st_mode & 0o077:
        raise RuntimeError("Cache GEO sin permisos privados")
    cache = json.loads(_CACHE.read_text(encoding="utf-8"))
    resultados = cache.get("resultados")
    if not isinstance(resultados, dict):
        raise RuntimeError("Cache GEO incompatible")
    boundary = json.loads(_BOUNDARY.read_text(encoding="utf-8"))["features"][0]["geometry"]
    if boundary["type"] != "Polygon":
        raise RuntimeError("Referencia GEO incompatible")
    rings = boundary["coordinates"]
    now = datetime.now(timezone.utc)

    ids = {p.direccion_id for p in pedidos}
    textos = dict(db.execute(
        select(Direccion.id, Direccion.texto_original).where(Direccion.id.in_(ids))
    ).all()) if ids else {}
    if set(textos) != ids:
        raise RuntimeError("Direcciones GEO no coinciden con corte BI")

    filas: list[PedidoGeo] = []
    consultados: list[datetime] = []
    for pedido in pedidos:
        item = resultados.get(_normalizar(textos[pedido.direccion_id]))
        estado, precision, cell = "NO_GEOCODIFICADO", None, None
        motivo = "SIN_COINCIDENCIA_CACHE"
        if isinstance(item, dict):
            try:
                consultado = datetime.fromisoformat(item["consultado_en"])
                expira = datetime.fromisoformat(item["expira_en"])
                if consultado.tzinfo is None or expira.tzinfo is None:
                    raise ValueError("Cache GEO sin zona horaria")
                consultado = consultado.astimezone(timezone.utc)
                expira = expira.astimezone(timezone.utc)
                vigente = (
                    consultado <= now < expira <= consultado + timedelta(days=29)
                )
            except (KeyError, TypeError, ValueError):
                vigente = False
            if vigente:
                consultados.append(consultado)
                original_estado = item.get("estado")
                if original_estado == "OK_PENDIENTE_ZONA":
                    lat, lon = item.get("latitud_temporal"), item.get("longitud_temporal")
                    if (isinstance(lat, (int, float)) and not isinstance(lat, bool)
                        and isinstance(lon, (int, float)) and not isinstance(lon, bool)
                        and -90 <= lat <= 90 and -180 <= lon <= 180
                        and item.get("precision") in {"HIGH", "MEDIUM"}):
                        if _dentro_poligono(lon, lat, rings):
                            estado, precision = "OK", item["precision"]
                            cell = h3.latlng_to_cell(lat, lon, 9)
                            motivo = None
                        else:
                            estado = "RECHAZADO_BOUNDS"
                            motivo = "FUERA_REFERENCIA_ESPACIAL"
                    else:
                        estado = "RECHAZADO_PRECISION"
                        motivo = "COORDENADA_O_PRECISION_INSUFICIENTE"
                elif original_estado in {"SIN_RESULTADO", "RECHAZADO_BOUNDS", "RECHAZADO_PRECISION"}:
                    estado = original_estado
                    motivo = original_estado
                elif original_estado == "PARCIAL":
                    estado = "RECHAZADO_PRECISION"
                    motivo = "RESULTADO_PARCIAL"
                else:
                    motivo = "ESTADO_CACHE_NO_ADMITIDO"
            else:
                motivo = "CACHE_VENCIDO_O_INVALIDO"

        total, _ = _centavos(pedido.monto_total_centavos, pedido.total_soles)
        pendiente, _ = _centavos(pedido.monto_pendiente_centavos, pedido.saldo_pendiente)
        venta = total if total is not None and pendiente is not None and total >= 0 and 0 <= pendiente <= total else None
        filas.append(PedidoGeo(
            pedido_id=str(pedido.pedido_id), cliente_id=str(pedido.cliente_id),
            cantidad_balones=pedido.cantidad_balones, venta_centavos=venta,
            geocoding_estado=estado, geocoding_precision=precision, h3_res9=cell,
            motivo_tecnico=motivo,
        ))

    return filas, consultados, cache.get("fuente_generado_en")


def agregar_geo_cache_temporal(db: Session, pedidos: list[PedidoBI]) -> dict:
    """Aggregate current order rows against only live, zone-checked cache entries."""
    import h3

    filas, consultados, fuente_generado_en = filas_geo_cache_temporal(db, pedidos)

    geo = agregar_geo(filas, n_pedidos_corte_bi=len(pedidos))
    for cell in geo["celdas_h3_res9"]:
        cell["contorno"] = [
            {"lat": lat, "lng": lon} for lat, lon in h3.cell_to_boundary(cell["clave"])
        ]
    geo["estado"] = "DISPONIBLE"
    geo["fuente_geo"] = "cache_local_google_temporal"
    geo["fuente_generado_en"] = fuente_generado_en
    geo["actualizado_geo_hasta"] = max(consultados).isoformat() if consultados else None
    geo["referencia_espacial"] = "Límite distrital INEI 2017; no zona operativa aprobada"
    geo["balones_base"] = sum(p.cantidad_balones for p in pedidos)
    geo["venta_centavos_base"] = sum(p.venta_centavos for p in filas if p.venta_centavos is not None)
    geo["pedidos_con_monto_valido_base"] = sum(p.venta_centavos is not None for p in filas)
    geo["avisos"].append("Cobertura GEO temporal; resultado de Google vence y la zona de reparto aún no está validada por el dueño.")
    return geo
