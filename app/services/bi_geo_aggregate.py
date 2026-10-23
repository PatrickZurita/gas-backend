"""Agregación geográfica pura para GAS BI; sin I/O, geocoding ni datos nominales de salida.

Recibe pedidos ya filtrados por el mismo corte BI y resultados geográficos
previamente revisados. Es una referencia local para integrar en gas-backend;
no consulta PostgreSQL ni valida geometría H3 por sí misma.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re
from typing import Iterable


ESTADOS = frozenset(
    {"OK", "SIN_RESULTADO", "RECHAZADO_BOUNDS", "RECHAZADO_PRECISION", "NO_GEOCODIFICADO", "PENDIENTE_DUENO"}
)
PRECISIONES = frozenset({"HIGH", "MEDIUM", "LOW"})
PRECISIONES_PUBLICABLES = frozenset({"HIGH", "MEDIUM"})
H3_HEX = re.compile(r"[0-9a-f]{15}\Z")


@dataclass(frozen=True)
class PedidoGeo:
    """Identificadores internos para deduplicar; nunca se devuelven en la salida."""

    pedido_id: str
    cliente_id: str
    cantidad_balones: int
    venta_centavos: int | None
    geocoding_estado: str
    geocoding_precision: str | None = None
    h3_res9: str | None = None
    zona_validada_id: str | None = None
    motivo_tecnico: str | None = None


def _porcentaje(numerador: int, denominador: int) -> float | None:
    return round(100 * numerador / denominador, 2) if denominador else None


def _grupo(pedidos: list[PedidoGeo], clave: str) -> dict:
    importes = [p.venta_centavos for p in pedidos if p.venta_centavos is not None]
    return {
        "clave": clave,
        "pedidos": len(pedidos),
        "balones": sum(p.cantidad_balones for p in pedidos),
        "clientes": len({p.cliente_id for p in pedidos}),
        "pedidos_con_monto": len(importes),
        "pedidos_sin_monto": len(pedidos) - len(importes),
        "venta_centavos": sum(importes) if importes else None,
    }


def agregar_geo(
    pedidos_base: Iterable[PedidoGeo],
    *,
    n_pedidos_corte_bi: int,
    zonas_validadas: frozenset[str] = frozenset(),
    minimo_clientes_por_grupo: int = 5,
) -> dict:
    """Resume cobertura y grupos H3/zona del MISMO corte BI.

    El llamador debe aplicar `ACTIVO`, fecha_entrega, peso y normalización
    monetaria del núcleo BI; validar bounds, precisión y resolución H3; y
    aportar solo zonas cuya geometría fue aceptada por el dueño. No se emiten
    coordenadas, direcciones, clientes ni pedidos individuales.
    """
    if minimo_clientes_por_grupo < 2:
        raise ValueError("minimo_clientes_por_grupo debe ser al menos 2")
    if n_pedidos_corte_bi < 0:
        raise ValueError("n_pedidos_corte_bi no puede ser negativo")

    pedidos = list(pedidos_base)
    if len(pedidos) != n_pedidos_corte_bi:
        raise ValueError("La población geo no coincide con el corte BI")
    if len({p.pedido_id for p in pedidos}) != len(pedidos):
        raise ValueError("La población geo contiene pedidos duplicados")

    for pedido in pedidos:
        if not pedido.pedido_id or not pedido.cliente_id:
            raise ValueError("Cada pedido requiere claves internas de pedido y cliente")
        if pedido.cantidad_balones < 0 or (
            pedido.venta_centavos is not None and pedido.venta_centavos < 0
        ):
            raise ValueError("Unidades e importes normalizados no pueden ser negativos")
        if pedido.geocoding_estado not in ESTADOS:
            raise ValueError("Estado de geocoding desconocido")
        if pedido.geocoding_estado == "OK":
            if pedido.geocoding_precision not in PRECISIONES:
                raise ValueError("Geocoding OK requiere precisión conocida")
        elif pedido.geocoding_precision is not None:
            raise ValueError("Un geocoding rechazado no puede tener precisión aceptada")
        if pedido.h3_res9 is not None:
            if not H3_HEX.fullmatch(pedido.h3_res9) or (
                (int(pedido.h3_res9, 16) >> 52) & 15
            ) != 9:
                raise ValueError("H3 debe tener formato canónico y resolución 9")

    estados = Counter(p.geocoding_estado for p in pedidos)
    precisiones = Counter(
        p.geocoding_precision for p in pedidos if p.geocoding_estado == "OK"
    )
    ubicables = [
        p for p in pedidos
        if p.geocoding_estado == "OK"
        and p.geocoding_precision in PRECISIONES_PUBLICABLES
    ]
    con_h3 = [p for p in ubicables if p.h3_res9]
    en_zona = [p for p in ubicables if p.zona_validada_id in zonas_validadas]

    def resumir_grupos(filas: list[PedidoGeo], atributo: str) -> tuple[list[dict], int]:
        agrupados: dict[str, list[PedidoGeo]] = defaultdict(list)
        for fila in filas:
            agrupados[getattr(fila, atributo)].append(fila)
        visibles = []
        suprimidos = 0
        for clave, miembros in sorted(agrupados.items()):
            if len({p.cliente_id for p in miembros}) < minimo_clientes_por_grupo:
                suprimidos += len(miembros)
            else:
                visibles.append(_grupo(miembros, clave))
        return visibles, suprimidos

    celdas, pedidos_celdas_suprimidas = resumir_grupos(con_h3, "h3_res9")
    zonas, pedidos_zonas_suprimidas = resumir_grupos(en_zona, "zona_validada_id")
    base = len(pedidos)
    return {
        "version_definicion_geo": "geo-agregado-v1",
        "n_pedidos_base": base,
        "cobertura": {
            "pedidos_geocodificados": estados["OK"],
            "pedidos_ubicables_precision_high_medium": len(ubicables),
            "pedidos_con_h3_res9": len(con_h3),
            "pedidos_en_zona_validada": len(en_zona),
            "pct_geocodificados": _porcentaje(estados["OK"], base),
            "pct_ubicables": _porcentaje(len(ubicables), base),
            "pct_con_h3_res9": _porcentaje(len(con_h3), base),
            "pct_en_zona_validada": _porcentaje(len(en_zona), base),
            "estados": {estado: estados[estado] for estado in sorted(ESTADOS)},
            "precision_aceptada": {
                precision: precisiones[precision] for precision in sorted(PRECISIONES)
            },
        },
        "celdas_h3_res9": celdas,
        "zonas_validadas": zonas,
        "privacidad": {
            "minimo_clientes_por_grupo": minimo_clientes_por_grupo,
            "pedidos_en_celdas_suprimidas": pedidos_celdas_suprimidas,
            "pedidos_en_zonas_suprimidas": pedidos_zonas_suprimidas,
        },
        "avisos": [
            "Las celdas sin pedidos registrados no prueban demanda cero.",
            "H3 es exploratorio y no equivale a una zona operativa validada.",
            "La venta agregada excluye pedidos sin monto válido; consulte la cobertura monetaria.",
        ],
    }
