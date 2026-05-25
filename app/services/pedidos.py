"""Service `pedidos` con dispatch PostgreSQL/DynamoDB."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

from app.core.storage import is_dynamodb_enabled
from app.core.time import fecha_hoy_lima
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
    fecha_entrega = payload.fecha_entrega or fecha_hoy_lima()

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
            peso_balon_kg=payload.peso_balon_kg,
            metodo_pago=payload.metodo_pago if payload.pagado else None,
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
                peso_balon_kg=payload.peso_balon_kg,
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
            estado=pedido.estado,
            anulado_at=_parse_dt(pedido.anulado_at),
            anulado_motivo=pedido.anulado_motivo,
            peso_balon_kg=pedido.peso_balon_kg,
            metodo_pago=getattr(pedido, "metodo_pago", None),
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
        peso_balon_kg=payload.peso_balon_kg,
        metodo_pago=payload.metodo_pago,
    )
    return PedidoOut.model_validate(pedido, from_attributes=True)


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


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


class PedidoNoExisteError(Exception):
    """Pedido no encontrado (404)."""


class PedidoAnuladoNoEditableError(Exception):
    """Intento de editar pedido anulado (409)."""


def anular_pedido(
    db: "Session | None",
    pedido_id: int | str,
    *,
    motivo: str | None = None,
) -> PedidoOut:
    """Marca el pedido como ANULADO y compensa stock (idempotente).

    Si el pedido ya estaba ANULADO no se vuelve a compensar el stock; el
    endpoint devuelve 200 con el estado actual. Esto evita doble reversa en
    reintentos del cliente.
    """
    if is_dynamodb_enabled():
        return _anular_pedido_ddb(pedido_id, motivo=motivo)

    from app.infrastructure.repositories import pedidos as repo_pedidos
    from app.models.models import Pedido as PedidoModel

    session = _require_db(db)
    pg_id = _safe_int(pedido_id)
    if pg_id is None or session.get(PedidoModel, pg_id) is None:
        raise PedidoNoExisteError(f"Pedido {pedido_id} no existe")

    pedido = repo_pedidos.anular_pedido(session, pg_id, motivo=motivo)
    return PedidoOut.model_validate(pedido, from_attributes=True)


def patch_pedido(
    db: "Session | None",
    pedido_id: int | str,
    *,
    cantidad_balones: int | None = None,
    precio_unitario_centavos: int | None = None,
    monto_total_centavos: int | None = None,
    monto_pendiente_centavos: int | None = None,
    pagado: bool | None = None,
    fecha_entrega: date_cls | None = None,
    peso_balon_kg: int | None = None,
    metodo_pago: str | None = None,
    motivo_edicion: str | None = None,
) -> PedidoOut:
    if is_dynamodb_enabled():
        return _patch_pedido_ddb(
            pedido_id=pedido_id,
            cantidad_balones=cantidad_balones,
            precio_unitario_centavos=precio_unitario_centavos,
            monto_total_centavos=monto_total_centavos,
            monto_pendiente_centavos=monto_pendiente_centavos,
            pagado=pagado,
            fecha_entrega=fecha_entrega,
            peso_balon_kg=peso_balon_kg,
            metodo_pago=metodo_pago,
            motivo_edicion=motivo_edicion,
        )

    from app.infrastructure.repositories import pedidos as repo_pedidos
    from app.models.models import Pedido as PedidoModel

    session = _require_db(db)
    pg_id = _safe_int(pedido_id)
    if pg_id is None or session.get(PedidoModel, pg_id) is None:
        raise PedidoNoExisteError(f"Pedido {pedido_id} no existe")

    try:
        pedido = repo_pedidos.patch_pedido(
            session,
            pg_id,
            cantidad_balones=cantidad_balones,
            precio_unitario_centavos=precio_unitario_centavos,
            monto_total_centavos=monto_total_centavos,
            monto_pendiente_centavos=monto_pendiente_centavos,
            pagado=pagado,
            fecha_entrega=fecha_entrega,
            peso_balon_kg=peso_balon_kg,
            metodo_pago=metodo_pago,
            motivo_edicion=motivo_edicion,
        )
    except repo_pedidos.PedidoAnuladoEditableError as exc:
        raise PedidoAnuladoNoEditableError(str(exc)) from exc

    return PedidoOut.model_validate(pedido, from_attributes=True)


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------


def _anular_pedido_ddb(pedido_id: int | str, *, motivo: str | None) -> PedidoOut:
    from app.infrastructure.dynamodb.repositories import (
        movimientos_stock as ddb_movs,
    )
    from app.infrastructure.dynamodb.repositories import pedidos as ddb_pedidos
    from app.infrastructure.dynamodb.repositories import (
        stock_jornadas as ddb_jornadas,
    )

    pedido_id_str = str(pedido_id)
    actual = ddb_pedidos.obtener_pedido(pedido_id_str)
    if actual is None:
        raise PedidoNoExisteError(f"Pedido {pedido_id} no existe")

    ya_anulado = actual.estado == "ANULADO"
    pedido = ddb_pedidos.anular_pedido(pedido_id_str, motivo=motivo)
    if pedido is None:
        raise PedidoNoExisteError(f"Pedido {pedido_id} no existe")

    # Compensar stock solo en la primera anulacion (idempotencia).
    if not ya_anulado:
        jornada = ddb_jornadas.obtener_jornada(pedido.fecha_entrega)
        if jornada is not None and not jornada.cerrado:
            try:
                resultante = ddb_jornadas.aplicar_delta(
                    pedido.fecha_entrega, pedido.cantidad_balones
                )
                ddb_movs.registrar_movimiento(
                    fecha=pedido.fecha_entrega,
                    tipo="REVERSA_ANULACION",
                    cantidad_delta=pedido.cantidad_balones,
                    stock_resultante=resultante,
                    pedido_id=pedido.id,
                    observacion="Reversa por anulacion de pedido",
                    peso_balon_kg=pedido.peso_balon_kg,
                )
            except ValueError:
                # Stock no puede compensarse (caso borde). El pedido queda
                # anulado igual; el reporte excluira anulados de las metricas.
                pass

    return _ddb_pedido_to_out(pedido)


def _patch_pedido_ddb(
    *,
    pedido_id: int | str,
    cantidad_balones: int | None,
    precio_unitario_centavos: int | None,
    monto_total_centavos: int | None,
    monto_pendiente_centavos: int | None,
    pagado: bool | None,
    fecha_entrega: date_cls | None,
    peso_balon_kg: int | None,
    metodo_pago: str | None,
    motivo_edicion: str | None,
) -> PedidoOut:
    from app.infrastructure.dynamodb.repositories import (
        movimientos_stock as ddb_movs,
    )
    from app.infrastructure.dynamodb.repositories import pedidos as ddb_pedidos
    from app.infrastructure.dynamodb.repositories import (
        stock_jornadas as ddb_jornadas,
    )

    pedido_id_str = str(pedido_id)
    actual = ddb_pedidos.obtener_pedido(pedido_id_str)
    if actual is None:
        raise PedidoNoExisteError(f"Pedido {pedido_id} no existe")
    if actual.estado == "ANULADO":
        raise PedidoAnuladoNoEditableError(
            "No se puede editar un pedido anulado."
        )

    cantidad_vieja = actual.cantidad_balones
    fecha_vieja = actual.fecha_entrega
    peso_viejo = actual.peso_balon_kg

    fields: dict = {}
    if cantidad_balones is not None:
        fields["cantidad_balones"] = cantidad_balones
    if precio_unitario_centavos is not None:
        fields["precio_unitario_centavos"] = precio_unitario_centavos
    if monto_total_centavos is not None:
        fields["total_centavos"] = monto_total_centavos
    if monto_pendiente_centavos is not None:
        # Derivamos pagado_centavos para mantener invariante.
        total = monto_total_centavos or actual.total_centavos
        fields["pagado_centavos"] = max(0, total - monto_pendiente_centavos)
    if pagado is not None:
        # Si se fuerza pagado, ajustamos pagado_centavos al total.
        total = monto_total_centavos or actual.total_centavos
        fields["pagado_centavos"] = total if pagado else 0
    if fecha_entrega is not None:
        fields["fecha_entrega"] = fecha_entrega.isoformat()
    if peso_balon_kg is not None:
        fields["peso_balon_kg"] = peso_balon_kg
    if pagado is False:
        fields["metodo_pago"] = None
    elif metodo_pago is not None:
        fields["metodo_pago"] = metodo_pago

    if not fields:
        return _ddb_pedido_to_out(actual)

    pedido = ddb_pedidos.patch_pedido(pedido_id_str, **fields)
    if pedido is None:
        raise PedidoNoExisteError(f"Pedido {pedido_id} no existe")

    stock_impactado = (
        cantidad_balones is not None
        or fecha_entrega is not None
        or peso_balon_kg is not None
    )
    if stock_impactado:
        # Reversa en jornada/peso viejo.
        jornada_vieja = ddb_jornadas.obtener_jornada(fecha_vieja)
        if jornada_vieja is not None and not jornada_vieja.cerrado:
            try:
                resultante = ddb_jornadas.aplicar_delta(fecha_vieja, cantidad_vieja)
                ddb_movs.registrar_movimiento(
                    fecha=fecha_vieja,
                    tipo="REVERSA_ANULACION",
                    cantidad_delta=cantidad_vieja,
                    stock_resultante=resultante,
                    pedido_id=pedido.id,
                    observacion=motivo_edicion or "Reversa por edicion de pedido",
                    peso_balon_kg=peso_viejo,
                )
            except ValueError:
                pass
        # Nueva salida en jornada/peso nuevo.
        jornada_nueva = ddb_jornadas.obtener_jornada(pedido.fecha_entrega)
        if jornada_nueva is not None and not jornada_nueva.cerrado:
            try:
                resultante = ddb_jornadas.aplicar_delta(
                    pedido.fecha_entrega, -pedido.cantidad_balones
                )
                ddb_movs.registrar_movimiento(
                    fecha=pedido.fecha_entrega,
                    tipo="SALIDA_PEDIDO",
                    cantidad_delta=-pedido.cantidad_balones,
                    stock_resultante=resultante,
                    pedido_id=pedido.id,
                    observacion="Salida por edicion de pedido",
                    peso_balon_kg=pedido.peso_balon_kg,
                )
            except ValueError:
                pass

    return _ddb_pedido_to_out(pedido)


def _ddb_pedido_to_out(pedido) -> PedidoOut:
    try:
        created_at = datetime.fromisoformat(pedido.created_at)
    except (TypeError, ValueError):
        created_at = datetime.utcnow()
    try:
        fecha = date_cls.fromisoformat(pedido.fecha_entrega)
    except (TypeError, ValueError):
        fecha = fecha_hoy_lima()
    return PedidoOut(
        id=pedido.id,
        cliente_id=pedido.cliente_id,
        direccion_id=pedido.cliente_id,
        created_at=created_at,
        fecha_entrega=fecha,
        cantidad_balones=pedido.cantidad_balones,
        total_soles=_centavos_a_soles(pedido.total_centavos),
        tipo_balon=pedido.tipo_balon,
        marca_balon=pedido.marca_balon,
        precio_unitario_centavos=pedido.precio_unitario_centavos,
        monto_total_centavos=pedido.total_centavos,
        pagado=pedido.pagado,
        saldo_pendiente=_centavos_a_soles(pedido.pendiente_centavos),
        monto_pendiente_centavos=pedido.pendiente_centavos,
        estado=pedido.estado,
        anulado_at=_parse_dt(pedido.anulado_at),
        anulado_motivo=pedido.anulado_motivo,
        peso_balon_kg=pedido.peso_balon_kg,
        metodo_pago=getattr(pedido, "metodo_pago", None),
    )


def _safe_int(value: int | str) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
