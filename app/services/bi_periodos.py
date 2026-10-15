"""Comparaciones descriptivas de periodos calendario completos en Lima."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from app.core.time import fecha_hoy_lima
from app.services.bi import construir_corte

Granularidad = Literal["semana", "quincena", "mes"]


def _mes_anterior(mes: date) -> date:
    return date(mes.year - 1, 12, 1) if mes.month == 1 else date(mes.year, mes.month - 1, 1)


def _limites(hoy: date, granularidad: Granularidad) -> tuple[date, date, date, date]:
    if granularidad == "semana":
        inicio_actual = hoy - timedelta(days=hoy.weekday())
        inicio_reciente = inicio_actual - timedelta(days=7)
        inicio_anterior = inicio_reciente - timedelta(days=7)
        return inicio_anterior, inicio_reciente - timedelta(days=1), inicio_reciente, inicio_actual - timedelta(days=1)
    if granularidad == "mes":
        inicio_actual = date(hoy.year, hoy.month, 1)
        inicio_reciente = _mes_anterior(inicio_actual)
        inicio_anterior = _mes_anterior(inicio_reciente)
        return inicio_anterior, inicio_reciente - timedelta(days=1), inicio_reciente, inicio_actual - timedelta(days=1)
    if granularidad == "quincena":
        inicio_mes = date(hoy.year, hoy.month, 1)
        if hoy.day >= 16:
            return _mes_anterior(inicio_mes).replace(day=16), inicio_mes - timedelta(days=1), inicio_mes, inicio_mes.replace(day=15)
        inicio_reciente = _mes_anterior(inicio_mes).replace(day=16)
        inicio_anterior = _mes_anterior(inicio_mes)
        return inicio_anterior, inicio_anterior.replace(day=15), inicio_reciente, inicio_mes - timedelta(days=1)
    raise ValueError("Granularidad BI inválida")


def comparar_periodos(
    db: Session, *, granularidad: Granularidad,
    peso_balon_kg: Literal[10, 45] | None = None,
    hoy: date | None = None,
) -> dict:
    hoy = hoy or fecha_hoy_lima()
    anterior_desde, anterior_hasta, reciente_desde, reciente_hasta = _limites(hoy, granularidad)
    anterior = construir_corte(
        db, desde=anterior_desde, hasta=anterior_hasta,
        peso_balon_kg=peso_balon_kg,
    )
    reciente = construir_corte(
        db, desde=reciente_desde, hasta=reciente_hasta,
        peso_balon_kg=peso_balon_kg,
    )

    def proyectar(corte: dict) -> dict:
        resumen = corte["resumen"]
        return {
            "desde": corte["filtros"]["desde"],
            "hasta": corte["filtros"]["hasta"],
            "dias_calendario": (
                date.fromisoformat(corte["filtros"]["hasta"])
                - date.fromisoformat(corte["filtros"]["desde"])
            ).days + 1,
            "pedidos_activos": resumen["pedidos_activos"],
            "balones_vendidos": resumen["balones_vendidos"],
            "balones_10kg": resumen["balones_10kg"],
            "balones_45kg": resumen["balones_45kg"],
            "clientes_compradores": resumen["clientes_compradores"],
            "pedidos_con_monto_valido": resumen["pedidos_con_monto_valido"],
            "vendido_centavos": resumen["vendido_centavos"],
            "cobertura_monetaria": corte["cobertura"],
        }

    previo, actual = proyectar(anterior), proyectar(reciente)
    diferencia = actual["balones_vendidos"] - previo["balones_vendidos"]
    importes_comparables = all(
        bloque["pedidos_activos"] > 0
        and bloque["pedidos_activos"] == bloque["pedidos_con_monto_valido"]
        for bloque in (previo, actual)
    )
    return {
        "version_definiciones": reciente["version_definiciones"],
        "generado_en": reciente["generado_en"],
        "zona_horaria": reciente["zona_horaria"],
        "fecha_base": reciente["fecha_base"],
        "fuente": reciente["fuente"],
        "granularidad": granularidad,
        "peso_balon_kg": "todos" if peso_balon_kg is None else peso_balon_kg,
        "periodo_reciente": actual,
        "periodo_anterior": previo,
        "diferencia_balones": diferencia,
        "variacion_balones_pct": (
            round(100 * diferencia / previo["balones_vendidos"], 1)
            if previo["balones_vendidos"] else None
        ),
        "importes_comparables": importes_comparables,
        "limite": (
            "Ventas registradas por fecha_entrega; los ceros no prueban demanda cero. "
            "Quincenas y meses pueden tener distinta duración. "
            "No mide margen, caja del periodo ni causa del cambio."
        ),
    }
