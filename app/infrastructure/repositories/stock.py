from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import MovimientoStock, StockJornada

TIPO_INICIO_DIA = "INICIO_DIA"
TIPO_ENTRADA = "ENTRADA"
TIPO_SALIDA_PEDIDO = "SALIDA_PEDIDO"
TIPO_AJUSTE = "AJUSTE"


def obtener_jornada_por_fecha(db: Session, fecha: date) -> StockJornada | None:
    stmt = select(StockJornada).where(StockJornada.fecha == fecha)
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
) -> MovimientoStock:
    jornada.stock_actual += cantidad
    movimiento = MovimientoStock(
        stock_jornada_id=jornada.id,
        fecha=jornada.fecha,
        tipo=TIPO_ENTRADA,
        cantidad_delta=cantidad,
        stock_resultante=jornada.stock_actual,
        observacion=observacion,
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
) -> MovimientoStock | None:
    delta = stock_fisico - jornada.stock_actual
    if delta == 0:
        return None

    jornada.stock_actual = stock_fisico
    jornada.stock_final_fisico = stock_fisico
    movimiento = MovimientoStock(
        stock_jornada_id=jornada.id,
        fecha=jornada.fecha,
        tipo=TIPO_AJUSTE,
        cantidad_delta=delta,
        stock_resultante=jornada.stock_actual,
        observacion=observacion,
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
        observacion="Salida por pedido",
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
        }

    movimientos = listar_movimientos(db, jornada.id)
    entradas = sum(
        movimiento.cantidad_delta
        for movimiento in movimientos
        if movimiento.tipo == TIPO_ENTRADA
    )
    salidas = -sum(
        movimiento.cantidad_delta
        for movimiento in movimientos
        if movimiento.tipo == TIPO_SALIDA_PEDIDO
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
    }
