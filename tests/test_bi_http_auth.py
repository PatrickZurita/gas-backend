"""Synthetic BI HTTP access tests: no external Google or PostgreSQL calls."""

from __future__ import annotations

import json
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core import bi_auth, bi_db
from app.main import app
from app.services import bi as bi_service


@pytest.fixture(autouse=True)
def clean_bi_config(monkeypatch):
    monkeypatch.delenv("BI_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("BI_GOOGLE_SUB_ROLES", raising=False)
    monkeypatch.delenv("BI_DATABASE_URL", raising=False)
    app.dependency_overrides.clear()
    bi_db._engine.cache_clear()
    yield
    app.dependency_overrides.clear()
    bi_db._engine.cache_clear()


def _url():
    return "/bi/v1/corte?desde=2026-10-01&hasta=2026-10-02&peso_balon_kg=todos"


def _configurar(monkeypatch, roles=None):
    monkeypatch.setenv("BI_GOOGLE_CLIENT_ID", "test-web-client.apps.googleusercontent.com")
    monkeypatch.setenv("BI_GOOGLE_SUB_ROLES", json.dumps(roles or {"sub-sintetico": "viewer"}))


def _claims(**cambios):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-web-client.apps.googleusercontent.com",
        "exp": int(time.time()) + 3600,
        "sub": "sub-sintetico",
    }
    claims.update(cambios)
    return claims


def _autorizacion():
    return {"Authorization": "Bearer token-sintetico"}


def test_sin_configuracion_falla_cerrado_y_no_afecta_health():
    cliente = TestClient(app)
    respuesta = cliente.get(_url())
    assert respuesta.status_code == 503
    assert respuesta.headers["cache-control"] == "no-store"
    assert cliente.get("/health").status_code == 200


def test_sin_token_y_token_invalido(monkeypatch):
    _configurar(monkeypatch)
    cliente = TestClient(app)
    respuesta = cliente.get(_url())
    assert respuesta.status_code == 401
    assert respuesta.headers["www-authenticate"] == "Bearer"
    assert cliente.get(_url(), headers={"x-app-token": "cualquiera", "x-bi-role": "owner"}).status_code == 401

    def rechazar(*args, **kwargs):
        raise ValueError("firma inválida sintética")

    monkeypatch.setattr(bi_auth.google_id_token, "verify_oauth2_token", rechazar)
    respuesta = cliente.get(_url(), headers=_autorizacion())
    assert respuesta.status_code == 401
    assert respuesta.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("cambios", [
    {"iss": "https://otro.example"},
    {"aud": "otro-cliente"},
    {"exp": 0},
    {"sub": ""},
])
def test_claims_de_google_requeridos(monkeypatch, cambios):
    _configurar(monkeypatch)
    monkeypatch.setattr(
        bi_auth.google_id_token, "verify_oauth2_token",
        lambda *a, **k: _claims(**cambios),
    )
    assert TestClient(app).get(_url(), headers=_autorizacion()).status_code == 401


def test_sub_no_autorizado_es_403_y_rol_revocado_en_siguiente_request(monkeypatch):
    _configurar(monkeypatch, {"otro-sub": "viewer"})
    monkeypatch.setattr(
        bi_auth.google_id_token, "verify_oauth2_token",
        lambda *a, **k: _claims(sub="otro-sub"),
    )
    cliente = TestClient(app)
    # First request has an allowed identity; the missing BI DB correctly blocks it.
    assert cliente.get(_url(), headers=_autorizacion()).status_code == 503
    monkeypatch.setenv("BI_GOOGLE_SUB_ROLES", json.dumps({"sub-sintetico": "viewer"}))
    assert cliente.get(_url(), headers=_autorizacion()).status_code == 403


def test_token_valido_no_usa_db_operativa_si_falta_fuente_bi(monkeypatch):
    _configurar(monkeypatch)
    monkeypatch.setattr(
        bi_auth.google_id_token, "verify_oauth2_token",
        lambda *a, **k: _claims(),
    )
    respuesta = TestClient(app).get(_url(), headers=_autorizacion())
    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == "Fuente BI no configurada."


def test_viewer_recibe_solo_agregados_con_filtros_explicitados(monkeypatch):
    _configurar(monkeypatch)
    monkeypatch.setattr(
        bi_auth.google_id_token, "verify_oauth2_token",
        lambda *a, **k: _claims(),
    )
    monkeypatch.setattr(bi_service, "fecha_hoy_lima", lambda: date(2026, 10, 14))
    monkeypatch.setattr(bi_service, "is_dynamodb_enabled", lambda: False)
    monkeypatch.setattr(bi_service.repo_bi, "listar_activos_en_rango", lambda *a, **k: [])
    monkeypatch.setattr(
        bi_service.repo_bi, "listar_dias_activos_de_compradores", lambda *a, **k: [],
    )
    app.dependency_overrides[bi_db.get_bi_db] = lambda: object()
    respuesta = TestClient(app).get(_url(), headers=_autorizacion())
    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    cuerpo = respuesta.json()
    assert cuerpo["version_definiciones"] == "bi-v1.1"
    assert cuerpo["filtros"] == {
        "desde": "2026-10-01", "hasta": "2026-10-02",
        "peso_balon_kg": "todos", "estado": "ACTIVO",
    }
    assert cuerpo["n_pedidos_base"] == 0
    assert "clientes" not in cuerpo
    assert "pedidos" not in cuerpo


@pytest.mark.parametrize("url", [
    "/bi/v1/corte?desde=2026-10-03&hasta=2026-10-01",
    "/bi/v1/corte?desde=2025-01-01&hasta=2026-10-01",
    "/bi/v1/corte?desde=2026-10-01&hasta=2026-10-02&peso_balon_kg=25",
])
def test_filtros_fuera_de_contrato_dan_422(monkeypatch, url):
    _configurar(monkeypatch)
    monkeypatch.setattr(
        bi_auth.google_id_token, "verify_oauth2_token",
        lambda *a, **k: _claims(),
    )
    app.dependency_overrides[bi_db.get_bi_db] = lambda: object()
    respuesta = TestClient(app).get(url, headers=_autorizacion())
    assert respuesta.status_code == 422
    assert respuesta.headers["cache-control"] == "no-store"


def test_dsn_bi_exige_rol_neon_y_tls():
    valid = "postgresql://gas_readonly:x@ep-unit-test.neon.tech/gas?sslmode=require"
    assert bi_db._validar_dsn(valid).username == "gas_readonly"
    for dsn in (
        "postgresql://owner:x@ep-unit-test.neon.tech/gas?sslmode=require",
        "postgresql://gas_readonly:x@ep-unit-test.neon.tech/gas?sslmode=disable",
        "sqlite:///:memory:",
    ):
        with pytest.raises(Exception) as exc:
            bi_db._validar_dsn(dsn)
        assert getattr(exc.value, "status_code", None) == 503
        assert "x@" not in str(exc.value)


def test_barreras_rechazan_privilegio_escritura():
    base = {
        "usuario": "gas_readonly", "usuario_sesion": "gas_readonly",
        "solo_lectura": "on", "aislamiento": "repeatable read",
        "pedidos_existe": True, "puede_leer": True,
        **{campo: False for campo in bi_db._PROHIBIDOS},
    }
    bi_db._exigir_barreras(base)
    for campo in bi_db._PROHIBIDOS:
        alterado = {**base, campo: True}
        with pytest.raises(Exception) as exc:
            bi_db._exigir_barreras(alterado)
        assert getattr(exc.value, "status_code", None) == 503
