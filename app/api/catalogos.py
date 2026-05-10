from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.pedido import (
    MARCA_BALON_PETROPERU,
    MARCA_BALON_SOLGAS,
    TIPO_BALON_NORMAL,
    TIPO_BALON_PREMIUM,
)

router = APIRouter(prefix="/catalogos", tags=["catalogos"])


class CatalogoItemOut(BaseModel):
    codigo: str
    nombre: str


class CatalogoOut(BaseModel):
    items: list[CatalogoItemOut]


@router.get("/tipos-balon", response_model=CatalogoOut)
def listar_tipos_balon() -> CatalogoOut:
    return CatalogoOut(
        items=[
            CatalogoItemOut(codigo=TIPO_BALON_NORMAL, nombre="Normal"),
            CatalogoItemOut(codigo=TIPO_BALON_PREMIUM, nombre="Premium"),
        ]
    )


@router.get("/marcas-balon", response_model=CatalogoOut)
def listar_marcas_balon() -> CatalogoOut:
    return CatalogoOut(
        items=[
            CatalogoItemOut(codigo=MARCA_BALON_SOLGAS, nombre="Solgas"),
            CatalogoItemOut(codigo=MARCA_BALON_PETROPERU, nombre="Petroperu"),
        ]
    )
