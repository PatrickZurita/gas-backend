from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.deps import DbSession
from app.schemas.cliente import ClienteCreate, ClienteOut, ClienteRecienteOut
from app.services import clientes as service_clientes
from app.services.errors import AliasDuplicadoError

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.post("/", response_model=ClienteOut, status_code=status.HTTP_201_CREATED)
def crear_cliente(payload: ClienteCreate, db: DbSession) -> ClienteOut:
    try:
        return service_clientes.crear_cliente(
            db,
            alias=payload.alias.strip(),
            telefono=payload.telefono.strip(),
        )
    except AliasDuplicadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(
    "/search", response_model=list[ClienteOut], status_code=status.HTTP_200_OK
)
def search_clientes(
    db: DbSession,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=50),
) -> list[ClienteOut]:
    q_clean = q.strip()
    if not q_clean:
        raise HTTPException(status_code=422, detail="q no puede ser vacío.")

    try:
        return service_clientes.buscar_clientes(db, q=q_clean, limit=limit)
    except RuntimeError:
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Error interno al buscar clientes."
        )


@router.get(
    "/recientes",
    response_model=list[ClienteRecienteOut],
    status_code=status.HTTP_200_OK,
)
def listar_clientes_recientes(
    db: DbSession,
    limit: int = Query(10, ge=1, le=50),
) -> list[ClienteRecienteOut]:
    return service_clientes.listar_clientes_recientes(db, limit=limit)


@router.get(
    "/{cliente_id}", response_model=ClienteOut, status_code=status.HTTP_200_OK
)
def obtener_cliente(
    db: DbSession,
    cliente_id: str = Path(..., min_length=1, max_length=64),
) -> ClienteOut:
    cliente = service_clientes.obtener_cliente_por_id(db, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no existe")
    return cliente
