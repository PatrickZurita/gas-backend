import os
from enum import StrEnum


class StorageBackend(StrEnum):
    POSTGRES = "postgres"
    DYNAMODB = "dynamodb"


def get_storage_backend() -> StorageBackend:
    raw_value = os.getenv("APP_STORAGE_BACKEND", StorageBackend.POSTGRES.value)
    normalized = raw_value.strip().lower()
    if normalized == StorageBackend.DYNAMODB.value:
        return StorageBackend.DYNAMODB
    return StorageBackend.POSTGRES


def is_dynamodb_enabled() -> bool:
    return get_storage_backend() == StorageBackend.DYNAMODB
