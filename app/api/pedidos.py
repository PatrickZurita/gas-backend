from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.schemas.pedido import PedidoCreate, PedidoOut
from app.services import pedidos as service_pedidos
from app.services.errors import ClienteNoExisteError

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
