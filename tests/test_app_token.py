"""Tests del helper `require_app_token`.

`/health` permanece publico. La dependencia solo se activa cuando
`APP_SHARED_TOKEN` esta presente en el entorno.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import security


@pytest.fixture()
def app_with_protected_route():
    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = security.require_app_token):  # noqa: B008
        return {"ok": True}

    # Forma estandar FastAPI: usar Depends
    from fastapi import Depends

    app2 = FastAPI()

    @app2.get("/protected")
    def protected2(_: None = Depends(security.require_app_token)):
        return {"ok": True}

    return app2


def test_sin_token_configurado_endpoint_responde(app_with_protected_route, monkeypatch):
    monkeypatch.delenv(security.APP_SHARED_TOKEN_ENV, raising=False)
    response = TestClient(app_with_protected_route).get("/protected")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_con_token_configurado_y_header_correcto(app_with_protected_route, monkeypatch):
    monkeypatch.setenv(security.APP_SHARED_TOKEN_ENV, "secreto-test")
    response = TestClient(app_with_protected_route).get(
        "/protected", headers={"x-app-token": "secreto-test"}
    )
    assert response.status_code == 200


def test_con_token_configurado_y_header_incorrecto(app_with_protected_route, monkeypatch):
    monkeypatch.setenv(security.APP_SHARED_TOKEN_ENV, "secreto-test")
    response = TestClient(app_with_protected_route).get(
        "/protected", headers={"x-app-token": "otro"}
    )
    assert response.status_code == 401


def test_con_token_configurado_sin_header(app_with_protected_route, monkeypatch):
    monkeypatch.setenv(security.APP_SHARED_TOKEN_ENV, "secreto-test")
    response = TestClient(app_with_protected_route).get("/protected")
    assert response.status_code == 401


def test_app_token_configured_refleja_estado(monkeypatch):
    monkeypatch.delenv(security.APP_SHARED_TOKEN_ENV, raising=False)
    assert security.app_token_configured() is False
    monkeypatch.setenv(security.APP_SHARED_TOKEN_ENV, "x")
    assert security.app_token_configured() is True
    monkeypatch.setenv(security.APP_SHARED_TOKEN_ENV, "   ")
    assert security.app_token_configured() is False
