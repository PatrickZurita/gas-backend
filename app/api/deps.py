from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.storage import is_dynamodb_enabled
from app.db.session import SessionLocal


def get_db() -> Generator[Session | None, None, None]:
    """Provee sesion PostgreSQL cuando el storage es PostgreSQL.

    En modo `APP_STORAGE_BACKEND=dynamodb` no abre `SessionLocal()`, lo que
    permite que la Lambda arranque y atienda endpoints sin `DATABASE_URL`.
    Los routers que dependan de la sesion deben tolerar `None` o ser
    despachados por la capa `app.services.*` segun el storage activo.

    Los tests siguen pudiendo sobrescribir esta dependencia via
    `app.dependency_overrides[get_db]`.
    """
    if is_dynamodb_enabled():
        yield None
        return

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session | None, Depends(get_db)]
