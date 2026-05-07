from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


@lru_cache
def get_engine():
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for database endpoints.")
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True)


@lru_cache
def get_session_factory():
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=get_engine(),
    )


def SessionLocal():
    return get_session_factory()()
