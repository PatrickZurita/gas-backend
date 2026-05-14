from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.schemas.pedido import PedidoCreate, PedidoOut
from app.infrastructure.repositories import clientes as repo_clientes
from app.infrastructure.repositories import pedidos as repo_pedidos

router = APIRouter(prefix="/pedidos", tags=["pedidos"])


@router.post("", response_model=PedidoOut, status_code=201)
def crear_pedido(payload: PedidoCreate, db: DbSession):
    cliente = repo_clientes.obtener_cliente(db, payload.cliente_id)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no existe")

    fecha_entrega = payload.fecha_entrega or date.today()
    monto_total_centavos = _resolve_monto_total_centavos(payload)
    precio_unitario_centavos = (
        payload.precio_unitario_centavos
        if payload.precio_unitario_centavos is not None
        else monto_total_centavos // payload.cantidad_balones
    )
    monto_pendiente_centavos = _resolve_monto_pendiente_centavos(
        payload,
        monto_total_centavos,
    )

    return repo_pedidos.crear_pedido(
        db=db,
        cliente=cliente,
        fecha_entrega=fecha_entrega,
        cantidad_balones=payload.cantidad_balones,
        total_soles=(
            payload.total_soles
            if payload.total_soles is not None
            else _centavos_a_soles(monto_total_centavos)
        ),
        tipo_balon=payload.tipo_balon,
        marca_balon=payload.marca_balon,
        precio_unitario_centavos=precio_unitario_centavos,
        monto_total_centavos=monto_total_centavos,
        pagado=payload.pagado,
        saldo_pendiente=(
            payload.saldo_pendiente
            if payload.saldo_pendiente is not None
            else _centavos_a_soles(monto_pendiente_centavos)
        ),
        monto_pendiente_centavos=monto_pendiente_centavos,
        observacion=payload.observacion,
    )

@router.get("", response_model=list[PedidoOut])
def listar_pedidos(
    db: DbSession,
    cliente_id: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(50, ge=1, le=200),
):
    cliente = repo_clientes.obtener_cliente(db, cliente_id)
    if not cliente:
        raise HTTPException(404, "Cliente no existe")

    return repo_pedidos.buscar_pedidos_por_cliente(db, cliente_id=cliente_id, limit=limit)


def _resolve_monto_total_centavos(payload: PedidoCreate) -> int:
    if payload.monto_total_centavos is not None:
        return payload.monto_total_centavos
    if payload.precio_unitario_centavos is not None:
        return payload.precio_unitario_centavos * payload.cantidad_balones
    return _soles_a_centavos(payload.total_soles or Decimal("0"))


def _resolve_monto_pendiente_centavos(
    payload: PedidoCreate,
    monto_total_centavos: int,
) -> int:
    if payload.monto_pendiente_centavos is not None:
        return payload.monto_pendiente_centavos
    if payload.saldo_pendiente is not None:
        return _soles_a_centavos(payload.saldo_pendiente)
    return 0 if payload.pagado else monto_total_centavos


def _soles_a_centavos(monto_soles: Decimal) -> int:
    return int((monto_soles * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _centavos_a_soles(monto_centavos: int) -> Decimal:
    return (Decimal(monto_centavos) / Decimal(100)).quantize(Decimal("0.01"))

