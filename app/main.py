import os

from fastapi import FastAPI
from app.api.catalogos import router as catalogos_router
from app.api.clientes import router as clientes_router
from app.api.demanda_perdida import router as demanda_perdida_router
from app.api.pedidos import router as pedidos_router
from app.api.reportes import router as reportes_router
from app.api.stock import router as stock_router
from app.api.bi import router as bi_router

app = FastAPI(title="Gas Backend", version="0.1.0")


@app.middleware("http")
async def no_cache_bi(request, call_next):
    response = await call_next(request)
    if request.url.path == "/bi/v1" or request.url.path.startswith("/bi/v1/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "gas-api",
        "environment": os.getenv("APP_ENV", "dev"),
        "version": os.getenv("APP_VERSION", "dev"),
    }


app.include_router(clientes_router)
app.include_router(pedidos_router)
app.include_router(reportes_router)
app.include_router(stock_router)
app.include_router(catalogos_router)
app.include_router(demanda_perdida_router)
app.include_router(bi_router)
