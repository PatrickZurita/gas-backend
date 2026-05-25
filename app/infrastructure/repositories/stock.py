from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import MovimientoStock, StockJornada

TIPO_INICIO_DIA = "INICIO_DIA"
TIPO_ENTRADA = "ENTRADA"
TIPO_SALIDA_PEDIDO = "SALIDA_PEDIDO"
TIPO_AJUSTE = "AJUSTE"
TIPO_REVERSA_ANULACION = "REVERSA_ANULACION"


def obtener_jornada_por_fecha(db: Session, fecha: date) -> StockJornada | None:
    stmt = select(StockJornada).where(StockJornada.fecha == fecha)
    return db.execute(stmt).scalars().first()


def obtener_ultima_jornada_anterior(
    db: Session, fecha: date
) -> StockJornada | None:
    """Devuelve la jornada con fecha mas reciente estrictamente anterior a `fecha`.

    Usado por el flujo de continuar-de-ayer: permite traer el stock final
    del ultimo dia trabajado aunque no sea exactamente el dia anterior
    (ej. lunes despues de fin de semana sin operacion).
    """
    stmt = (
        select(StockJornada)
        .where(StockJornada.fecha < fecha)
        .order_by(StockJornada.fecha.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def listar_movimientos(db: Session, jornada_id: int) -> list[MovimientoStock]:
    stmt = (
        select(MovimientoStock)
        .where(MovimientoStock.stock_jornada_id == jornada_id)
        .order_by(MovimientoStock.created_at.asc(), MovimientoStock.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def iniciar_dia(
    db: Session,
    *,
    fecha: date,
    stock_inicial: int,
    observacion: str | None = None,
) -> StockJornada:
    jornada = StockJornada(
        fecha=fecha,
        stock_inicial=stock_inicial,
        stock_actual=stock_inicial,
        cerrado=False,
    )
    db.add(jornada)
    db.flush()
    db.add(
        MovimientoStock(
            stock_jornada_id=jornada.id,
            fecha=fecha,
            tipo=TIPO_INICIO_DIA,
            cantidad_delta=stock_inicial,
            stock_resultante=stock_inicial,
            observacion=observacion or "Inicio de dia",
        )
    )
    db.commit()
    db.refresh(jornada)
    return jornada


def registrar_entrada(
    db: Session,
    *,
    jornada: StockJornada,
    cantidad: int,
    observacion: str | None = None,
    peso_balon_kg: int | None = None,
) -> MovimientoStock:
    jornada.stock_actual += cantidad
    movimiento = MovimientoStock(
        stock_jornada_id=jornada.id,
        fecha=jornada.fecha,
        tipo=TIPO_ENTRADA,
        cantidad_delta=cantidad,
        stock_resultante=jornada.stock_actual,
        observacion=observacion,
        peso_balon_kg=peso_balon_kg,
    )
    db.add(movimiento)
    db.commit()
    db.refresh(movimiento)
    return movimiento


def registrar_ajuste_a_stock_fisico(
    db: Session,
    *,
    jornada: StockJornada,
    stock_fisico: int,
    observacion: str | None = None,
    peso_balon_kg: int | None = None,
) -> MovimientoStock | None:
    """Si `peso_balon_kg` se provee, `stock_fisico` es el objetivo de ese
    peso. El delta se calcula contra el stock por peso derivado de movimientos
    y se aplica al global. El MovimientoStock lleva el peso para que el
    resumen por peso lo bucketize correcto.
    """
    if peso_balon_kg is None:
        delta = stock_fisico - jornada.stock_actual
    else:
        movimientos = listar_movimientos(db, jornada.id)
        por_peso = construir_resumen_por_peso(
            jornada.stock_inicial, movimientos
        )
        bucket = "45kg" if peso_balon_kg == 45 else "10kg"
        disponible_actual = por_peso[bucket]["stock_disponible"]
        delta = stock_fisico - disponible_actual

    if delta == 0:
        return None

    jornada.stock_actual = jornada.stock_actual + delta
    if peso_balon_kg is None:
        # legacy: el ajuste global tambien refleja el stock fisico cerrado
        jornada.stock_final_fisico = stock_fisico
    movimiento = MovimientoStock(
        stock_jornada_id=jornada.id,
        fecha=jornada.fecha,
        tipo=TIPO_AJUSTE,
        cantidad_delta=delta,
        stock_resultante=jornada.stock_actual,
        observacion=observacion,
        peso_balon_kg=peso_balon_kg,
    )
    db.add(movimiento)
    db.commit()
    db.refresh(movimiento)
    return movimiento


def registrar_salida_pedido_si_jornada_existe(
    db: Session,
    *,
    fecha: date,
    cantidad_balones: int,
    pedido_id: int,
    marca_balon: str | None = None,
    tipo_balon: str | None = None,
    peso_balon_kg: int | None = None,
) -> MovimientoStock | None:
    jornada = obtener_jornada_por_fecha(db, fecha)
    if jornada is None or jornada.cerrado:
        return None

    delta = -cantidad_balones
    jornada.stock_actual += delta
    movimiento = MovimientoStock(
        stock_jornada_id=jornada.id,
        fecha=fecha,
        tipo=TIPO_SALIDA_PEDIDO,
        cantidad_delta=delta,
        stock_resultante=jornada.stock_actual,
        pedido_id=pedido_id,
        marca_balon=marca_balon,
        tipo_balon=tipo_balon,
        peso_balon_kg=peso_balon_kg,
        observacion="Salida por pedido",
    )
    db.add(movimiento)
    db.flush()
    return movimiento


def registrar_reversa_anulacion_si_jornada_existe(
    db: Session,
    *,
    fecha: date,
    cantidad_balones: int,
    pedido_id: int,
    marca_balon: str | None = None,
    tipo_balon: str | None = None,
    peso_balon_kg: int | None = None,
    observacion: str | None = None,
) -> MovimientoStock | None:
    """Compensa la salida de un pedido (anulado o editado) devolviendo stock (+N).

    Solo aplica si la jornada de `fecha` existe y no esta cerrada. La reversa
    referencia el `pedido_id` y se contabiliza como neto de salidas (no como
    ajuste fisico), para no ocultar la anulacion/edicion en el rubro de
    ajustes. El `observacion` permite distinguir reversas por anulacion vs
    por edicion de cantidad/fecha.
    """
    jornada = obtener_jornada_por_fecha(db, fecha)
    if jornada is None or jornada.cerrado:
        return None

    delta = cantidad_balones
    jornada.stock_actual += delta
    movimiento = MovimientoStock(
        stock_jornada_id=jornada.id,
        fecha=fecha,
        tipo=TIPO_REVERSA_ANULACION,
        cantidad_delta=delta,
        stock_resultante=jornada.stock_actual,
        pedido_id=pedido_id,
        marca_balon=marca_balon,
        tipo_balon=tipo_balon,
        peso_balon_kg=peso_balon_kg,
        observacion=observacion or "Reversa por anulacion de pedido",
    )
    db.add(movimiento)
    db.flush()
    return movimiento


def construir_resumen(db: Session, fecha: date) -> dict[str, object]:
    jornada = obtener_jornada_por_fecha(db, fecha)
    if jornada is None:
        return {
            "fecha": fecha,
            "stock_iniciado": False,
            "stock_inicial": None,
            "entradas": 0,
            "salidas": 0,
            "ajustes": 0,
            "stock_actual": None,
            "stock_final_fisico": None,
            "cerrado": False,
            "por_peso": _bucket_por_peso_vacio(),
        }

    movimientos = listar_movimientos(db, jornada.id)
    entradas = sum(
        movimiento.cantidad_delta
        for movimiento in movimientos
        if movimiento.tipo == TIPO_ENTRADA
    )
    # `salidas` neto: la reversa por anulacion/edicion (+N) cancela su
    # SALIDA_PEDIDO (-N), de modo que un pedido anulado o editado no cuenta
    # como salida ni queda escondido en `ajustes`.
    salidas = -sum(
        movimiento.cantidad_delta
        for movimiento in movimientos
        if movimiento.tipo in (TIPO_SALIDA_PEDIDO, TIPO_REVERSA_ANULACION)
    )
    ajustes = sum(
        movimiento.cantidad_delta
        for movimiento in movimientos
        if movimiento.tipo == TIPO_AJUSTE
    )

    return {
        "fecha": fecha,
        "stock_iniciado": True,
        "stock_inicial": jornada.stock_inicial,
        "entradas": entradas,
        "salidas": salidas,
        "ajustes": ajustes,
        "stock_actual": jornada.stock_actual,
        "stock_final_fisico": jornada.stock_final_fisico,
        "cerrado": jornada.cerrado,
        "por_peso": construir_resumen_por_peso(
            jornada.stock_inicial, movimientos
        ),
    }


def _bucket_por_peso_vacio() -> dict[str, dict[str, int]]:
    return {
        "10kg": {
            "salidas": 0,
            "entradas": 0,
            "reversas": 0,
            "ajustes": 0,
            "stock_disponible": 0,
        },
        "45kg": {
            "salidas": 0,
            "entradas": 0,
            "reversas": 0,
            "ajustes": 0,
            "stock_disponible": 0,
        },
    }


def construir_resumen_por_peso(
    stock_inicial: int,
    movimientos: list[MovimientoStock],
) -> dict[str, dict[str, int]]:
    """Segrega movimientos en buckets 10 kg y 45 kg.

    El `stock_inicial` global se asigna al bucket 10 kg (decision V2.3
    porque el stock legacy es exclusivamente 10 kg; los 45 kg parten de 0).
    Movimientos sin `peso_balon_kg` se interpretan como 10 kg (legacy).
    """
    buckets = _bucket_por_peso_vacio()
    buckets["10kg"]["stock_disponible"] = stock_inicial

    for mov in movimientos:
        bucket_key = "45kg" if (mov.peso_balon_kg or 10) == 45 else "10kg"
        bucket = buckets[bucket_key]
        if mov.tipo == TIPO_ENTRADA:
            bucket["entradas"] += mov.cantidad_delta
            bucket["stock_disponible"] += mov.cantidad_delta
        elif mov.tipo == TIPO_SALIDA_PEDIDO:
            bucket["salidas"] += -mov.cantidad_delta
            bucket["stock_disponible"] += mov.cantidad_delta
        elif mov.tipo == TIPO_REVERSA_ANULACION:
            bucket["reversas"] += mov.cantidad_delta
            bucket["stock_disponible"] += mov.cantidad_delta
        elif mov.tipo == TIPO_AJUSTE:
            bucket["ajustes"] += mov.cantidad_delta
            bucket["stock_disponible"] += mov.cantidad_delta
        # INICIO_DIA se ignora aqui: ya esta sumado via `stock_inicial`.

    return buckets
