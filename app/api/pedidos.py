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

    return repo_pedidos.crear_pedido(
        db=db,
        cliente=cliente,
        fecha_pedido=payload.fecha_pedido,
        cantidad_balones=payload.cantidad_balones,
        total_soles=payload.total_soles,
        pagado=payload.pagado,
        saldo_pendiente=payload.saldo_pendiente,
        observacion=payload.observacion,
    )

@router.get("", response_model=list[PedidoOut])
def listar_pedidos(
    db: DbSession,
    cliente_id: int = Query(..., ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    cliente = repo_clientes.obtener_cliente(db, cliente_id)
    if not cliente:
        raise HTTPException(404, "Cliente no existe")

    return repo_pedidos.buscar_pedidos_por_cliente(db, cliente_id=cliente_id, limit=limit)

