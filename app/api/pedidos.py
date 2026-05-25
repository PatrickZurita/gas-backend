from fastapi import APIRouter, HTTPException, Path, Query

from app.api.deps import DbSession
from app.schemas.pedido import (
    PedidoAnularRequest,
    PedidoCreate,
    PedidoOut,
    PedidoPatch,
)
from app.services import pedidos as service_pedidos
from app.services.errors import ClienteNoExisteError
from app.services.pedidos import PedidoAnuladoNoEditableError, PedidoNoExisteError

router = APIRouter(prefix="/pedidos", tags=["pedidos"])


@router.post("", response_model=PedidoOut, status_code=201)
def crear_pedido(payload: PedidoCreate, db: DbSession) -> PedidoOut:
    try:
        return service_pedidos.crear_pedido(db, payload)
    except ClienteNoExisteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[PedidoOut])
def listar_pedidos(
    db: DbSession,
    cliente_id: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(50, ge=1, le=200),
) -> list[PedidoOut]:
    try:
        return service_pedidos.listar_pedidos_por_cliente(
            db, cliente_id=cliente_id, limit=limit
        )
    except ClienteNoExisteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{pedido_id}/anular", response_model=PedidoOut)
def anular_pedido(
    db: DbSession,
    pedido_id: int = Path(..., ge=1),
    payload: PedidoAnularRequest | None = None,
) -> PedidoOut:
    motivo = payload.motivo if payload is not None else None
    try:
        return service_pedidos.anular_pedido(db, pedido_id, motivo=motivo)
    except PedidoNoExisteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{pedido_id}", response_model=PedidoOut)
def patch_pedido(
    payload: PedidoPatch,
    db: DbSession,
    pedido_id: int = Path(..., ge=1),
) -> PedidoOut:
    try:
        return service_pedidos.patch_pedido(
            db,
            pedido_id,
            cantidad_balones=payload.cantidad_balones,
            precio_unitario_centavos=payload.precio_unitario_centavos,
            monto_total_centavos=payload.monto_total_centavos,
            monto_pendiente_centavos=payload.monto_pendiente_centavos,
            pagado=payload.pagado,
            fecha_entrega=payload.fecha_entrega,
            peso_balon_kg=payload.peso_balon_kg,
            metodo_pago=payload.metodo_pago,
            motivo_edicion=payload.motivo_edicion,
        )
    except PedidoNoExisteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PedidoAnuladoNoEditableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
