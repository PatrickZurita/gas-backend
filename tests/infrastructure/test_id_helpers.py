import pytest

from app.infrastructure.repositories._id_helpers import to_pg_id


def test_to_pg_id_acepta_int():
    assert to_pg_id(42) == 42


def test_to_pg_id_acepta_string_numerico():
    assert to_pg_id("42") == 42


def test_to_pg_id_rechaza_uuid_string():
    with pytest.raises(ValueError, match="no es valido para PostgreSQL"):
        to_pg_id("a1b2c3d4-e5f6-47g8-h9i0-j1k2l3m4n5o6")


def test_to_pg_id_rechaza_string_no_numerico():
    with pytest.raises(ValueError, match="no es valido para PostgreSQL"):
        to_pg_id("abc")


def test_to_pg_id_rechaza_otros_tipos():
    with pytest.raises(TypeError):
        to_pg_id(1.5)  # type: ignore[arg-type]
