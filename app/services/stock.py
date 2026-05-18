"""Service `stock` con dispatch PostgreSQL/DynamoDB."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from typing import TYPE_CHECKING

from app.core.storage import is_dynamodb_enabled
from app.schemas.stock import (
    MovimientoStockOut,
    StockDiaOut,
    StockOperacionOut,
    StockResumenOut,
)
from app.services.errors import (
    StockCerradoError,
    StockNoIniciadoError,
    StockYaIniciadoError,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

TIPO_INICIO_DIA = "INICIO_DIA"
TIPO_ENTRADA = "ENTRADA"
TIPO_SALIDA_PEDIDO = "SALIDA_PEDIDO"
TIPO_AJUSTE = "AJUSTE"


def _require_db(db: "Session | None") -> "Session":
    if db is None:
        raise RuntimeError(
            "Servicio PostgreSQL requiere sesion; "
            "storage actual no esta inyectando una."
        )
    return db


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


def resumen(db: "Session | None", *, fecha: date_cls) -> StockResumenOut:
    if is_dynamodb_enabled():
        return _ddb_resumen(fecha)

    from app.infrastructure.repositories import stock as repo_stock

    session = _require_db(db)
    return StockResumenOut(**repo_stock.construir_resumen(session, fecha))


def stock_dia(db: "Session | None", *, fecha: date_cls) -> StockDiaOut:
    if is_dynamodb_enabled():
        resumen_data = _ddb_resumen(fecha).model_dump()
        movimientos = _ddb_listar_movimientos_out(fecha)
        return StockDiaOut(**resumen_data, movimientos=movimientos)

    from app.infrastructure.repositories import stock as repo_stock

    session = _require_db(db)
    base_resumen = repo_stock.construir_resumen(session, fecha)
    jornada = repo_stock.obtener_jornada_por_fecha(session, fecha)
    if jornada is None:
        return StockDiaOut(**base_resumen, movimientos=[])
    movimientos = repo_stock.listar_movimientos(session, jornada.id)
    return StockDiaOut(
        **base_resumen,
        movimientos=[
            MovimientoStockOut.model_validate(m, from_attributes=True)
            for m in movimientos
        ],
    )


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def iniciar_dia(
    db: "Session | None",
    *,
    fecha: date_cls,
    stock_inicial: int,
    observacion: str | None,
) -> StockResumenOut:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import (
            movimientos_stock as ddb_movs,
        )
        from app.infrastructure.dynamodb.repositories import (
            stock_jornadas as ddb_jornadas,
        )

        if ddb_jornadas.obtener_jornada(fecha.isoformat()) is not None:
            raise StockYaIniciadoError("El stock del dia ya fue iniciado.")

        ddb_jornadas.abrir_jornada(fecha.isoformat(), stock_inicial)
        ddb_movs.registrar_movimiento(
            fecha=fecha.isoformat(),
            tipo=TIPO_INICIO_DIA,
            cantidad_delta=stock_inicial,
            stock_resultante=stock_inicial,
            observacion=observacion or "Inicio de dia",
        )
        return _ddb_resumen(fecha)

    from app.infrastructure.repositories import stock as repo_stock

    session = _require_db(db)
    if repo_stock.obtener_jornada_por_fecha(session, fecha) is not None:
        raise StockYaIniciadoError("El stock del dia ya fue iniciado.")
    repo_stock.iniciar_dia(
        session,
        fecha=fecha,
        stock_inicial=stock_inicial,
        observacion=observacion,
    )
    return StockResumenOut(**repo_stock.construir_resumen(session, fecha))


def registrar_entrada(
    db: "Session | None",
    *,
    fecha: date_cls,
    cantidad: int,
    observacion: str | None,
) -> StockOperacionOut:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import (
            movimientos_stock as ddb_movs,
        )
        from app.infrastructure.dynamodb.repositories import (
            stock_jornadas as ddb_jornadas,
        )

        jornada = ddb_jornadas.obtener_jornada(fecha.isoformat())
        if jornada is None:
            raise StockNoIniciadoError("El stock del dia no fue iniciado.")
        if jornada.cerrado:
            raise StockCerradoError("El stock del dia esta cerrado.")

        resultante = ddb_jornadas.aplicar_delta(fecha.isoformat(), cantidad)
        ddb_movs.registrar_movimiento(
            fecha=fecha.isoformat(),
            tipo=TIPO_ENTRADA,
            cantidad_delta=cantidad,
            stock_resultante=resultante,
            observacion=observacion,
        )
        return StockOperacionOut(
            fecha=fecha,
            tipo=TIPO_ENTRADA,
            cantidad_delta=cantidad,
            stock_actual=resultante,
            observacion=observacion,
        )

    from app.infrastructure.repositories import stock as repo_stock

    session = _require_db(db)
    jornada = repo_stock.obtener_jornada_por_fecha(session, fecha)
    if jornada is None:
        raise StockNoIniciadoError("El stock del dia no fue iniciado.")
    if jornada.cerrado:
        raise StockCerradoError("El stock del dia esta cerrado.")

    movimiento = repo_stock.registrar_entrada(
        session, jornada=jornada, cantidad=cantidad, observacion=observacion
    )
    return StockOperacionOut(
        fecha=fecha,
        tipo=movimiento.tipo,
        cantidad_delta=movimiento.cantidad_delta,
        stock_actual=movimiento.stock_resultante,
        observacion=movimiento.observacion,
    )


def registrar_ajuste(
    db: "Session | None",
    *,
    fecha: date_cls,
    stock_fisico: int,
    observacion: str | None,
) -> StockOperacionOut:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import (
            movimientos_stock as ddb_movs,
        )
        from app.infrastructure.dynamodb.repositories import (
            stock_jornadas as ddb_jornadas,
        )

        jornada = ddb_jornadas.obtener_jornada(fecha.isoformat())
        if jornada is None:
            raise StockNoIniciadoError("El stock del dia no fue iniciado.")
        if jornada.cerrado:
            raise StockCerradoError("El stock del dia esta cerrado.")

        delta = stock_fisico - jornada.stock_actual
        if delta != 0:
            ddb_jornadas.aplicar_delta(fecha.isoformat(), delta)
            ddb_movs.registrar_movimiento(
                fecha=fecha.isoformat(),
                tipo=TIPO_AJUSTE,
                cantidad_delta=delta,
                stock_resultante=stock_fisico,
                observacion=observacion,
            )
        return StockOperacionOut(
            fecha=fecha,
            tipo=TIPO_AJUSTE,
            cantidad_delta=delta,
            stock_actual=stock_fisico,
            observacion=observacion,
        )

    from app.infrastructure.repositories import stock as repo_stock

    session = _require_db(db)
    jornada = repo_stock.obtener_jornada_por_fecha(session, fecha)
    if jornada is None:
        raise StockNoIniciadoError("El stock del dia no fue iniciado.")
    if jornada.cerrado:
        raise StockCerradoError("El stock del dia esta cerrado.")

    movimiento = repo_stock.registrar_ajuste_a_stock_fisico(
        session,
        jornada=jornada,
        stock_fisico=stock_fisico,
        observacion=observacion,
    )
    return StockOperacionOut(
        fecha=fecha,
        tipo=TIPO_AJUSTE,
        cantidad_delta=0 if movimiento is None else movimiento.cantidad_delta,
        stock_actual=stock_fisico,
        observacion=observacion,
    )


def registrar_salida_por_pedido(
    db: "Session | None",
    *,
    fecha: date_cls,
    cantidad_balones: int,
    pedido_id: int | str,
    marca_balon: str | None = None,
    tipo_balon: str | None = None,
) -> None:
    """Side-effect best-effort: si la jornada existe y no esta cerrada,
    registra una salida. No falla el pedido si la jornada no existe."""
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import (
            movimientos_stock as ddb_movs,
        )
        from app.infrastructure.dynamodb.repositories import (
            stock_jornadas as ddb_jornadas,
        )

        jornada = ddb_jornadas.obtener_jornada(fecha.isoformat())
        if jornada is None or jornada.cerrado:
            return
        try:
            resultante = ddb_jornadas.aplicar_delta(fecha.isoformat(), -cantidad_balones)
        except ValueError:
            return
        ddb_movs.registrar_movimiento(
            fecha=fecha.isoformat(),
            tipo=TIPO_SALIDA_PEDIDO,
            cantidad_delta=-cantidad_balones,
            stock_resultante=resultante,
            pedido_id=str(pedido_id),
            observacion="Salida por pedido",
        )
        del marca_balon, tipo_balon  # no se persisten en DDB MVP
        return

    from app.infrastructure.repositories import stock as repo_stock

    session = _require_db(db)
    repo_stock.registrar_salida_pedido_si_jornada_existe(
        session,
        fecha=fecha,
        cantidad_balones=cantidad_balones,
        pedido_id=pedido_id,
        marca_balon=marca_balon,
        tipo_balon=tipo_balon,
    )


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------


def _ddb_resumen(fecha: date_cls) -> StockResumenOut:
    from app.infrastructure.dynamodb.repositories import (
        movimientos_stock as ddb_movs,
    )
    from app.infrastructure.dynamodb.repositories import (
        stock_jornadas as ddb_jornadas,
    )

    jornada = ddb_jornadas.obtener_jornada(fecha.isoformat())
    if jornada is None:
        return StockResumenOut(
            fecha=fecha,
            stock_iniciado=False,
            stock_inicial=None,
            entradas=0,
            salidas=0,
            ajustes=0,
            stock_actual=None,
            stock_final_fisico=None,
            cerrado=False,
        )

    movs = ddb_movs.listar_movimientos_por_fecha(fecha.isoformat())
    entradas = sum(m.cantidad_delta for m in movs if m.tipo == TIPO_ENTRADA)
    salidas = -sum(m.cantidad_delta for m in movs if m.tipo == TIPO_SALIDA_PEDIDO)
    ajustes = sum(m.cantidad_delta for m in movs if m.tipo == TIPO_AJUSTE)

    return StockResumenOut(
        fecha=fecha,
        stock_iniciado=True,
        stock_inicial=jornada.stock_inicial,
        entradas=entradas,
        salidas=salidas,
        ajustes=ajustes,
        stock_actual=jornada.stock_actual,
        stock_final_fisico=None,
        cerrado=jornada.cerrado,
    )


def _ddb_listar_movimientos_out(fecha: date_cls) -> list[MovimientoStockOut]:
    from app.infrastructure.dynamodb.repositories import (
        movimientos_stock as ddb_movs,
    )

    movs = ddb_movs.listar_movimientos_por_fecha(fecha.isoformat())
    out: list[MovimientoStockOut] = []
    for m in movs:
        try:
            created_at = datetime.fromisoformat(m.fecha)
        except ValueError:
            created_at = datetime.utcnow()
        out.append(
            MovimientoStockOut(
                id=m.id,
                tipo=m.tipo,
                cantidad_delta=m.cantidad_delta,
                stock_resultante=m.stock_resultante,
                pedido_id=m.pedido_id,
                observacion=None,
                created_at=created_at,
            )
        )
    return out
