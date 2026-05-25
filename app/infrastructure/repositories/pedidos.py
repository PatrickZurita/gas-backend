from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Pedido, Direccion, Cliente
from app.infrastructure.repositories import stock as repo_stock
from app.infrastructure.repositories._id_helpers import to_pg_id


def _get_or_create_direccion_default(db: Session, cliente: Cliente) -> Direccion:
    stmt = (
        select(Direccion)
        .where(
            Direccion.cliente_id == cliente.id,
            Direccion.activa.is_(True),
        )
        .order_by(Direccion.id.asc())
        .limit(1)
    )

    direccion = db.execute(stmt).scalars().first()
    if direccion is not None:
        return direccion

    direccion = Direccion(
        cliente_id=cliente.id,
        texto_original=cliente.alias,  # dirección por defecto
        distrito=None,
        referencia=None,
        activa=True,
    )
    db.add(direccion)
    db.flush()  # obtiene direccion.id sin commit todavía
    return direccion

def buscar_pedidos_por_cliente(db: Session, cliente_id: int | str, limit: int = 50) -> list[Pedido]:
    pg_id = to_pg_id(cliente_id)
    stmt = (
        select(Pedido)
        .where(Pedido.cliente_id == pg_id)
        .order_by(Pedido.created_at.desc(), Pedido.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())

def crear_pedido(
    db: Session,
    cliente: Cliente,
    fecha_entrega: date,
    cantidad_balones: int,
    total_soles: Decimal,
    tipo_balon: str = "NORMAL",
    marca_balon: str = "PETROPERU",
    precio_unitario_centavos: int | None = None,
    monto_total_centavos: int | None = None,
    pagado: bool = True,
    saldo_pendiente: Decimal | None = None,
    monto_pendiente_centavos: int | None = None,
    observacion: str | None = None,
    peso_balon_kg: int = 10,
    metodo_pago: str | None = None,
) -> Pedido:
    try:
        direccion = _get_or_create_direccion_default(db, cliente)

        pedido = Pedido(
            cliente_id=cliente.id,
            direccion_id=direccion.id,
            fecha_entrega=fecha_entrega,
            cantidad_balones=cantidad_balones,
            total_soles=total_soles,
            tipo_balon=tipo_balon,
            marca_balon=marca_balon,
            precio_unitario_centavos=precio_unitario_centavos,
            monto_total_centavos=monto_total_centavos,
            pagado=pagado,
            saldo_pendiente=(
                saldo_pendiente
                if saldo_pendiente is not None
                else (0 if pagado else total_soles)
            ),
            monto_pendiente_centavos=monto_pendiente_centavos,
            peso_balon_kg=peso_balon_kg,
            metodo_pago=metodo_pago if pagado else None,
        )

        db.add(pedido)
        db.flush()
        repo_stock.registrar_salida_pedido_si_jornada_existe(
            db,
            fecha=fecha_entrega,
            cantidad_balones=cantidad_balones,
            pedido_id=pedido.id,
            marca_balon=marca_balon,
            tipo_balon=tipo_balon,
            peso_balon_kg=peso_balon_kg,
        )
        db.commit()
        db.refresh(pedido)
        return pedido

    except Exception:
        db.rollback()
        raise


def anular_pedido(
    db: Session,
    pedido_id: int | str,
    *,
    motivo: str | None = None,
) -> Pedido:
    """Marca un pedido como ANULADO y compensa el stock (idempotente).

    Si el pedido ya esta ANULADO no se vuelve a compensar el stock: la
    segunda llamada es un no-op que devuelve el pedido sin duplicar la
    reversa. La compensacion solo ocurre si la jornada de `fecha_entrega`
    existe y no esta cerrada.
    """
    pg_id = to_pg_id(pedido_id)
    try:
        pedido = db.get(Pedido, pg_id)
        if pedido is None:
            raise ValueError(f"Pedido {pedido_id} no existe.")

        if pedido.estado == "ANULADO":
            return pedido

        pedido.estado = "ANULADO"
        pedido.anulado_at = datetime.now(timezone.utc)
        pedido.anulado_motivo = motivo

        repo_stock.registrar_reversa_anulacion_si_jornada_existe(
            db,
            fecha=pedido.fecha_entrega,
            cantidad_balones=pedido.cantidad_balones,
            pedido_id=pedido.id,
            marca_balon=pedido.marca_balon,
            tipo_balon=pedido.tipo_balon,
            peso_balon_kg=pedido.peso_balon_kg,
        )
        db.commit()
        db.refresh(pedido)
        return pedido

    except Exception:
        db.rollback()
        raise


class PedidoAnuladoEditableError(Exception):
    """Intento de editar un pedido ya anulado (409)."""


def patch_pedido(
    db: Session,
    pedido_id: int | str,
    *,
    cantidad_balones: int | None = None,
    precio_unitario_centavos: int | None = None,
    monto_total_centavos: int | None = None,
    monto_pendiente_centavos: int | None = None,
    pagado: bool | None = None,
    fecha_entrega: date | None = None,
    peso_balon_kg: int | None = None,
    metodo_pago: str | None = None,
    motivo_edicion: str | None = None,
) -> Pedido:
    """Edita un pedido ACTIVO y compensa stock si cambia cantidad/fecha/peso.

    Reglas:
    - Pedido ANULADO -> PedidoAnuladoEditableError.
    - Cambia cantidad: reversa por edicion (+N viejo) en jornada actual +
      nueva SALIDA_PEDIDO (-N nuevo) en la jornada destino.
    - Cambia fecha: reversa en jornada vieja + nueva SALIDA en jornada nueva.
    - Cambia peso: reversa en bucket viejo + nueva SALIDA en bucket nuevo
      (mismo dia o nuevo dia segun fecha_entrega).
    """
    pg_id = to_pg_id(pedido_id)
    try:
        pedido = db.get(Pedido, pg_id)
        if pedido is None:
            raise ValueError(f"Pedido {pedido_id} no existe.")
        if pedido.estado == "ANULADO":
            raise PedidoAnuladoEditableError(
                "No se puede editar un pedido anulado."
            )

        cantidad_vieja = pedido.cantidad_balones
        fecha_vieja = pedido.fecha_entrega
        peso_viejo = pedido.peso_balon_kg
        marca_balon = pedido.marca_balon
        tipo_balon = pedido.tipo_balon

        stock_impactado = (
            cantidad_balones is not None
            or fecha_entrega is not None
            or peso_balon_kg is not None
        )

        if cantidad_balones is not None:
            pedido.cantidad_balones = cantidad_balones
        if precio_unitario_centavos is not None:
            pedido.precio_unitario_centavos = precio_unitario_centavos
        if monto_total_centavos is not None:
            pedido.monto_total_centavos = monto_total_centavos
        if monto_pendiente_centavos is not None:
            pedido.monto_pendiente_centavos = monto_pendiente_centavos
        if pagado is not None:
            pedido.pagado = pagado
            if pagado is False:
                # Si se marca como no pagado, el metodo de pago deja de aplicar.
                pedido.metodo_pago = None
        if fecha_entrega is not None:
            pedido.fecha_entrega = fecha_entrega
        if peso_balon_kg is not None:
            pedido.peso_balon_kg = peso_balon_kg
        if metodo_pago is not None:
            pedido.metodo_pago = metodo_pago
        if motivo_edicion is not None:
            # Reutilizamos `anulado_motivo` para trazabilidad cuando se quiera
            # auditar; alternativa: tabla de auditoria. MVP: anotacion en
            # observacion del movimiento de reversa.
            pass

        if stock_impactado:
            # 1) Reversa por edicion en la jornada/peso anterior.
            repo_stock.registrar_reversa_anulacion_si_jornada_existe(
                db,
                fecha=fecha_vieja,
                cantidad_balones=cantidad_vieja,
                pedido_id=pedido.id,
                marca_balon=marca_balon,
                tipo_balon=tipo_balon,
                peso_balon_kg=peso_viejo,
                observacion=motivo_edicion or "Reversa por edicion de pedido",
            )
            # 2) Nueva salida con la cantidad/fecha/peso actualizados.
            repo_stock.registrar_salida_pedido_si_jornada_existe(
                db,
                fecha=pedido.fecha_entrega,
                cantidad_balones=pedido.cantidad_balones,
                pedido_id=pedido.id,
                marca_balon=pedido.marca_balon,
                tipo_balon=pedido.tipo_balon,
                peso_balon_kg=pedido.peso_balon_kg,
            )

        db.commit()
        db.refresh(pedido)
        return pedido

    except Exception:
        db.rollback()
        raise
