"""Service `pedidos` con dispatch PostgreSQL/DynamoDB."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

from app.core.storage import is_dynamodb_enabled
from app.schemas.pedido import PedidoCreate, PedidoOut
from app.services.errors import ClienteNoExisteError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _require_db(db: "Session | None") -> "Session":
    if db is None:
        raise RuntimeError(
            "Servicio PostgreSQL requiere sesion; "
            "storage actual no esta inyectando una."
        )
    return db


def _soles_a_centavos(monto_soles: Decimal) -> int:
    return int((monto_soles * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _centavos_a_soles(monto_centavos: int) -> Decimal:
    return (Decimal(monto_centavos) / Decimal(100)).quantize(Decimal("0.01"))


def _resolve_monto_total_centavos(payload: PedidoCreate) -> int:
    if payload.monto_total_centavos is not None:
        return payload.monto_total_centavos
    if payload.precio_unitario_centavos is not None:
        return payload.precio_unitario_centavos * payload.cantidad_balones
    return _soles_a_centavos(payload.total_soles or Decimal("0"))


def _resolve_monto_pendiente_centavos(
    payload: PedidoCreate, monto_total_centavos: int
) -> int:
    if payload.monto_pendiente_centavos is not None:
        return payload.monto_pendiente_centavos
    if payload.saldo_pendiente is not None:
        return _soles_a_centavos(payload.saldo_pendiente)
    return 0 if payload.pagado else monto_total_centavos


def crear_pedido(db: "Session | None", payload: PedidoCreate) -> PedidoOut:
    monto_total_centavos = _resolve_monto_total_centavos(payload)
    precio_unitario_centavos = (
        payload.precio_unitario_centavos
        if payload.precio_unitario_centavos is not None
        else monto_total_centavos // payload.cantidad_balones
    )
    monto_pendiente_centavos = _resolve_monto_pendiente_centavos(
        payload, monto_total_centavos
    )
    fecha_entrega = payload.fecha_entrega or date_cls.today()

    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import (
            clientes as ddb_clientes,
        )
        from app.infrastructure.dynamodb.repositories import pedidos as ddb_pedidos
        from app.services import stock as service_stock

        cliente_id_str = str(payload.cliente_id)
        cliente = ddb_clientes.obtener_cliente_por_id(cliente_id_str)
        if cliente is None:
            raise ClienteNoExisteError("Cliente no existe")

        pagado_centavos = max(0, monto_total_centavos - monto_pendiente_centavos)
        pedido = ddb_pedidos.crear_pedido(
            cliente_id=cliente_id_str,
            cliente_alias=cliente.alias,
            fecha_entrega=fecha_entrega.isoformat(),
            cantidad_balones=payload.cantidad_balones,
            total_centavos=monto_total_centavos,
            pagado_centavos=pagado_centavos,
            tipo_balon=payload.tipo_balon,
            marca_balon=payload.marca_balon,
            precio_unitario_centavos=precio_unitario_centavos,
        )

        # Side effect de stock: si la jornada existe y no esta cerrada, registrar
        # salida. No fallar el pedido si la jornada no existe.
        try:
            service_stock.registrar_salida_por_pedido(
                db,
                fecha=fecha_entrega,
                cantidad_balones=payload.cantidad_balones,
                pedido_id=pedido.id,
                marca_balon=payload.marca_balon,
                tipo_balon=payload.tipo_balon,
            )
        except Exception:
            # El stock-side-effect no debe romper el pedido en DDB MVP.
            pass

        try:
            created_at = datetime.fromisoformat(pedido.created_at)
        except ValueError:
            created_at = datetime.utcnow()

        return PedidoOut(
            id=pedido.id,
            cliente_id=pedido.cliente_id,
            direccion_id=pedido.cliente_id,
            created_at=created_at,
            fecha_entrega=fecha_entrega,
            cantidad_balones=pedido.cantidad_balones,
            total_soles=_centavos_a_soles(pedido.total_centavos),
            tipo_balon=pedido.tipo_balon,
            marca_balon=pedido.marca_balon,
            precio_unitario_centavos=pedido.precio_unitario_centavos,
            monto_total_centavos=pedido.total_centavos,
            pagado=pedido.pagado,
            saldo_pendiente=_centavos_a_soles(pedido.pendiente_centavos),
            monto_pendiente_centavos=pedido.pendiente_centavos,
        )

    from app.infrastructure.repositories import clientes as repo_clientes
    from app.infrastructure.repositories import pedidos as repo_pedidos

    session = _require_db(db)
    cliente = repo_clientes.obtener_cliente(session, payload.cliente_id)
    if cliente is None:
        raise ClienteNoExisteError("Cliente no existe")

    total_soles = (
        payload.total_soles
        if payload.total_soles is not None
        else _centavos_a_soles(monto_total_centavos)
    )
    saldo_pendiente = (
        payload.saldo_pendiente
        if payload.saldo_pendiente is not None
        else _centavos_a_soles(monto_pendiente_centavos)
    )

    pedido = repo_pedidos.crear_pedido(
        db=session,
        cliente=cliente,
        fecha_entrega=fecha_entrega,
        cantidad_balones=payload.cantidad_balones,
        total_soles=total_soles,
        tipo_balon=payload.tipo_balon,
        marca_balon=payload.marca_balon,
        precio_unitario_centavos=precio_unitario_centavos,
        monto_total_centavos=monto_total_centavos,
        pagado=payload.pagado,
        saldo_pendiente=saldo_pendiente,
        monto_pendiente_centavos=monto_pendiente_centavos,
        observacion=payload.observacion,
    )
    return PedidoOut.model_validate(pedido, from_attributes=True)


def listar_pedidos_por_cliente(
    db: "Session | None", *, cliente_id: str, limit: int
) -> list[PedidoOut]:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import (
            clientes as ddb_clientes,
        )
        from app.infrastructure.dynamodb.repositories import pedidos as ddb_pedidos

        if ddb_clientes.obtener_cliente_por_id(cliente_id) is None:
            raise ClienteNoExisteError("Cliente no existe")

        items = ddb_pedidos.listar_pedidos_por_cliente(cliente_id, limit=limit)
        out: list[PedidoOut] = []
        for p in items:
            try:
                fecha = date_cls.fromisoformat(p.fecha_entrega)
            except ValueError:
                continue
            try:
                created_at = datetime.fromisoformat(p.created_at)
            except ValueError:
                created_at = datetime.utcnow()
            out.append(
                PedidoOut(
                    id=p.id,
                    cliente_id=p.cliente_id,
                    direccion_id=p.cliente_id,
                    created_at=created_at,
                    fecha_entrega=fecha,
                    cantidad_balones=p.cantidad_balones,
                    total_soles=_centavos_a_soles(p.total_centavos),
                    tipo_balon=p.tipo_balon,
                    marca_balon=p.marca_balon,
                    precio_unitario_centavos=p.precio_unitario_centavos,
                    monto_total_centavos=p.total_centavos,
                    pagado=p.pagado,
                    saldo_pendiente=_centavos_a_soles(p.pendiente_centavos),
                    monto_pendiente_centavos=p.pendiente_centavos,
                )
            )
        return out

    from app.infrastructure.repositories import clientes as repo_clientes
    from app.infrastructure.repositories import pedidos as repo_pedidos

    session = _require_db(db)
    if repo_clientes.obtener_cliente(session, cliente_id) is None:
        raise ClienteNoExisteError("Cliente no existe")

    rows = repo_pedidos.buscar_pedidos_por_cliente(
        session, cliente_id=cliente_id, limit=limit
    )
    return [PedidoOut.model_validate(p, from_attributes=True) for p in rows]
