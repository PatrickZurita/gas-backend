"""Barreras del runner BI, solo con objetos falsos y sin conexión de red."""

from datetime import date

import pytest

from scripts import reconciliar_bi_readonly as cli
from test_bi_presentacion import _corte_sintetico


def _estado_valido():
    return {
        "usuario": "gas_readonly", "usuario_sesion": "gas_readonly",
        "solo_lectura": "on", "aislamiento": "repeatable read",
        "pedidos_existe": True, "puede_leer": True,
        "puede_insertar": False, "puede_actualizar": False,
        "puede_borrar": False, "puede_truncar": False,
        "superusuario": False, "crea_roles": False, "crea_bases": False,
    }


@pytest.mark.parametrize("campo,valor", [
    ("usuario", "admin"), ("usuario_sesion", "admin"),
    ("solo_lectura", "off"), ("aislamiento", "read committed"),
    ("pedidos_existe", False), ("puede_leer", False),
    ("puede_insertar", True), ("puede_actualizar", True),
    ("puede_borrar", True), ("puede_truncar", True),
    ("superusuario", True), ("crea_roles", True), ("crea_bases", True),
])
def test_rol_o_transaccion_inseguros_se_rechazan(campo, valor):
    estado = _estado_valido()
    estado[campo] = valor
    with pytest.raises(PermissionError):
        cli._exigir_barreras(estado)


@pytest.mark.parametrize("dsn", [
    "sqlite:///tmp/a.db",
    "postgresql://admin:clave@host/db?sslmode=require",
    "postgresql://gas_readonly:clave@host/db",
    "postgresql://gas_readonly:clave@ep-sintetico.neon.tech/db?sslmode=disable",
    "postgresql://gas_readonly:clave@ep-sintetico.neon.tech/db?options=-c%20default_transaction_read_only%3Doff",
])
def test_dsn_inseguro_se_rechaza_sin_mostrarlo(dsn):
    with pytest.raises(ValueError) as error:
        cli._validar_dsn(dsn)
    assert "clave" not in str(error.value)


def test_dsn_aceptado_fuerza_psycopg_y_tls():
    url = cli._validar_dsn("postgresql://gas_readonly:clave@ep-sintetico.neon.tech/db")
    assert url.drivername == "postgresql+psycopg"
    assert url.query["sslmode"] == "require"


@pytest.mark.parametrize("desde,hasta", [
    ("2026-10-02", "2026-10-01"),
    ("2024-01-01", "2026-10-01"),
    ("2026-10-01", "2026-10-32"),
])
def test_rangos_invalidos_se_rechazan_antes_de_conectar(desde, hasta):
    with pytest.raises(ValueError):
        cli._validar_fechas(desde, hasta)


class _TransaccionFalsa:
    def __init__(self, eventos):
        self.eventos = eventos

    def rollback(self):
        self.eventos.append("rollback")


class _ResultadoFalso:
    def __init__(self, estado):
        self.estado = estado

    def mappings(self):
        return self

    def one(self):
        return self.estado


class _ConexionFalsa:
    def __init__(self, eventos, estado):
        self.eventos = eventos
        self.estado = estado

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.eventos.append("cerrar")

    def begin(self):
        self.eventos.append("begin")
        return _TransaccionFalsa(self.eventos)

    def exec_driver_sql(self, sql):
        if sql.startswith("SET TRANSACTION"):
            self.eventos.append("set_read_only")
        else:
            self.eventos.append("comprobar_barreras")
        return _ResultadoFalso(self.estado)


class _EngineFalso:
    def __init__(self, eventos, estado):
        self.conexion = _ConexionFalsa(eventos, estado)

    def connect(self):
        return self.conexion


def test_la_barrera_precede_el_corte_y_siempre_hace_rollback(monkeypatch):
    eventos = []

    class SesionFalsa:
        def __init__(self, *, bind, join_transaction_mode):
            assert join_transaction_mode == "rollback_only"
            assert bind is engine.conexion

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    engine = _EngineFalso(eventos, _estado_valido())
    monkeypatch.setattr(cli, "Session", SesionFalsa)
    monkeypatch.setattr(cli, "_construir_corte", lambda *_, **__: eventos.append("leer_corte"))

    cli._obtener_corte(engine, desde=date(2026, 10, 1), hasta=date(2026, 10, 2), peso=None)
    assert eventos == [
        "begin", "set_read_only", "comprobar_barreras", "leer_corte",
        "rollback", "cerrar",
    ]


def test_barrera_fallida_impide_leer_y_hace_rollback(monkeypatch):
    eventos = []
    estado = _estado_valido()
    estado["puede_borrar"] = True
    engine = _EngineFalso(eventos, estado)
    monkeypatch.setattr(cli, "_construir_corte", lambda *_, **__: pytest.fail("Leyó datos"))

    with pytest.raises(PermissionError):
        cli._obtener_corte(engine, desde=date(2026, 10, 1),
                           hasta=date(2026, 10, 2), peso=None)
    assert eventos == ["begin", "set_read_only", "comprobar_barreras", "rollback", "cerrar"]


def test_runner_reconcilia_solo_agregados_sinteticos():
    salida = cli._reconciliar(_corte_sintetico())
    assert salida["checks"] == {
        "json_xlsx": "ok", "serie_resumen": "ok", "actividad": "ok",
        "cobertura": "ok", "importes": "ok",
    }
    assert salida["n_pedidos_base"] == 3
    assert "actividad_clientes" not in salida


def test_runner_rechaza_cobertura_que_no_suma_poblacion():
    corte = _corte_sintetico()
    corte["cobertura"]["pedidos_monetarios_anomalos"] = 1
    with pytest.raises(ValueError, match="Cobertura monetaria"):
        cli._reconciliar(corte)


def test_runner_rechaza_denominador_incoherente_de_cohorte():
    corte = _corte_sintetico()
    corte["actividad_clientes"]["cohortes_retorno"][0]["censurados"] = 2
    with pytest.raises(ValueError, match="Denominadores"):
        cli._reconciliar(corte)
