"""Nominal HTTP security and parity checks with invented SQLite rows only."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import bi_nominal as bi_api
from app.core import bi_auth, bi_db
from app.db.base import Base
from app.main import app
from app.models.models import Cliente, Direccion, Pedido
from app.services import bi_nominal as bi_service


def _cliente_web():
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def _auth():
    return {"Authorization": "Bearer token-inventado"}


@pytest.fixture(autouse=True)
def aislar_configuracion(monkeypatch):
    for key in (
        "BI_NOMINAL_LOCAL_ENABLED", "BI_NOMINAL_AUDIT_DB_PATH",
        "BI_GOOGLE_CLIENT_ID", "BI_GOOGLE_SUB_ROLES", "BI_DATABASE_URL", "APP_ENV",
    ):
        monkeypatch.delenv(key, raising=False)
    app.dependency_overrides.clear()
    bi_db._engine.cache_clear()
    yield
    app.dependency_overrides.clear()
    bi_db._engine.cache_clear()


@pytest.fixture
def acceso_local(tmp_path, monkeypatch):
    privado = tmp_path / "privado"
    privado.mkdir(mode=0o700)
    auditoria = privado / "bi-audit.sqlite3"
    monkeypatch.setenv("BI_NOMINAL_LOCAL_ENABLED", "1")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("BI_NOMINAL_AUDIT_DB_PATH", str(auditoria))
    monkeypatch.setenv("BI_GOOGLE_CLIENT_ID", "inventado.apps.googleusercontent.com")
    monkeypatch.setenv("BI_GOOGLE_SUB_ROLES", json.dumps({"sub-inventado": "owner"}))
    monkeypatch.setattr(
        bi_auth.google_id_token, "verify_oauth2_token",
        lambda *a, **k: {
            "iss": "https://accounts.google.com",
            "aud": "inventado.apps.googleusercontent.com",
            "exp": int(time.time()) + 3600,
            "sub": "sub-inventado",
        },
    )
    return auditoria


@pytest.fixture
def datos_inventados(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Cliente.__table__, Direccion.__table__, Pedido.__table__])
    with Session(engine) as db:
        db.execute(insert(Cliente), [
            {"id": 1, "alias": "=FORMULA()", "nombre": "Nombre inventado",
             "telefono": "000-TEST-1"},
            {"id": 2, "alias": "Sin compra", "telefono": "000-TEST-2"},
        ])
        db.execute(insert(Direccion), [
            {"id": 1, "cliente_id": 1, "texto_original": "+DIRECCION", "activa": True},
            {"id": 2, "cliente_id": 2, "texto_original": "Calle ficticia", "activa": True},
        ])
        db.execute(insert(Pedido), [
            {"id": 1, "cliente_id": 1, "direccion_id": 1,
             "fecha_entrega": date(2026, 10, 1), "peso_balon_kg": 10,
             "cantidad_balones": 1, "total_soles": Decimal("70.00"),
             "saldo_pendiente": Decimal("10.00"), "monto_total_centavos": 7000,
             "monto_pendiente_centavos": 1000, "estado": "ACTIVO"},
            {"id": 2, "cliente_id": 1, "direccion_id": 1,
             "fecha_entrega": date(2026, 10, 2), "peso_balon_kg": 45,
             "cantidad_balones": 1, "total_soles": Decimal("100.25"),
             "saldo_pendiente": Decimal("0.00"), "monto_total_centavos": None,
             "monto_pendiente_centavos": None, "estado": "ACTIVO"},
        ])
        db.flush()
        app.dependency_overrides[bi_db.get_bi_db] = lambda: db
        yield db
    engine.dispose()


def _eventos(ruta):
    with sqlite3.connect(ruta) as db:
        return db.execute(
            "SELECT accion, resultado, actor_ref, filtros, filas, bytes_preparados "
            "FROM eventos_nominales ORDER BY id"
        ).fetchall()


def test_puerta_local_apagada_y_tcp_no_loopback(acceso_local, datos_inventados, monkeypatch):
    monkeypatch.delenv("BI_NOMINAL_LOCAL_ENABLED")
    assert _cliente_web().get("/bi/v1/clientes", headers=_auth()).status_code == 503
    monkeypatch.setenv("BI_NOMINAL_LOCAL_ENABLED", "1")
    monkeypatch.delenv("APP_ENV")
    assert _cliente_web().get("/bi/v1/clientes", headers=_auth()).status_code == 503
    monkeypatch.setenv("APP_ENV", "prd")
    assert _cliente_web().get("/bi/v1/clientes", headers=_auth()).status_code == 503
    monkeypatch.setenv("APP_ENV", "dev")
    externo = TestClient(app, base_url="http://127.0.0.1", client=("10.0.0.1", 50000))
    assert externo.get("/bi/v1/clientes", headers=_auth()).status_code == 503
    assert _cliente_web().get("/bi/v1/clientes", headers={**_auth(), "X-Forwarded-For": "1.2.3.4"}).status_code == 503


def test_401_403_y_auditoria_sin_token(acceso_local, datos_inventados, monkeypatch):
    cliente = _cliente_web()
    assert cliente.get("/bi/v1/clientes").status_code == 401
    monkeypatch.setenv("BI_GOOGLE_SUB_ROLES", json.dumps({"sub-inventado": "viewer"}))
    assert cliente.get("/bi/v1/clientes", headers=_auth()).status_code == 403
    eventos = _eventos(acceso_local)
    assert len(eventos) == 2
    assert [e[1] for e in eventos] == ["denied", "denied"]
    assert all(e[2] is None for e in eventos)
    assert stat.S_IMODE(os.stat(acceso_local.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(acceso_local).st_mode) == 0o600


def test_falla_cerrado_sin_auditoria_privada(acceso_local, datos_inventados, monkeypatch):
    monkeypatch.setenv("BI_NOMINAL_AUDIT_DB_PATH", str(acceso_local.parent / "falta" / "audit.sqlite3"))
    respuesta = _cliente_web().get("/bi/v1/clientes", headers=_auth())
    assert respuesta.status_code == 503
    assert respuesta.headers["cache-control"] == "no-store"
    assert "falta" not in respuesta.text


def test_auditoria_con_permisos_inseguros_falla_cerrado(acceso_local, datos_inventados):
    acceso_local.parent.chmod(0o755)
    respuesta = _cliente_web().get("/bi/v1/clientes", headers=_auth())
    assert respuesta.status_code == 503
    assert not acceso_local.exists()


def test_paginas_owner_y_limites(acceso_local, datos_inventados):
    cliente = _cliente_web()
    catalogo = cliente.get("/bi/v1/clientes?offset=1&limit=1", headers=_auth())
    assert catalogo.status_code == 200
    assert catalogo.headers["cache-control"] == "no-store"
    assert catalogo.json()["metadatos"]["snapshot_garantizado"] is True
    assert catalogo.json()["metadatos"]["snapshot_alcance"] == "solicitud"
    assert catalogo.json()["metadatos"]["total_registros"] == 2
    assert len(catalogo.json()["filas"]) == 1
    pedidos = cliente.get(
        "/bi/v1/pedidos?desde=2026-10-01&hasta=2026-10-02&peso_balon_kg=10&limit=1",
        headers=_auth(),
    )
    assert pedidos.status_code == 200
    assert pedidos.headers["cache-control"] == "no-store"
    assert pedidos.json()["metadatos"]["total_registros"] == 1
    assert pedidos.json()["filas"][0]["monto_total_centavos"] == 7000
    assert cliente.get("/bi/v1/clientes?limit=201", headers=_auth()).status_code == 422
    assert cliente.get(
        "/bi/v1/pedidos?desde=2026-10-03&hasta=2026-10-01", headers=_auth(),
    ).status_code == 422
    assert [evento[1] for evento in _eventos(acceso_local)] == [
        "served", "served", "failed", "failed",
    ]


def test_pausas_owner_local_y_auditoria(acceso_local, datos_inventados, monkeypatch):
    monkeypatch.setattr(bi_service, "fecha_hoy_lima", lambda: date(2026, 10, 15))
    cliente = _cliente_web()
    ruta = "/bi/v1/clientes/pausas?desde=2026-05-21&hasta=2026-10-14&limit=1"
    assert cliente.get(ruta).status_code == 401
    respuesta = cliente.get(ruta, headers=_auth())
    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    cuerpo = respuesta.json()
    assert cuerpo["metadatos"]["poblacion"] == "compradores_del_periodo_con_pausa_observada"
    assert cuerpo["metadatos"]["snapshot_garantizado"] is True
    assert cuerpo["metadatos"]["total_registros"] == 1
    assert cuerpo["filas"][0]["dias_compra_observados"] == ["2026-10-01", "2026-10-02"]
    assert cuerpo["filas"][0]["cadencia_individual"] is None
    assert [evento[1] for evento in _eventos(acceso_local)] == ["denied", "served"]
    monkeypatch.setenv("BI_GOOGLE_SUB_ROLES", json.dumps({"sub-inventado": "viewer"}))
    assert cliente.get(ruta, headers=_auth()).status_code == 403
    assert _eventos(acceso_local)[-1][1] == "denied"


def test_exports_owner_conciliados_y_escape_formula(acceso_local, datos_inventados):
    cliente = _cliente_web()
    clientes = cliente.post("/bi/v1/clientes/export", headers=_auth())
    assert clientes.status_code == 200
    assert clientes.headers["cache-control"] == "no-store"
    libro_clientes = load_workbook(BytesIO(clientes.content), data_only=False)
    assert libro_clientes["Clientes registrados"]["B2"].value == "'=FORMULA()"
    assert libro_clientes["Clientes registrados"]["B2"].data_type != "f"

    pedidos = cliente.post(
        "/bi/v1/pedidos/export?desde=2026-10-01&hasta=2026-10-02&peso_balon_kg=todos",
        headers=_auth(),
    )
    assert pedidos.status_code == 200
    assert pedidos.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert pedidos.headers["content-disposition"].startswith("attachment; filename=")
    assert pedidos.headers["cache-control"] == "no-store"
    libro = load_workbook(BytesIO(pedidos.content), data_only=False)
    assert libro["Pedidos"]["C2"].value == "'=FORMULA()"
    assert libro["Pedidos"]["D2"].value == "'+DIRECCION"
    meta = dict(libro["Metadatos"].values)
    assert meta["snapshot_garantizado"] is True
    assert meta["snapshot_alcance"] == "solicitud"
    assert meta["generado_en"] == pedidos.headers["x-bi-generado-en"]
    assert meta["pedidos_validos.monto_total_centavos"] == 17025
    eventos = _eventos(acceso_local)
    assert [e[1] for e in eventos] == ["prepared", "prepared"]
    assert all(e[2] and len(e[2]) == 64 for e in eventos)
    assert all(e[5] > 0 for e in eventos)
    assert "FORMULA" not in str(eventos)
    assert "token" not in str(eventos)


def test_export_exceso_5000_y_paridad_fallida_no_entregan_archivo(
    acceso_local, datos_inventados, monkeypatch,
):
    monkeypatch.setattr(bi_service.repo, "contar_pedidos", lambda *a, **k: 5001)
    url = "/bi/v1/pedidos/export?desde=2026-10-01&hasta=2026-10-02"
    exceso = _cliente_web().post(url, headers=_auth())
    assert exceso.status_code == 422
    assert "content-disposition" not in exceso.headers


def test_paridad_fallida_no_entrega_archivo(acceso_local, datos_inventados, monkeypatch):
    real = bi_api.construir_corte

    def corte_discrepante(*args, **kwargs):
        corte = real(*args, **kwargs)
        corte["resumen"]["vendido_centavos"] += 1
        return corte

    monkeypatch.setattr(bi_api, "construir_corte", corte_discrepante)
    respuesta = _cliente_web().post(
        "/bi/v1/pedidos/export?desde=2026-10-01&hasta=2026-10-02", headers=_auth(),
    )
    assert respuesta.status_code == 503
    assert "content-disposition" not in respuesta.headers
    assert _eventos(acceso_local)[0][1] == "failed"
