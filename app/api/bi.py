"""Router reservado para BI; todavía no se monta ni expone endpoints."""

from fastapi import APIRouter, Depends

from app.core.bi_auth import require_bi_principal

# La identidad es obligatoria para todas las rutas que se añadan aquí.
# Cada operación debe declarar además su permiso con require_bi_permission.
router = APIRouter(
    prefix="/bi/v1",
    tags=["bi"],
    dependencies=[Depends(require_bi_principal)],
)
