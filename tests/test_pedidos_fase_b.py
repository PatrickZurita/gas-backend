import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db.base import Base
from app.infrastructure.repositories import pedidos as repo_pedidos
from app.main import app
from app.models.models import Cliente, Direccion


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db_session(db_session_factory):
    db = db_session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session_factory):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _crear_cliente(db, alias: str = "Las Higueras 371") -> Cliente:
    cliente = Cliente(alias=alias, telefono="999888777", nombre=None)
    db.add(cliente)
    db.flush()
    db.add(
        Direccion(
            cliente_id=cliente.id,
            texto_original=alias,
            distrito=None,
            referencia=None,
            activa=True,
        )
    )
    db.commit()
    db.refresh(cliente)
    return cliente


def test_catalogos_devuelven_tipos_y_marcas(client):
    tipos = client.get("/catalogos/tipos-balon")
    marcas = client.get("/catalogos/marcas-balon")

    assert tipos.status_code == 200
    assert tipos.json() == {
        "items": [
            {"codigo": "NORMAL", "nombre": "Normal"},
            {"codigo": "PREMIUM", "nombre": "Premium"},
        ]
    }
    assert marcas.status_code == 200
    assert marcas.json() == {
        "items": [
            {"codigo": "SOLGAS", "nombre": "Solgas"},
            {"codigo": "PETROPERU", "nombre": "Petroperu"},
        ]
    }


def test_pedido_legacy_usa_defaults_petroperu_normal(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["marca_balon"] == "PETROPERU"
    assert body["tipo_balon"] == "NORMAL"
    assert body["precio_unitario_centavos"] == 5500
    assert body["monto_total_centavos"] == 5500
    assert body["monto_pendiente_centavos"] == 0
    assert body["total_soles"] == "55.00"


def test_pedido_nuevo_registra_marca_tipo_y_precio_real(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "marca_balon": "SOLGAS",
            "tipo_balon": "PREMIUM",
            "precio_unitario_centavos": 6500,
            "pagado": False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["marca_balon"] == "SOLGAS"
    assert body["tipo_balon"] == "PREMIUM"
    assert body["precio_unitario_centavos"] == 6500
    assert body["monto_total_centavos"] == 6500
    assert body["monto_pendiente_centavos"] == 6500
    assert body["saldo_pendiente"] == "65.00"


def test_pedido_acepta_total_soles_con_centimos(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": "55.50",
            "pagado": False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["total_soles"] == "55.50"
    assert body["saldo_pendiente"] == "55.50"
    assert body["precio_unitario_centavos"] == 5550
    assert body["monto_total_centavos"] == 5550
    assert body["monto_pendiente_centavos"] == 5550


def test_pedido_rechaza_marca_o_tipo_invalidos(client, db_session):
    cliente = _crear_cliente(db_session)

    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "marca_balon": "OTRA",
            "tipo_balon": "NORMAL",
            "precio_unitario_centavos": 6500,
            "pagado": True,
        },
    )

    assert response.status_code == 422


def test_reporte_usa_centavos_exactos_y_expone_marca_tipo(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "marca_balon": "SOLGAS",
            "tipo_balon": "NORMAL",
            "monto_total_centavos": 110050,
            "monto_pendiente_centavos": 50,
            "pagado": False,
        },
    )

    response = client.get("/reportes/dia", params={"fecha": "2026-01-16"})

    assert response.status_code == 200
    body = response.json()
    pedido = body["pedidos"][0]
    assert body["monto_total_centavos"] == 110050
    assert body["monto_pendiente_centavos"] == 50
    assert body["monto_pagado_centavos"] == 110000
    assert pedido["marca_balon"] == "SOLGAS"
    assert pedido["tipo_balon"] == "NORMAL"
    assert pedido["monto_total_centavos"] == 110050


# --- V2.0 Stock consistency baseline: pedidos activos/anulados ---


def _crear_pedido_con_jornada(client, db_session, *, stock_inicial=30, cantidad=2):
    """Inicia jornada y crea un pedido ACTIVO. Devuelve (cliente, pedido_id)."""
    cliente = _crear_cliente(db_session)
    iniciar = client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": stock_inicial},
    )
    assert iniciar.status_code == 201

    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": cantidad,
            "total_soles": 55 * cantidad,
            "pagado": True,
        },
    )
    assert crear.status_code == 201
    return cliente, crear.json()["id"]


def test_v2_pedido_activo_baja_stock_y_sube_vendidos(client, db_session):
    _crear_pedido_con_jornada(client, db_session, stock_inicial=30, cantidad=2)

    reporte = client.get("/reportes/dia", params={"fecha": "2026-01-16"}).json()
    assert reporte["pedidos_count"] == 1
    assert reporte["balones_vendidos"] == 2
    assert reporte["stock"]["salidas"] == 2
    assert reporte["stock"]["stock_actual"] == 28


def test_v2_anular_pedido_excluye_del_resumen_y_recupera_stock(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )

    repo_pedidos.anular_pedido(db_session, pedido_id, motivo="pedido duplicado")

    reporte = client.get("/reportes/dia", params={"fecha": "2026-01-16"}).json()
    # Resumen excluye el pedido anulado.
    assert reporte["pedidos_count"] == 0
    assert reporte["balones_vendidos"] == 0
    # Stock se recupera: salida (-2) cancelada por reversa (+2).
    assert reporte["stock"]["salidas"] == 0
    assert reporte["stock"]["stock_actual"] == 30
    # La reversa no se contabiliza como ajuste manual.
    assert reporte["stock"]["ajustes"] == 0


def test_v2_anular_dos_veces_no_duplica_reversa(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )

    # Idempotente: la segunda anulacion es un no-op, no vuelve a compensar.
    repo_pedidos.anular_pedido(db_session, pedido_id, motivo="dup")
    repo_pedidos.anular_pedido(db_session, pedido_id, motivo="dup otra vez")

    detalle = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    assert detalle["stock_actual"] == 30  # no 32
    reversas = [m for m in detalle["movimientos"] if m["tipo"] == "REVERSA_ANULACION"]
    assert len(reversas) == 1


def test_v2_reporte_dia_excluye_anulados_y_mantiene_activos(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": 30},
    )

    def _crear(cantidad):
        resp = client.post(
            "/pedidos",
            json={
                "cliente_id": cliente.id,
                "fecha_entrega": "2026-01-16",
                "cantidad_balones": cantidad,
                "total_soles": 55 * cantidad,
                "pagado": True,
            },
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    id_activo = _crear(1)
    id_anulado = _crear(3)

    repo_pedidos.anular_pedido(db_session, id_anulado, motivo="error de registro")

    reporte = client.get("/reportes/dia", params={"fecha": "2026-01-16"}).json()
    assert reporte["pedidos_count"] == 1
    assert reporte["balones_vendidos"] == 1
    assert [p["id"] for p in reporte["pedidos"]] == [id_activo]
    # 30 - 1 - 3 + 3(reversa) = 29
    assert reporte["stock"]["stock_actual"] == 29
    assert reporte["stock"]["salidas"] == 1


# --- V2.1: endpoint POST /pedidos/{id}/anular ---


def test_v21_endpoint_anular_marca_estado_y_recupera_stock(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )

    response = client.post(
        f"/pedidos/{pedido_id}/anular",
        json={"motivo": "pedido duplicado"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == pedido_id
    assert body["estado"] == "ANULADO"
    assert body["anulado_motivo"] == "pedido duplicado"
    assert body["anulado_at"] is not None

    reporte = client.get("/reportes/dia", params={"fecha": "2026-01-16"}).json()
    assert reporte["pedidos_count"] == 0
    assert reporte["stock"]["stock_actual"] == 30


def test_v21_endpoint_anular_sin_motivo_funciona(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=10, cantidad=1
    )

    response = client.post(f"/pedidos/{pedido_id}/anular")

    assert response.status_code == 200
    body = response.json()
    assert body["estado"] == "ANULADO"
    assert body["anulado_motivo"] is None


def test_v21_endpoint_anular_es_idempotente(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )

    primero = client.post(f"/pedidos/{pedido_id}/anular", json={"motivo": "dup"})
    segundo = client.post(f"/pedidos/{pedido_id}/anular", json={"motivo": "dup"})

    assert primero.status_code == 200
    # Idempotente: el segundo POST devuelve 200 con el estado actual, no
    # vuelve a compensar el stock.
    assert segundo.status_code == 200
    assert segundo.json()["estado"] == "ANULADO"

    detalle = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    assert detalle["stock_actual"] == 30
    reversas = [m for m in detalle["movimientos"] if m["tipo"] == "REVERSA_ANULACION"]
    assert len(reversas) == 1


def test_v21_endpoint_anular_pedido_inexistente_devuelve_404(client):
    response = client.post("/pedidos/9999/anular", json={"motivo": "x"})

    assert response.status_code == 404


def test_v21_pedido_anulado_excluido_de_deudas(client, db_session):
    cliente = _crear_cliente(db_session)
    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": False,
        },
    )
    assert crear.status_code == 201
    pedido_id = crear.json()["id"]

    deudas_antes = client.get("/reportes/deudas").json()
    assert deudas_antes["pedidos_count"] == 1
    assert deudas_antes["monto_pendiente_centavos"] == 5500

    anular = client.post(f"/pedidos/{pedido_id}/anular", json={"motivo": "error"})
    assert anular.status_code == 200

    deudas_despues = client.get("/reportes/deudas").json()
    assert deudas_despues["pedidos_count"] == 0
    assert deudas_despues["monto_pendiente_centavos"] == 0


def test_v21_pedido_out_expone_estado_activo_por_default(client, db_session):
    cliente = _crear_cliente(db_session)
    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
        },
    )
    assert crear.status_code == 201
    body = crear.json()
    assert body["estado"] == "ACTIVO"
    assert body["anulado_at"] is None
    assert body["anulado_motivo"] is None


# --- V2.1.b: endpoint PATCH /pedidos/{id} ---


def test_v21_patch_cantidad_recalcula_stock(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )

    # 30 - 2 = 28; al PATCH cantidad=5: reversa +2, salida -5 ⇒ 28 + 2 - 5 = 25.
    response = client.patch(
        f"/pedidos/{pedido_id}",
        json={"cantidad_balones": 5, "motivo_edicion": "agrego 3 mas"},
    )
    assert response.status_code == 200
    assert response.json()["cantidad_balones"] == 5

    detalle = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    assert detalle["stock_actual"] == 25
    # salidas neto = 5 (5 efectivos despues de reversa).
    assert detalle["salidas"] == 5


def test_v21_patch_fecha_mueve_impacto_entre_jornadas(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )
    # Iniciar otra jornada para la nueva fecha destino.
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-17", "stock_inicial": 20},
    )

    response = client.patch(
        f"/pedidos/{pedido_id}",
        json={"fecha_entrega": "2026-01-17"},
    )
    assert response.status_code == 200
    assert response.json()["fecha_entrega"] == "2026-01-17"

    # Jornada vieja recupera stock; jornada nueva pierde stock.
    vieja = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    nueva = client.get("/stock/dia", params={"fecha": "2026-01-17"}).json()
    assert vieja["stock_actual"] == 30  # reversa +2
    assert nueva["stock_actual"] == 18  # 20 - 2
    assert vieja["salidas"] == 0
    assert nueva["salidas"] == 2


def test_v21_patch_pedido_anulado_devuelve_409(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )
    assert client.post(f"/pedidos/{pedido_id}/anular").status_code == 200

    response = client.patch(
        f"/pedidos/{pedido_id}", json={"cantidad_balones": 5}
    )
    assert response.status_code == 409


def test_v21_patch_pedido_inexistente_devuelve_404(client):
    response = client.patch("/pedidos/9999", json={"cantidad_balones": 5})
    assert response.status_code == 404


def test_v21_patch_solo_metadata_no_toca_stock(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )
    response = client.patch(
        f"/pedidos/{pedido_id}",
        json={"pagado": False, "monto_pendiente_centavos": 5500},
    )
    assert response.status_code == 200

    detalle = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    # Sin cambio en cantidad/fecha/peso ⇒ una sola SALIDA_PEDIDO, sin reversa.
    salidas = [m for m in detalle["movimientos"] if m["tipo"] == "SALIDA_PEDIDO"]
    reversas = [m for m in detalle["movimientos"] if m["tipo"] == "REVERSA_ANULACION"]
    assert len(salidas) == 1
    assert len(reversas) == 0
    assert detalle["stock_actual"] == 28


# --- V2.2: peso_balon_kg ---


def test_v22_crear_pedido_default_peso_10kg(client, db_session):
    cliente = _crear_cliente(db_session)
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
        },
    )
    assert response.status_code == 201
    assert response.json()["peso_balon_kg"] == 10


def test_v22_crear_pedido_peso_45kg_explicito(client, db_session):
    cliente = _crear_cliente(db_session)
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 160,
            "pagado": True,
            "peso_balon_kg": 45,
        },
    )
    assert response.status_code == 201
    assert response.json()["peso_balon_kg"] == 45


def test_v22_crear_pedido_peso_invalido_devuelve_422(client, db_session):
    cliente = _crear_cliente(db_session)
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "peso_balon_kg": 20,
        },
    )
    assert response.status_code == 422


def test_v22_patch_peso_actualiza(client, db_session):
    _, pedido_id = _crear_pedido_con_jornada(
        client, db_session, stock_inicial=30, cantidad=2
    )
    response = client.patch(
        f"/pedidos/{pedido_id}", json={"peso_balon_kg": 45}
    )
    assert response.status_code == 200
    assert response.json()["peso_balon_kg"] == 45


def test_v22_reporte_dia_expone_peso(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "peso_balon_kg": 45,
        },
    )
    reporte = client.get("/reportes/dia", params={"fecha": "2026-01-16"}).json()
    assert reporte["pedidos"][0]["peso_balon_kg"] == 45


# --- V2.3: Stock por peso ---


def test_v23_pedido_10kg_no_afecta_bucket_45kg(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": 30},
    )
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 3,
            "total_soles": 165,
            "peso_balon_kg": 10,
        },
    )

    detalle = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    por_peso = detalle["por_peso"]
    assert por_peso["10kg"]["salidas"] == 3
    assert por_peso["45kg"]["salidas"] == 0
    assert por_peso["10kg"]["stock_disponible"] == 27
    assert por_peso["45kg"]["stock_disponible"] == 0


def test_v23_pedido_45kg_no_afecta_bucket_10kg(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": 30},
    )
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 2,
            "total_soles": 320,
            "peso_balon_kg": 45,
        },
    )

    detalle = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    por_peso = detalle["por_peso"]
    assert por_peso["10kg"]["salidas"] == 0
    assert por_peso["45kg"]["salidas"] == 2
    assert por_peso["10kg"]["stock_disponible"] == 30
    assert por_peso["45kg"]["stock_disponible"] == -2


def test_v23_anular_45kg_solo_compensa_bucket_45kg(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-01-16", "stock_inicial": 30},
    )
    p10 = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "peso_balon_kg": 10,
        },
    ).json()["id"]
    p45 = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 2,
            "total_soles": 320,
            "peso_balon_kg": 45,
        },
    ).json()["id"]

    client.post(f"/pedidos/{p45}/anular", json={"motivo": "duplicado"})

    detalle = client.get("/stock/dia", params={"fecha": "2026-01-16"}).json()
    por_peso = detalle["por_peso"]
    # bucket 45kg: salidas 2, reversas 2 → 0 - 2 + 2 = 0
    assert por_peso["45kg"]["salidas"] == 2
    assert por_peso["45kg"]["reversas"] == 2
    assert por_peso["45kg"]["stock_disponible"] == 0
    # bucket 10kg intacto: 30 - 1 = 29
    assert por_peso["10kg"]["salidas"] == 1
    assert por_peso["10kg"]["reversas"] == 0
    assert por_peso["10kg"]["stock_disponible"] == 29
    # silenciar pedido 10kg (ya validado).
    del p10


# --- V2.5: GET /clientes catalogo ---


def test_v25_get_clientes_sin_q_devuelve_lista(client, db_session):
    _crear_cliente(db_session, alias="Maria 100")
    _crear_cliente(db_session, alias="Jose 200")

    response = client.get("/clientes")
    assert response.status_code == 200
    aliases = {c["alias"] for c in response.json()}
    assert {"Maria 100", "Jose 200"}.issubset(aliases)


def test_v25_get_clientes_con_q_match(client, db_session):
    _crear_cliente(db_session, alias="Maria 100")
    _crear_cliente(db_session, alias="Jose 200")

    response = client.get("/clientes", params={"q": "maria"})
    assert response.status_code == 200
    aliases = [c["alias"] for c in response.json()]
    assert aliases == ["Maria 100"]


def test_v25_get_clientes_con_q_sin_match(client, db_session):
    _crear_cliente(db_session, alias="Maria 100")
    response = client.get("/clientes", params={"q": "nadie"})
    assert response.status_code == 200
    assert response.json() == []


# --- V3: validar /reportes/dia ---


def test_v3_reporte_dia_fecha_pasada_funciona(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2025-12-31",
            "cantidad_balones": 1,
            "total_soles": 55,
        },
    )
    response = client.get("/reportes/dia", params={"fecha": "2025-12-31"})
    assert response.status_code == 200
    assert response.json()["pedidos_count"] == 1


def test_v3_reporte_dia_sin_pedidos_devuelve_estructura_vacia(client):
    response = client.get("/reportes/dia", params={"fecha": "2030-01-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["pedidos_count"] == 0
    assert body["pedidos"] == []


def test_v3_reporte_dia_fecha_invalida_devuelve_422(client):
    response = client.get("/reportes/dia", params={"fecha": "no-es-fecha"})
    assert response.status_code == 422


def test_v3_reporte_dia_anulados_excluidos_explicitamente(client, db_session):
    cliente = _crear_cliente(db_session)
    activo = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-02-10",
            "cantidad_balones": 1,
            "total_soles": 55,
        },
    ).json()["id"]
    anulado = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-02-10",
            "cantidad_balones": 5,
            "total_soles": 275,
        },
    ).json()["id"]
    client.post(f"/pedidos/{anulado}/anular", json={"motivo": "error"})

    body = client.get("/reportes/dia", params={"fecha": "2026-02-10"}).json()
    assert body["pedidos_count"] == 1
    assert [p["id"] for p in body["pedidos"]] == [activo]
    assert body["balones_vendidos"] == 1


# --- V4: /reportes/semana y /reportes/mes ---


def _crear_pedido_directo(client, db_session, *, fecha, cantidad, peso, total=55):
    cliente = _crear_cliente(db_session, alias=f"Cliente {fecha}-{peso}-{cantidad}")
    resp = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": fecha,
            "cantidad_balones": cantidad,
            "total_soles": total,
            "peso_balon_kg": peso,
            "pagado": True,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_v4_reporte_semana_agrega_dias_y_separa_pesos(client, db_session):
    # Pedidos en 3 dias del rango (2026-03-09 a 2026-03-15).
    _crear_pedido_directo(client, db_session, fecha="2026-03-09", cantidad=2, peso=10, total=110)
    _crear_pedido_directo(client, db_session, fecha="2026-03-11", cantidad=1, peso=45, total=160)
    _crear_pedido_directo(client, db_session, fecha="2026-03-15", cantidad=3, peso=10, total=165)

    response = client.get("/reportes/semana", params={"desde": "2026-03-09"})
    assert response.status_code == 200
    body = response.json()
    assert body["desde"] == "2026-03-09"
    assert body["hasta"] == "2026-03-15"
    assert body["total_pedidos"] == 3
    assert body["balones_10kg"] == 5
    assert body["balones_45kg"] == 1
    assert body["total_vendido_centavos"] == 11000 + 16000 + 16500
    assert len(body["dias"]) == 7
    # Verificar dias especificos.
    dias_by_date = {d["fecha"]: d for d in body["dias"]}
    assert dias_by_date["2026-03-09"]["balones_10kg"] == 2
    assert dias_by_date["2026-03-11"]["balones_45kg"] == 1
    assert dias_by_date["2026-03-10"]["pedidos_count"] == 0


def test_v4_reporte_semana_sin_pedidos(client):
    response = client.get("/reportes/semana", params={"desde": "2030-01-06"})
    assert response.status_code == 200
    body = response.json()
    assert body["total_pedidos"] == 0
    assert body["balones_10kg"] == 0
    assert body["balones_45kg"] == 0
    assert len(body["dias"]) == 7


def test_v4_reporte_semana_suma_compras_por_peso_sin_contar_inicio(client):
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-03-09", "stock_inicial": 20},
    )
    client.post(
        "/stock/entrada",
        json={"fecha": "2026-03-09", "cantidad": 5, "peso_balon_kg": 10},
    )
    client.post(
        "/stock/iniciar-dia",
        json={"fecha": "2026-03-10", "stock_inicial": 25},
    )
    client.post(
        "/stock/entrada",
        json={"fecha": "2026-03-10", "cantidad": 2, "peso_balon_kg": 45},
    )

    response = client.get("/reportes/semana", params={"desde": "2026-03-09"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_compras_10kg"] == 5
    assert body["total_compras_45kg"] == 2
    dias_by_date = {d["fecha"]: d for d in body["dias"]}
    assert dias_by_date["2026-03-09"]["compras_10kg"] == 5
    assert dias_by_date["2026-03-09"]["compras_45kg"] == 0
    assert dias_by_date["2026-03-09"]["stock_final_10kg"] == 25
    assert dias_by_date["2026-03-09"]["stock_final_45kg"] == 0
    assert dias_by_date["2026-03-10"]["compras_10kg"] == 0
    assert dias_by_date["2026-03-10"]["compras_45kg"] == 2
    assert dias_by_date["2026-03-10"]["stock_final_10kg"] == 25
    assert dias_by_date["2026-03-10"]["stock_final_45kg"] == 2


def test_v4_reporte_semana_excluye_anulados(client, db_session):
    activo = _crear_pedido_directo(
        client, db_session, fecha="2026-03-09", cantidad=2, peso=10, total=110
    )
    anulado = _crear_pedido_directo(
        client, db_session, fecha="2026-03-09", cantidad=5, peso=10, total=275
    )
    client.post(f"/pedidos/{anulado}/anular", json={"motivo": "error"})

    body = client.get("/reportes/semana", params={"desde": "2026-03-09"}).json()
    assert body["total_pedidos"] == 1
    assert body["balones_10kg"] == 2
    del activo


def test_v4_reporte_mes_agrega_correctamente(client, db_session):
    _crear_pedido_directo(client, db_session, fecha="2026-04-01", cantidad=1, peso=10, total=55)
    _crear_pedido_directo(client, db_session, fecha="2026-04-15", cantidad=2, peso=45, total=320)
    _crear_pedido_directo(client, db_session, fecha="2026-04-30", cantidad=3, peso=10, total=165)

    response = client.get("/reportes/mes", params={"mes": "2026-04"})
    assert response.status_code == 200
    body = response.json()
    assert body["mes"] == "2026-04"
    assert body["desde"] == "2026-04-01"
    assert body["hasta"] == "2026-04-30"
    assert body["total_pedidos"] == 3
    assert body["balones_10kg"] == 4
    assert body["balones_45kg"] == 2
    assert len(body["dias"]) == 30


def test_v4_reporte_mes_formato_invalido_devuelve_422(client):
    response = client.get("/reportes/mes", params={"mes": "abril-2026"})
    assert response.status_code == 422


# --- V2.6: metodo_pago (Efectivo / Yape) ---


def test_v26_crear_pedido_pagado_con_efectivo(client, db_session):
    cliente = _crear_cliente(db_session)
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "EFECTIVO",
        },
    )
    assert response.status_code == 201
    assert response.json()["metodo_pago"] == "EFECTIVO"


def test_v26_crear_pedido_pagado_con_yape(client, db_session):
    cliente = _crear_cliente(db_session)
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "YAPE",
        },
    )
    assert response.status_code == 201
    assert response.json()["metodo_pago"] == "YAPE"


def test_v26_crear_pedido_sin_metodo_pago_es_valido(client, db_session):
    cliente = _crear_cliente(db_session)
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
        },
    )
    assert response.status_code == 201
    assert response.json()["metodo_pago"] is None


def test_v26_metodo_pago_invalido_devuelve_422(client, db_session):
    cliente = _crear_cliente(db_session)
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "TRANSFERENCIA",
        },
    )
    assert response.status_code == 422


def test_v26_metodo_pago_con_pagado_false_devuelve_422(client, db_session):
    cliente = _crear_cliente(db_session)
    response = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": False,
            "metodo_pago": "EFECTIVO",
        },
    )
    assert response.status_code == 422


def test_v26_patch_metodo_pago(client, db_session):
    cliente = _crear_cliente(db_session)
    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "EFECTIVO",
        },
    )
    pedido_id = crear.json()["id"]

    response = client.patch(
        f"/pedidos/{pedido_id}",
        json={"metodo_pago": "YAPE"},
    )
    assert response.status_code == 200
    assert response.json()["metodo_pago"] == "YAPE"


def test_v26_patch_pagado_false_limpia_metodo_pago(client, db_session):
    cliente = _crear_cliente(db_session)
    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "EFECTIVO",
        },
    )
    pedido_id = crear.json()["id"]

    response = client.patch(
        f"/pedidos/{pedido_id}",
        json={"pagado": False, "monto_pendiente_centavos": 5500},
    )
    assert response.status_code == 200
    assert response.json()["metodo_pago"] is None


# --- V2.7: deuda al editar pagado se sincroniza correctamente ---


def test_v27_patch_pagado_true_quita_pedido_de_deudas(client, db_session):
    """Bug reportado: usuario marca pedido como pagado desde editar y la
    deuda sigue apareciendo en /reportes/deudas porque saldo_pendiente
    (legacy) no se sincroniza con monto_pendiente_centavos.

    Fix: listar_pedidos_con_deuda filtra por pagado=False (semantico) y
    patch_pedido sincroniza saldo_pendiente.
    """
    cliente = _crear_cliente(db_session)
    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": False,
        },
    )
    assert crear.status_code == 201
    pedido_id = crear.json()["id"]

    # Verificamos que aparece en deudas inicialmente.
    deudas_inicial = client.get("/reportes/deudas").json()
    assert deudas_inicial["pedidos_count"] == 1

    # Usuario edita y marca como pagado (sin enviar monto_pendiente_centavos).
    response = client.patch(f"/pedidos/{pedido_id}", json={"pagado": True})
    assert response.status_code == 200
    assert response.json()["pagado"] is True
    assert response.json()["monto_pendiente_centavos"] == 0

    # La deuda ya no debe aparecer.
    deudas_final = client.get("/reportes/deudas").json()
    assert deudas_final["pedidos_count"] == 0
    assert deudas_final["monto_pendiente_centavos"] == 0


def test_v27_patch_pagado_true_actualiza_resumen_dia_correcto(client, db_session):
    """El reporte del dia del pedido (no de hoy) refleja el pedido como
    pagado al editarlo. Verifica que monto_pagado del dia sube y
    monto_pendiente baja sin mover el monto entre fechas.
    """
    cliente = _crear_cliente(db_session)
    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": False,
        },
    )
    pedido_id = crear.json()["id"]

    reporte_inicial = client.get(
        "/reportes/dia", params={"fecha": "2026-01-16"}
    ).json()
    assert reporte_inicial["monto_total_centavos"] == 5500
    assert reporte_inicial["monto_pagado_centavos"] == 0
    assert reporte_inicial["monto_pendiente_centavos"] == 5500

    client.patch(f"/pedidos/{pedido_id}", json={"pagado": True})

    reporte_final = client.get(
        "/reportes/dia", params={"fecha": "2026-01-16"}
    ).json()
    # El total facturado del dia no cambia (el pedido siempre conto como
    # vendido); lo que cambia es la distribucion pagado/pendiente.
    assert reporte_final["monto_total_centavos"] == 5500
    assert reporte_final["monto_pagado_centavos"] == 5500
    assert reporte_final["monto_pendiente_centavos"] == 0


def test_v27_patch_pagado_true_no_afecta_otros_dias(client, db_session):
    """Si el pedido es del 16 y hoy seria otro dia, marcarlo como pagado
    NO suma a otra fecha. La deuda se quita correctamente y el
    monto_pagado del 16 sube; los demas dias quedan intactos.
    """
    cliente = _crear_cliente(db_session)
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": False,
        },
    )
    crear_otro = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-17",
            "cantidad_balones": 2,
            "total_soles": 100,
            "pagado": True,
        },
    )
    assert crear_otro.status_code == 201

    pedido_16 = [
        p
        for p in client.get(
            "/reportes/dia", params={"fecha": "2026-01-16"}
        ).json()["pedidos"]
    ][0]
    client.patch(f"/pedidos/{pedido_16['id']}", json={"pagado": True})

    r17 = client.get("/reportes/dia", params={"fecha": "2026-01-17"}).json()
    # El reporte del 17 no se modifica.
    assert r17["monto_total_centavos"] == 10000
    assert r17["monto_pagado_centavos"] == 10000
    assert r17["monto_pendiente_centavos"] == 0


def test_v27_patch_solo_pagado_true_sin_monto_pendiente_sigue_sincronizado(
    client, db_session
):
    """Si el frontend solo manda pagado=True (sin monto_pendiente_centavos),
    el repo debe poner monto_pendiente_centavos=0 y saldo_pendiente=0
    automaticamente.
    """
    cliente = _crear_cliente(db_session)
    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": False,
        },
    )
    pedido_id = crear.json()["id"]

    response = client.patch(f"/pedidos/{pedido_id}", json={"pagado": True})
    body = response.json()
    assert body["pagado"] is True
    assert body["monto_pendiente_centavos"] == 0
    assert float(body["saldo_pendiente"]) == 0.0


# --- V2.8: breakdown cobrado por metodo de pago ---


def test_v28_reporte_dia_separa_cobrado_por_metodo(client, db_session):
    cliente = _crear_cliente(db_session)
    # Tres pedidos: 1 efectivo, 1 yape, 1 deuda sin metodo
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "EFECTIVO",
        },
    )
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 2,
            "total_soles": 110,
            "pagado": True,
            "metodo_pago": "YAPE",
        },
    )
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": False,
        },
    )

    reporte = client.get(
        "/reportes/dia", params={"fecha": "2026-01-16"}
    ).json()
    assert reporte["monto_cobrado_efectivo_centavos"] == 5500
    assert reporte["monto_cobrado_yape_centavos"] == 11000
    # La suma de los buckets debe ser <= cobrado_total (deuda excluida).
    assert (
        reporte["monto_cobrado_efectivo_centavos"]
        + reporte["monto_cobrado_yape_centavos"]
        == reporte["monto_pagado_centavos"]
    )


def test_v28_reporte_dia_pagado_sin_metodo_no_se_atribuye(client, db_session):
    """Pedido pagado=True sin metodo_pago (legacy) no se cuenta en ningun
    bucket. La suma efectivo+yape sera menor que monto_pagado_centavos."""
    cliente = _crear_cliente(db_session)
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
        },
    )

    reporte = client.get(
        "/reportes/dia", params={"fecha": "2026-01-16"}
    ).json()
    assert reporte["monto_pagado_centavos"] == 5500
    assert reporte["monto_cobrado_efectivo_centavos"] == 0
    assert reporte["monto_cobrado_yape_centavos"] == 0


def test_v28_reporte_semana_acumula_breakdown(client, db_session):
    cliente = _crear_cliente(db_session)
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-19",  # lunes
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "EFECTIVO",
        },
    )
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-21",  # miercoles
            "cantidad_balones": 2,
            "total_soles": 110,
            "pagado": True,
            "metodo_pago": "YAPE",
        },
    )

    semana = client.get(
        "/reportes/semana", params={"desde": "2026-01-19"}
    ).json()
    assert semana["total_cobrado_efectivo_centavos"] == 5500
    assert semana["total_cobrado_yape_centavos"] == 11000

    # Por dia tambien debe distinguir.
    lunes = next(d for d in semana["dias"] if d["fecha"] == "2026-01-19")
    miercoles = next(d for d in semana["dias"] if d["fecha"] == "2026-01-21")
    assert lunes["cobrado_efectivo_centavos"] == 5500
    assert lunes["cobrado_yape_centavos"] == 0
    assert miercoles["cobrado_efectivo_centavos"] == 0
    assert miercoles["cobrado_yape_centavos"] == 11000


def test_v28_pedido_en_reporte_dia_expone_metodo_pago(client, db_session):
    """Cada pedido en /reportes/dia debe exponer metodo_pago para que el
    frontend pueda renderizar un chip Efectivo/Yape al lado del badge
    Pagado. Sin esto, Pydantic descarta el campo silenciosamente.
    """
    cliente = _crear_cliente(db_session)
    crear_yape = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "YAPE",
        },
    )
    assert crear_yape.status_code == 201
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
            "metodo_pago": "EFECTIVO",
        },
    )
    # Pedido legacy sin metodo (pagado=True pero sin elegir metodo).
    client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": True,
        },
    )

    reporte = client.get(
        "/reportes/dia", params={"fecha": "2026-01-16"}
    ).json()
    metodos = sorted([p.get("metodo_pago") for p in reporte["pedidos"]],
                     key=lambda x: (x is None, x))
    assert metodos == ["EFECTIVO", "YAPE", None]


def test_v28_patch_pagado_actualiza_breakdown_del_dia(client, db_session):
    """Al cobrar una deuda con PATCH (pagado=True + metodo_pago=YAPE),
    el reporte del dia debe sumar al bucket de Yape."""
    cliente = _crear_cliente(db_session)
    crear = client.post(
        "/pedidos",
        json={
            "cliente_id": cliente.id,
            "fecha_entrega": "2026-01-16",
            "cantidad_balones": 1,
            "total_soles": 55,
            "pagado": False,
        },
    )
    pedido_id = crear.json()["id"]

    reporte_pre = client.get(
        "/reportes/dia", params={"fecha": "2026-01-16"}
    ).json()
    assert reporte_pre["monto_cobrado_yape_centavos"] == 0

    client.patch(
        f"/pedidos/{pedido_id}",
        json={"pagado": True, "metodo_pago": "YAPE"},
    )

    reporte_post = client.get(
        "/reportes/dia", params={"fecha": "2026-01-16"}
    ).json()
    assert reporte_post["monto_cobrado_yape_centavos"] == 5500
    assert reporte_post["monto_cobrado_efectivo_centavos"] == 0
