"""Service `stock` con dispatch PostgreSQL/DynamoDB."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from typing import TYPE_CHECKING

from app.core.storage import is_dynamodb_enabled
from app.schemas.stock import (
    MovimientoStockOut,
    StockContinuarPreviewOut,
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
TIPO_REVERSA_ANULACION = "REVERSA_ANULACION"


def _bucket_vacio() -> dict:
    return {
        "salidas": 0,
        "entradas": 0,
        "reversas": 0,
        "ajustes": 0,
        "stock_disponible": 0,
    }


def _bucket_por_peso_vacio() -> dict:
    return {"10kg": _bucket_vacio(), "45kg": _bucket_vacio()}


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
    peso_balon_kg: int | None = None,
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
            peso_balon_kg=peso_balon_kg,
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
        session,
        jornada=jornada,
        cantidad=cantidad,
        observacion=observacion,
        peso_balon_kg=peso_balon_kg,
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
    peso_balon_kg: int | None = None,
) -> StockOperacionOut:
    """Si `peso_balon_kg` se provee, `stock_fisico` es el stock objetivo para
    ese peso (10 o 45). El delta se calcula contra `por_peso[peso].stock_disponible`
    y se aplica tanto al global como al bucket del peso indicado (via el
    MovimientoStock que lleva `peso_balon_kg`).
    Si `peso_balon_kg` es None, comportamiento legacy: ajusta el global.
    """
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

        if peso_balon_kg is None:
            delta = stock_fisico - jornada.stock_actual
            stock_resultante = stock_fisico
        else:
            resumen_actual = _ddb_resumen(fecha)
            por_peso = resumen_actual.por_peso
            if peso_balon_kg == 45:
                disponible_actual = por_peso.cuarenta_y_cinco_kg.stock_disponible
            else:
                disponible_actual = por_peso.diez_kg.stock_disponible
            delta = stock_fisico - disponible_actual
            stock_resultante = jornada.stock_actual + delta

        if delta != 0:
            ddb_jornadas.aplicar_delta(fecha.isoformat(), delta)
            ddb_movs.registrar_movimiento(
                fecha=fecha.isoformat(),
                tipo=TIPO_AJUSTE,
                cantidad_delta=delta,
                stock_resultante=stock_resultante,
                observacion=observacion,
                peso_balon_kg=peso_balon_kg,
            )
        return StockOperacionOut(
            fecha=fecha,
            tipo=TIPO_AJUSTE,
            cantidad_delta=delta,
            stock_actual=stock_resultante,
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
        peso_balon_kg=peso_balon_kg,
    )
    return StockOperacionOut(
        fecha=fecha,
        tipo=TIPO_AJUSTE,
        cantidad_delta=0 if movimiento is None else movimiento.cantidad_delta,
        stock_actual=jornada.stock_actual,
        observacion=observacion,
    )


def preview_continuar_dia(
    db: "Session | None", *, fecha: date_cls
) -> StockContinuarPreviewOut:
    """Si existe una jornada anterior con stock > 0, devuelve sus totales
    por peso para que el cliente pueda confirmar el carry-over.
    """
    if is_dynamodb_enabled():
        return _ddb_preview_continuar(fecha)

    from app.infrastructure.repositories import stock as repo_stock

    session = _require_db(db)
    jornada_anterior = repo_stock.obtener_ultima_jornada_anterior(session, fecha)
    if jornada_anterior is None:
        return StockContinuarPreviewOut(puede_continuar=False)

    movimientos = repo_stock.listar_movimientos(session, jornada_anterior.id)
    por_peso = repo_stock.construir_resumen_por_peso(
        jornada_anterior.stock_inicial, movimientos
    )
    stock_10 = max(0, por_peso["10kg"]["stock_disponible"])
    stock_45 = max(0, por_peso["45kg"]["stock_disponible"])
    return StockContinuarPreviewOut(
        puede_continuar=(stock_10 + stock_45) > 0,
        fecha_origen=jornada_anterior.fecha,
        stock_10kg=stock_10,
        stock_45kg=stock_45,
    )


def continuar_de_ayer(
    db: "Session | None", *, fecha: date_cls
) -> StockResumenOut:
    """Crea la jornada de `fecha` arrastrando el stock por peso de la
    ultima jornada anterior. El stock 10 kg va como stock_inicial (bucket
    legacy 10 kg). El stock 45 kg se registra como ENTRADA con peso 45
    inmediatamente despues, asi el resumen por peso queda correcto.
    """
    if is_dynamodb_enabled():
        return _ddb_continuar_de_ayer(fecha)

    from app.infrastructure.repositories import stock as repo_stock

    session = _require_db(db)
    if repo_stock.obtener_jornada_por_fecha(session, fecha) is not None:
        raise StockYaIniciadoError("El stock del dia ya fue iniciado.")

    jornada_anterior = repo_stock.obtener_ultima_jornada_anterior(session, fecha)
    if jornada_anterior is None:
        raise StockNoIniciadoError(
            "No hay una jornada anterior para arrastrar el stock."
        )

    movimientos_prev = repo_stock.listar_movimientos(
        session, jornada_anterior.id
    )
    por_peso = repo_stock.construir_resumen_por_peso(
        jornada_anterior.stock_inicial, movimientos_prev
    )
    stock_10 = max(0, por_peso["10kg"]["stock_disponible"])
    stock_45 = max(0, por_peso["45kg"]["stock_disponible"])

    jornada = repo_stock.iniciar_dia(
        session,
        fecha=fecha,
        stock_inicial=stock_10,
        observacion=f"Continuado de {jornada_anterior.fecha.isoformat()}",
    )
    if stock_45 > 0:
        repo_stock.registrar_entrada(
            session,
            jornada=jornada,
            cantidad=stock_45,
            observacion=f"Carry-over 45kg de {jornada_anterior.fecha.isoformat()}",
            peso_balon_kg=45,
        )

    return StockResumenOut(**repo_stock.construir_resumen(session, fecha))


def _ddb_preview_continuar(fecha: date_cls) -> StockContinuarPreviewOut:
    from app.infrastructure.dynamodb.repositories import (
        movimientos_stock as ddb_movs,
    )
    from app.infrastructure.dynamodb.repositories import (
        stock_jornadas as ddb_jornadas,
    )

    todas = ddb_jornadas.listar_jornadas_anteriores(fecha.isoformat())
    if not todas:
        return StockContinuarPreviewOut(puede_continuar=False)
    ultima = todas[0]
    movs = ddb_movs.listar_movimientos_por_fecha(ultima.fecha)
    stock_10 = ultima.stock_inicial
    stock_45 = 0
    for m in movs:
        bucket_45 = (m.peso_balon_kg or 10) == 45
        if m.tipo == TIPO_ENTRADA:
            if bucket_45:
                stock_45 += m.cantidad_delta
            else:
                stock_10 += m.cantidad_delta
        elif m.tipo == TIPO_SALIDA_PEDIDO:
            if bucket_45:
                stock_45 += m.cantidad_delta
            else:
                stock_10 += m.cantidad_delta
        elif m.tipo == TIPO_REVERSA_ANULACION:
            if bucket_45:
                stock_45 += m.cantidad_delta
            else:
                stock_10 += m.cantidad_delta
        elif m.tipo == TIPO_AJUSTE:
            if bucket_45:
                stock_45 += m.cantidad_delta
            else:
                stock_10 += m.cantidad_delta
    stock_10 = max(0, stock_10)
    stock_45 = max(0, stock_45)
    return StockContinuarPreviewOut(
        puede_continuar=(stock_10 + stock_45) > 0,
        fecha_origen=date_cls.fromisoformat(ultima.fecha),
        stock_10kg=stock_10,
        stock_45kg=stock_45,
    )


def _ddb_continuar_de_ayer(fecha: date_cls) -> StockResumenOut:
    from app.infrastructure.dynamodb.repositories import (
        movimientos_stock as ddb_movs,
    )
    from app.infrastructure.dynamodb.repositories import (
        stock_jornadas as ddb_jornadas,
    )

    if ddb_jornadas.obtener_jornada(fecha.isoformat()) is not None:
        raise StockYaIniciadoError("El stock del dia ya fue iniciado.")

    preview = _ddb_preview_continuar(fecha)
    if not preview.puede_continuar or preview.fecha_origen is None:
        raise StockNoIniciadoError(
            "No hay una jornada anterior para arrastrar el stock."
        )

    ddb_jornadas.abrir_jornada(fecha.isoformat(), preview.stock_10kg)
    ddb_movs.registrar_movimiento(
        fecha=fecha.isoformat(),
        tipo=TIPO_INICIO_DIA,
        cantidad_delta=preview.stock_10kg,
        stock_resultante=preview.stock_10kg,
        observacion=f"Continuado de {preview.fecha_origen.isoformat()}",
    )
    if preview.stock_45kg > 0:
        resultante = ddb_jornadas.aplicar_delta(
            fecha.isoformat(), preview.stock_45kg
        )
        ddb_movs.registrar_movimiento(
            fecha=fecha.isoformat(),
            tipo=TIPO_ENTRADA,
            cantidad_delta=preview.stock_45kg,
            stock_resultante=resultante,
            observacion=f"Carry-over 45kg de {preview.fecha_origen.isoformat()}",
            peso_balon_kg=45,
        )
    return _ddb_resumen(fecha)


def registrar_salida_por_pedido(
    db: "Session | None",
    *,
    fecha: date_cls,
    cantidad_balones: int,
    pedido_id: int | str,
    marca_balon: str | None = None,
    tipo_balon: str | None = None,
    peso_balon_kg: int | None = None,
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
            peso_balon_kg=peso_balon_kg,
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
        peso_balon_kg=peso_balon_kg,
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
            por_peso=_bucket_por_peso_vacio(),
        )

    movs = ddb_movs.listar_movimientos_por_fecha(fecha.isoformat())
    entradas = sum(m.cantidad_delta for m in movs if m.tipo == TIPO_ENTRADA)
    # salidas neto: reversas (+N) cancelan SALIDA_PEDIDO (-N).
    salidas = -sum(
        m.cantidad_delta
        for m in movs
        if m.tipo in (TIPO_SALIDA_PEDIDO, TIPO_REVERSA_ANULACION)
    )
    ajustes = sum(m.cantidad_delta for m in movs if m.tipo == TIPO_AJUSTE)

    por_peso = _bucket_por_peso_vacio()
    por_peso["10kg"]["stock_disponible"] = jornada.stock_inicial
    for m in movs:
        bucket_key = "45kg" if (m.peso_balon_kg or 10) == 45 else "10kg"
        bucket = por_peso[bucket_key]
        if m.tipo == TIPO_ENTRADA:
            bucket["entradas"] += m.cantidad_delta
            bucket["stock_disponible"] += m.cantidad_delta
        elif m.tipo == TIPO_SALIDA_PEDIDO:
            bucket["salidas"] += -m.cantidad_delta
            bucket["stock_disponible"] += m.cantidad_delta
        elif m.tipo == TIPO_REVERSA_ANULACION:
            bucket["reversas"] += m.cantidad_delta
            bucket["stock_disponible"] += m.cantidad_delta
        elif m.tipo == TIPO_AJUSTE:
            bucket["ajustes"] += m.cantidad_delta
            bucket["stock_disponible"] += m.cantidad_delta

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
        por_peso=por_peso,
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
                peso_balon_kg=m.peso_balon_kg,
            )
        )
    return out
