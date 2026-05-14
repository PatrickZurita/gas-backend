from fastapi import APIRouter, Path, Query, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.schemas.cliente import ClienteCreate, ClienteOut, ClienteRecienteOut
from app.infrastructure.repositories import clientes as repo

router = APIRouter(prefix="/clientes", tags=["clientes"])

def _cliente_to_out(cliente) -> ClienteOut:
    return ClienteOut(
        id=cliente.id,
        alias=cliente.alias,
        telefono=cliente.telefono,
        direccion=cliente.alias,
    )

def _monto_total_centavos(pedido) -> int:
    if pedido.monto_total_centavos is not None:
        return pedido.monto_total_centavos
    return int(pedido.total_soles * 100)

@router.post("/", response_model=ClienteOut, status_code=status.HTTP_201_CREATED)
def crear_cliente(payload: ClienteCreate, db: DbSession) -> ClienteOut:
    try:
        cliente = repo.crear_cliente(
            db,
            alias=payload.alias.strip(),
            telefono=payload.telefono.strip(),
        )
        return _cliente_to_out(cliente)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un cliente con ese alias.",
        )

@router.get("/search", response_model=list[ClienteOut], status_code=status.HTTP_200_OK)
def search_clientes(
    db: DbSession,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=50),
) -> list[ClienteOut]:
    q_clean = q.strip()
    if not q_clean:
        raise HTTPException(status_code=422, detail="q no puede ser vacío.")

    try:
        clientes = repo.buscar_clientes(db, q=q_clean, limit=limit)
        return [_cliente_to_out(cliente) for cliente in clientes]
    except Exception:
        raise HTTPException(status_code=500, detail="Error interno al buscar clientes.")

@router.get(
    "/recientes",
    response_model=list[ClienteRecienteOut],
    status_code=status.HTTP_200_OK,
)
def listar_clientes_recientes(
    db: DbSession,
    limit: int = Query(10, ge=1, le=50),
) -> list[ClienteRecienteOut]:
    recientes = repo.listar_clientes_recientes(db, limit=limit)
    return [
        ClienteRecienteOut(
            id=cliente.id,
            alias=cliente.alias,
            telefono=cliente.telefono,
            direccion=cliente.alias,
            ultimo_pedido_fecha=pedido.fecha_entrega,
            ultimo_total_centavos=_monto_total_centavos(pedido),
        )
        for cliente, pedido in recientes
    ]
    
@router.get("/{cliente_id}", response_model=ClienteOut, status_code=status.HTTP_200_OK)
def obtener_cliente(
    db: DbSession,
    cliente_id: str = Path(..., min_length=1, max_length=64),
) -> ClienteOut:
    cliente = repo.obtener_cliente_por_id(db, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no existe")
    return _cliente_to_out(cliente)
