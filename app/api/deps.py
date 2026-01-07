from collections.abc import Generator
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from typing import Annotated
from fastapi import Depends

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        
DbSession = Annotated[Session, Depends(get_db)]

