"""Listados BI nominales internos para un canal privado futuro.

No se registran alias, teléfonos ni direcciones en logs. Ninguna función
autentica al solicitante: el control de acceso es requisito del adaptador que
algún día exponga estos datos. Por ahora solo se permite uso local autorizado.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.storage import is_dynamodb_enabled
from app.core.time import LIMA_TZ, fecha_hoy_lima
from app.infrastructure.repositories import bi_nominal as repo
from app.services.bi import RANGO_MAXIMO_DIAS, VERSION_DEFINICIONES, _centavos

MAX_PAGINA = 200
MAX_EXPORT_FILAS = 5000
VERSION_NOMINAL = "bi-nominal-v1"


def _db_pg(db: Session | None) -> Session:
    if db is None or is_dynamodb_enabled():
        raise RuntimeError("Los listados BI nominales requieren PostgreSQL")
    return db


def _validar_pagina(offset: int, limit: int) -> None:
    if not 0 <= offset <= 1_000_000 or not 1 <= limit <= MAX_PAGINA:
        raise ValueError("Paginación fuera de límites")


def _validar_filtros(desde: date, hasta: date, peso_balon_kg: int | None) -> None:
    if desde > hasta or hasta > fecha_hoy_lima():
        raise ValueError("Periodo BI inválido")
    if (hasta - desde).days + 1 > RANGO_MAXIMO_DIAS:
        raise ValueError("Periodo BI excede el máximo permitido")
    if peso_balon_kg not in (None, 10, 45):
        raise ValueError("peso_balon_kg debe ser 10, 45 o todos")


def _meta(poblacion: str, *, total: int, filtros: dict[str, Any]) -> dict[str, Any]:
    return {
        "version_definiciones": VERSION_DEFINICIONES,
        "version_nominal": VERSION_NOMINAL,
        "generado_en": datetime.now(LIMA_TZ).isoformat(),
        "zona_horaria": "America/Lima",
        "fuente": "PostgreSQL",
        "fecha_base": "fecha_entrega_registrada" if poblacion != "clientes_registrados" else None,
        "poblacion": poblacion,
        "filtros": filtros,
        "total_registros": total,
        "limite_exportacion": MAX_EXPORT_FILAS,
        "snapshot_garantizado": False,
        "avisos": [
            "Datos personales: entregar solo a usuario autorizado; no guardar en Git ni logs.",
            "Las consultas separadas requieren snapshot de lectura para identidad exacta entre cortes.",
        ],
    }


def _filtros_pedidos(desde: date, hasta: date, peso_balon_kg: int | None) -> dict[str, Any]:
    return {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "peso_balon_kg": peso_balon_kg if peso_balon_kg is not None else "todos",
        "estado": "ACTIVO",
    }


def _cliente(fila: repo.ClienteNominalDB) -> dict[str, Any]:
    return {
        "cliente_id": fila.id,
        "alias": fila.alias,
        "nombre": fila.nombre,
        "telefono": fila.telefono,
        "direccion_activa_observada": fila.direccion_activa_observada,
        "canal_captacion": fila.canal_captacion,
    }


def _pedido(fila: repo.PedidoNominalDB) -> dict[str, Any]:
    total, total_legacy = _centavos(fila.monto_total_centavos, fila.total_soles)
    pendiente, pendiente_legacy = _centavos(
        fila.monto_pendiente_centavos, fila.saldo_pendiente
    )
    if total is None or pendiente is None:
        estado_monto = "sin_dato"
    elif total < 0 or pendiente < 0 or pendiente > total:
        estado_monto = "anomalo"
    else:
        estado_monto = "valido"
    valido = estado_monto == "valido"
    return {
        "pedido_id": fila.id,
        "cliente_id": fila.cliente_id,
        "cliente_alias": fila.cliente_alias,
        "direccion_pedido": fila.direccion_pedido,
        "fecha_entrega": fila.fecha_entrega.isoformat(),
        "peso_balon_kg": fila.peso_balon_kg,
        "cantidad_balones": fila.cantidad_balones,
        "monto_total_centavos": total if valido else None,
        "monto_pendiente_centavos": pendiente if valido else None,
        "cobrado_calculado_centavos": total - pendiente if valido else None,
        "estado_monto": estado_monto,
        "monto_total_legacy": total_legacy,
        "pendiente_legacy": pendiente_legacy,
        "metodo_pago": fila.metodo_pago,
    }


def _cobertura(pedidos: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "pedidos_monto_total_legacy": sum(p["monto_total_legacy"] for p in pedidos),
        "pedidos_pendiente_legacy": sum(p["pendiente_legacy"] for p in pedidos),
        "pedidos_sin_monto_valido": sum(p["estado_monto"] == "sin_dato" for p in pedidos),
        "pedidos_monetarios_anomalos": sum(p["estado_monto"] == "anomalo" for p in pedidos),
        "pedidos_con_monto_valido": sum(p["estado_monto"] == "valido" for p in pedidos),
    }


def pagina_pedidos(
    db: Session | None, *, desde: date, hasta: date,
    peso_balon_kg: int | None = None, offset: int = 0, limit: int = 100,
) -> dict[str, Any]:
    db = _db_pg(db)
    _validar_filtros(desde, hasta, peso_balon_kg)
    _validar_pagina(offset, limit)
    filtros = _filtros_pedidos(desde, hasta, peso_balon_kg)
    total = repo.contar_pedidos(db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg)
    filas = [_pedido(p) for p in repo.listar_pedidos(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg,
        offset=offset, limit=limit,
    )]
    return {"metadatos": _meta("pedidos_activos", total=total, filtros=filtros),
            "offset": offset, "limite": limit, "filas": filas,
            "cobertura_pagina": _cobertura(filas)}


def pagina_clientes_registrados(
    db: Session | None, *, offset: int = 0, limit: int = 100,
) -> dict[str, Any]:
    db = _db_pg(db)
    _validar_pagina(offset, limit)
    total = repo.contar_clientes_registrados(db)
    filas = [_cliente(c) for c in repo.listar_clientes_registrados(
        db, offset=offset, limit=limit
    )]
    return {"metadatos": _meta("clientes_registrados", total=total, filtros={}),
            "offset": offset, "limite": limit, "filas": filas}


def preparar_exportacion_pedidos(
    db: Session | None, *, desde: date, hasta: date,
    peso_balon_kg: int | None = None,
) -> dict[str, Any]:
    """Prepara en memoria un extracto acotado; no guarda archivos ni descarga."""
    db = _db_pg(db)
    _validar_filtros(desde, hasta, peso_balon_kg)
    filtros = _filtros_pedidos(desde, hasta, peso_balon_kg)
    total = repo.contar_pedidos(db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg)
    if total > MAX_EXPORT_FILAS:
        raise ValueError("La exportación excede el límite de filas; reduzca el periodo")
    pedidos = [_pedido(p) for p in repo.listar_pedidos(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg,
        offset=0, limit=MAX_EXPORT_FILAS,
    )]
    n_compradores = repo.contar_compradores(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg
    )
    compradores = [_cliente(c) for c in repo.listar_compradores(
        db, desde=desde, hasta=hasta, peso_balon_kg=peso_balon_kg,
        offset=0, limit=MAX_EXPORT_FILAS,
    )]
    if len(pedidos) != total or len(compradores) != n_compradores:
        raise RuntimeError("La población cambió durante la lectura; repetir con snapshot")
    metadatos = _meta("pedidos_activos_y_compradores", total=total, filtros=filtros)
    metadatos["clientes_compradores"] = n_compradores
    return {"metadatos": metadatos, "pedidos": pedidos,
            "compradores": compradores, "cobertura": _cobertura(pedidos)}


def preparar_exportacion_clientes_registrados(db: Session | None) -> dict[str, Any]:
    db = _db_pg(db)
    total = repo.contar_clientes_registrados(db)
    if total > MAX_EXPORT_FILAS:
        raise ValueError("El catálogo excede el límite de filas; requiere paginación")
    clientes = [_cliente(c) for c in repo.listar_clientes_registrados(
        db, offset=0, limit=MAX_EXPORT_FILAS
    )]
    if len(clientes) != total:
        raise RuntimeError("El catálogo cambió durante la lectura; repetir con snapshot")
    return {"metadatos": _meta("clientes_registrados", total=total, filtros={}),
            "clientes": clientes}
