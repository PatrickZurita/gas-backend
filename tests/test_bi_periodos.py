"""Comparaciones y continuidad con fechas y ventas sintéticas."""

from datetime import date

import pytest

from app.services import bi_periodos, bi_semanal


@pytest.mark.parametrize("hoy,granularidad,esperado", [
    (date(2026, 10, 15), "semana", ("2026-09-28", "2026-10-04", "2026-10-05", "2026-10-11")),
    (date(2026, 10, 15), "quincena", ("2026-09-01", "2026-09-15", "2026-09-16", "2026-09-30")),
    (date(2026, 10, 16), "quincena", ("2026-09-16", "2026-09-30", "2026-10-01", "2026-10-15")),
    (date(2027, 1, 1), "mes", ("2026-11-01", "2026-11-30", "2026-12-01", "2026-12-31")),
])
def test_limites_periodos_cerrados(hoy, granularidad, esperado):
    assert tuple(d.isoformat() for d in bi_periodos._limites(hoy, granularidad)) == esperado


def test_comparacion_periodos_conserva_denominadores_y_cobertura(monkeypatch):
    llamadas = []

    def corte(_db, *, desde, hasta, peso_balon_kg):
        llamadas.append((desde, hasta, peso_balon_kg))
        reciente = desde == date(2026, 10, 5)
        pedidos = 2 if reciente else 0
        return {
            "version_definiciones": "bi-v1.1",
            "generado_en": "2026-10-15T10:00:00-05:00",
            "zona_horaria": "America/Lima", "fecha_base": "fecha_entrega_registrada",
            "fuente": "PostgreSQL/pedidos",
            "filtros": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
            "resumen": {"pedidos_activos": pedidos, "balones_vendidos": pedidos,
                        "balones_10kg": pedidos, "balones_45kg": 0,
                        "clientes_compradores": 1 if reciente else 0,
                        "pedidos_con_monto_valido": pedidos,
                        "vendido_centavos": pedidos * 7000},
            "cobertura": {"pedidos_sin_monto_valido": 0},
        }

    monkeypatch.setattr(bi_periodos, "construir_corte", corte)
    respuesta = bi_periodos.comparar_periodos(
        object(), granularidad="semana", peso_balon_kg=10,
        hoy=date(2026, 10, 15),
    )
    assert len(llamadas) == 2
    assert llamadas[0] == (date(2026, 9, 28), date(2026, 10, 4), 10)
    assert llamadas[1] == (date(2026, 10, 5), date(2026, 10, 11), 10)
    assert respuesta["periodo_reciente"]["clientes_compradores"] == 1
    assert respuesta["periodo_anterior"]["dias_calendario"] == 7
    assert respuesta["diferencia_balones"] == 2
    assert respuesta["variacion_balones_pct"] is None
    assert respuesta["importes_comparables"] is False


def test_comparacion_semanal_bi09_usa_semanas_cerradas_y_compradores(monkeypatch):
    llamadas = []

    def corte(_db, *, desde, hasta, peso_balon_kg):
        llamadas.append((desde, hasta, peso_balon_kg))
        return {
            "version_definiciones": "bi-v1.1", "generado_en": "2026-10-15T10:00:00-05:00",
            "zona_horaria": "America/Lima", "fecha_base": "fecha_entrega_registrada",
            "fuente": "PostgreSQL/pedidos",
            "filtros": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
            "resumen": {
                "pedidos_activos": 2, "balones_vendidos": 3,
                "balones_10kg": 3, "balones_45kg": 0,
                "clientes_compradores": 1, "pedidos_con_monto_valido": 2,
                "vendido_centavos": 14000,
            },
            "cobertura": {"pedidos_monto_total_legacy": 0,
                          "pedidos_pendiente_legacy": 0,
                          "pedidos_sin_monto_valido": 0,
                          "pedidos_monetarios_anomalos": 0},
        }

    monkeypatch.setattr(bi_semanal, "construir_corte", corte)
    respuesta = bi_semanal.comparar_semanas(
        object(), peso_balon_kg=10, hoy=date(2026, 10, 15),
    )
    assert llamadas == [
        (date(2026, 10, 5), date(2026, 10, 11), 10),
        (date(2026, 9, 28), date(2026, 10, 4), 10),
    ]
    assert respuesta["semana_reciente"]["clientes_compradores"] == 1
    assert respuesta["semana_anterior"]["pedidos_activos"] == 2
    assert respuesta["variacion_balones_pct"] == 0.0
