import os

from fastapi import FastAPI
from app.api.clientes import router as clientes_router
from app.api.pedidos import router as pedidos_router

app = FastAPI(title="Gas Backend", version="0.1.0")


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
