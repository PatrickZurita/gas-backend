"""Comparación descriptiva de dos semanas operativas completas del corte BI."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from app.core.time import fecha_hoy_lima
from app.services.bi import construir_corte


def comparar_semanas(
    db: Session, *, peso_balon_kg: Literal[10, 45] | None = None,
    hoy: date | None = None,
) -> dict:
    hoy = hoy or fecha_hoy_lima()
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    reciente_desde = lunes_actual - timedelta(days=7)
    previa_desde = reciente_desde - timedelta(days=7)
    reciente = construir_corte(
        db, desde=reciente_desde, hasta=lunes_actual - timedelta(days=1),
        peso_balon_kg=peso_balon_kg,
    )
    previa = construir_corte(
        db, desde=previa_desde, hasta=reciente_desde - timedelta(days=1),
        peso_balon_kg=peso_balon_kg,
    )

    def resumen(corte: dict) -> dict:
        datos = corte["resumen"]
        return {
            "desde": corte["filtros"]["desde"],
            "hasta": corte["filtros"]["hasta"],
            "pedidos_activos": datos["pedidos_activos"],
            "balones_vendidos": datos["balones_vendidos"],
            "balones_10kg": datos["balones_10kg"],
            "balones_45kg": datos["balones_45kg"],
            "clientes_compradores": datos["clientes_compradores"],
            "pedidos_con_monto_valido": datos["pedidos_con_monto_valido"],
            "vendido_centavos": datos["vendido_centavos"],
            "cobertura_monetaria": {
                "pedidos_monto_total_legacy": corte["cobertura"]["pedidos_monto_total_legacy"],
                "pedidos_pendiente_legacy": corte["cobertura"]["pedidos_pendiente_legacy"],
                "pedidos_sin_monto_valido": corte["cobertura"]["pedidos_sin_monto_valido"],
                "pedidos_monetarios_anomalos": corte["cobertura"]["pedidos_monetarios_anomalos"],
            },
        }

    actual = resumen(reciente)
    anterior = resumen(previa)
    diferencia = actual["balones_vendidos"] - anterior["balones_vendidos"]
    porcentaje = (
        round(100 * diferencia / anterior["balones_vendidos"], 1)
        if anterior["balones_vendidos"] else None
    )
    importes_comparables = all(
        corte["resumen"]["pedidos_activos"] > 0
        and corte["resumen"]["pedidos_activos"]
        == corte["resumen"]["pedidos_con_monto_valido"]
        for corte in (reciente, previa)
    )
    if actual["balones_vendidos"] > anterior["balones_vendidos"]:
        lectura = "Se registraron más balones que en la semana anterior."
    elif actual["balones_vendidos"] < anterior["balones_vendidos"]:
        lectura = "Se registraron menos balones que en la semana anterior."
    else:
        lectura = "Se registró la misma cantidad de balones en ambas semanas."
    if not actual["pedidos_activos"] or not anterior["pedidos_activos"]:
        lectura += " Un cero indica ausencia de pedidos activos registrados, no demanda cero."
    return {
        "version_definiciones": reciente["version_definiciones"],
        "generado_en": reciente["generado_en"],
        "zona_horaria": reciente["zona_horaria"],
        "fecha_base": reciente["fecha_base"],
        "fuente": reciente["fuente"],
        "peso_balon_kg": "todos" if peso_balon_kg is None else peso_balon_kg,
        "semana_reciente": actual,
        "semana_anterior": anterior,
        "diferencia_balones": diferencia,
        "variacion_balones_pct": porcentaje,
        "importes_comparables": importes_comparables,
        "lectura": lectura,
        "limite": (
            "Compara ventas registradas por día operativo; no mide demanda total, "
            "margen, caja del periodo ni causa del cambio."
        ),
    }
