"""Representaciones locales del corte BI agregado, sin acceso a datos ni rutas HTTP."""

from __future__ import annotations

import json

from app.services.bi import CorteBI

_MEDIDAS = (
    "pedidos_activos",
    "balones_vendidos",
    "balones_10kg",
    "balones_45kg",
    "vendido_centavos",
    "pendiente_centavos",
    "cobrado_calculado_centavos",
    "pedidos_con_monto_valido",
)
_RESUMEN_CLIENTES = (
    "clientes_compradores",
    "primera_compra_observada_en_periodo",
    "compradores_que_volvieron_en_periodo",
)
_COBERTURA = (
    "pedidos_monto_total_legacy",
    "pedidos_pendiente_legacy",
    "pedidos_sin_monto_valido",
    "pedidos_monetarios_anomalos",
)


def proyectar_corte_agregado(corte: CorteBI) -> CorteBI:
    """Copia solo campos agregados del corte para JSON y Excel.

    Esta proyección no vuelve a consultar PostgreSQL ni recalcula métricas. La
    lista explícita impide que campos nominales añadidos por error se filtren.
    """
    actividad = corte["actividad_clientes"]
    return {
        "version_definiciones": corte["version_definiciones"],
        "generado_en": corte["generado_en"],
        "zona_horaria": corte["zona_horaria"],
        "fuente": corte["fuente"],
        "fecha_base": corte["fecha_base"],
        "filtros": {
            campo: corte["filtros"][campo]
            for campo in ("desde", "hasta", "peso_balon_kg", "estado")
        },
        "n_pedidos_base": corte["n_pedidos_base"],
        "resumen": {
            campo: corte["resumen"][campo]
            for campo in (*_MEDIDAS, *_RESUMEN_CLIENTES)
        },
        "serie_diaria": [
            {
                campo: fila[campo]
                for campo in ("fecha", "peso_balon_kg", *_MEDIDAS)
            }
            for fila in corte["serie_diaria"]
        ],
        "actividad_clientes": {
            "meses": [
                {campo: fila[campo] for campo in ("mes", "clientes_compradores")}
                for fila in actividad["meses"]
            ],
            "clientes_con_cadencia_explorable": actividad["clientes_con_cadencia_explorable"],
            "intervalos_observados": actividad["intervalos_observados"],
            "mediana_intervalo_dias": actividad["mediana_intervalo_dias"],
            "corte_cohortes_hasta": actividad["corte_cohortes_hasta"],
            "cohortes_retorno": [
                {
                    campo: cohorte[campo]
                    for campo in (
                        "ventana_dias", "elegibles", "retornaron", "censurados", "porcentaje"
                    )
                }
                for cohorte in actividad["cohortes_retorno"]
            ],
        },
        "cobertura": {campo: corte["cobertura"][campo] for campo in _COBERTURA},
        "avisos": list(corte["avisos"]),
    }


def serializar_corte_json(corte: CorteBI) -> bytes:
    """Serializa la misma proyección agregada que consume el exportador Excel."""
    return json.dumps(
        proyectar_corte_agregado(corte), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
