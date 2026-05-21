"""Helpers de tiempo para GAS.

Las fechas operativas (fecha_entrega, jornada de stock) deben estar en zona
horaria America/Lima (UTC-5) para reflejar el dia laboral del operador. Los
timestamps tecnicos (created_at, updated_at) siguen siendo UTC.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

LIMA_TZ = ZoneInfo("America/Lima")


def fecha_hoy_lima() -> date:
    """Fecha 'hoy' en zona horaria America/Lima (UTC-5)."""
    return datetime.now(LIMA_TZ).date()
