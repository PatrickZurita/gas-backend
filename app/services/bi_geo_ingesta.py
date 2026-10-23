"""Private transaction-scoped ingest primitive for reviewed, expiring GEO results.

This module provides no HTTP route or automatic job. A separately authorized
operator flow must validate provider terms, district/bounds and precision,
then call this function with a writable session and commit explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.models import Direccion, ResultadoGeoTemporal
from app.services.bi_geo import fingerprint_direccion
from app.services.bi_geo_aggregate import ESTADOS, H3_HEX, PRECISIONES


@dataclass(frozen=True)
class ResultadoGeoRevisado:
    direccion_id: int
    estado: str
    precision: str | None
    h3_res9: str | None
    proveedor: str
    geocodificado_en: datetime
    expira_en: datetime


def preparar_ingesta_geo(db: Session, dato: ResultadoGeoRevisado) -> None:
    """Stage one result; caller owns approval, transaction and eventual commit."""
    direccion = db.get(Direccion, dato.direccion_id)
    if direccion is None:
        raise ValueError("Dirección no encontrada")
    if dato.estado not in ESTADOS - {"NO_GEOCODIFICADO"}:
        raise ValueError("Estado geo inválido para ingesta")
    if dato.estado == "OK":
        if dato.precision not in PRECISIONES:
            raise ValueError("Resultado OK sin precisión")
    elif dato.precision is not None or dato.h3_res9 is not None:
        raise ValueError("Resultado no OK con precisión o H3")
    if dato.h3_res9 is not None and (
        not H3_HEX.fullmatch(dato.h3_res9)
        or (int(dato.h3_res9, 16) >> 52) & 15 != 9
    ):
        raise ValueError("H3 no canónico o sin resolución 9")
    if dato.proveedor not in {"GOOGLE", "MANUAL"}:
        raise ValueError("Proveedor geo no aprobado")
    if dato.geocodificado_en.tzinfo is None or dato.expira_en.tzinfo is None:
        raise ValueError("Timestamps geo deben tener zona horaria")
    inicio = dato.geocodificado_en.astimezone(timezone.utc)
    fin = dato.expira_en.astimezone(timezone.utc)
    if not inicio < fin <= inicio + timedelta(days=29):
        raise ValueError("Vencimiento geo fuera de límite")
    if fin <= datetime.now(timezone.utc):
        raise ValueError("Resultado geo ya vencido")

    db.merge(ResultadoGeoTemporal(
        direccion_id=dato.direccion_id,
        texto_fingerprint=fingerprint_direccion(direccion.texto_original),
        estado=dato.estado,
        precision=dato.precision,
        h3_res9=dato.h3_res9,
        proveedor=dato.proveedor,
        geocodificado_en=dato.geocodificado_en,
        expira_en=dato.expira_en,
    ))
