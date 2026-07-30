"""Service `clientes` con dispatch PostgreSQL/DynamoDB."""

from __future__ import annotations

from datetime import date as date_cls
from typing import TYPE_CHECKING

from app.core.storage import is_dynamodb_enabled
from app.schemas.cliente import ClienteOut, ClienteRecienteOut
from app.services.errors import AliasDuplicadoError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _require_db(db: "Session | None") -> "Session":
    if db is None:
        raise RuntimeError(
            "Servicio PostgreSQL requiere sesion; "
            "storage actual no esta inyectando una."
        )
    return db


def _cliente_pg_to_out(cliente) -> ClienteOut:
    return ClienteOut(
        id=cliente.id,
        alias=cliente.alias,
        telefono=cliente.telefono,
        direccion=cliente.alias,
        canal_captacion=cliente.canal_captacion,
    )


def _cliente_ddb_to_out(c) -> ClienteOut:
    # Item DDB legacy sin atributo canal_captacion ⇒ None (misma semantica
    # que legacy PG). Paridad completa enumerada en la spec P1 §6.
    return ClienteOut(
        id=c.id,
        alias=c.alias,
        telefono=c.telefono,
        direccion=c.direccion,
        canal_captacion=getattr(c, "canal_captacion", None),
    )


def _monto_total_centavos_pg(pedido) -> int:
    if pedido.monto_total_centavos is not None:
        return pedido.monto_total_centavos
    return int(pedido.total_soles * 100)


def crear_cliente(
    db: "Session | None",
    *,
    alias: str,
    telefono: str,
    canal_captacion: str | None = None,
) -> ClienteOut:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import clientes as ddb

        if canal_captacion is not None:
            # Decision D11 (spec P1): AWS en standby, la rama nueva es deuda
            # explicita y visible. Paridad enumerada en la spec P1 §6.
            raise NotImplementedError(
                "canal_captacion no esta implementado en el backend DynamoDB "
                "(AWS en standby, spec P1 §6 / D11)."
            )
        try:
            c = ddb.crear_cliente_con_id_generado(alias=alias, telefono=telefono)
        except ddb.AliasDuplicadoError as exc:
            raise AliasDuplicadoError(str(exc)) from exc
        return _cliente_ddb_to_out(c)

    from sqlalchemy.exc import IntegrityError

    from app.infrastructure.repositories import clientes as pg

    session = _require_db(db)
    try:
        cliente = pg.crear_cliente(
            session,
            alias=alias,
            telefono=telefono,
            canal_captacion=canal_captacion,
        )
    except IntegrityError as exc:
        session.rollback()
        raise AliasDuplicadoError("Ya existe un cliente con ese alias.") from exc
    return _cliente_pg_to_out(cliente)


def obtener_cliente_por_id(
    db: "Session | None", cliente_id: str
) -> ClienteOut | None:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import clientes as ddb

        c = ddb.obtener_cliente_por_id(cliente_id)
        if c is None:
            return None
        return _cliente_ddb_to_out(c)

    from app.infrastructure.repositories import clientes as pg

    session = _require_db(db)
    cliente = pg.obtener_cliente_por_id(session, cliente_id)
    if cliente is None:
        return None
    return _cliente_pg_to_out(cliente)


def buscar_clientes(
    db: "Session | None", *, q: str, limit: int
) -> list[ClienteOut]:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import clientes as ddb

        items = ddb.buscar_clientes(q, limit=limit)
        return [_cliente_ddb_to_out(c) for c in items]

    from app.infrastructure.repositories import clientes as pg

    session = _require_db(db)
    rows = pg.buscar_clientes(session, q=q, limit=limit)
    return [_cliente_pg_to_out(c) for c in rows]


def listar_catalogo_clientes(
    db: "Session | None",
    *,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ClienteOut]:
    """V2.5: GET /clientes catalogo simple, sin paginar agresivamente.

    Si `q` esta presente, filtra por alias/telefono (PostgreSQL ILIKE; DDB
    scan + filtro en memoria). Sin `q`, devuelve hasta `limit` clientes
    ordenados por id desc.
    """
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import clientes as ddb

        # En MVP el volumen es bajo: scan completo y filtramos en memoria.
        items = ddb.listar_catalogo(q=q, limit=limit, offset=offset)
        return [_cliente_ddb_to_out(c) for c in items]

    from app.infrastructure.repositories import clientes as pg

    session = _require_db(db)
    rows = pg.listar_catalogo(session, q=q, limit=limit, offset=offset)
    return [_cliente_pg_to_out(c) for c in rows]


def listar_clientes_recientes(
    db: "Session | None", *, limit: int
) -> list[ClienteRecienteOut]:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import (
            clientes as ddb_clientes,
        )
        from app.infrastructure.dynamodb.repositories import pedidos as ddb_pedidos
        from app.infrastructure.dynamodb.repositories.reportes import (
            _scan_all_pedidos,
        )

        pedidos = sorted(
            _scan_all_pedidos(),
            key=lambda p: (p.fecha_entrega, p.created_at),
            reverse=True,
        )
        out: list[ClienteRecienteOut] = []
        seen: set[str] = set()
        for p in pedidos:
            if p.cliente_id in seen:
                continue
            seen.add(p.cliente_id)
            cliente = ddb_clientes.obtener_cliente_por_id(p.cliente_id)
            if cliente is None:
                continue
            try:
                fecha = date_cls.fromisoformat(p.fecha_entrega)
            except ValueError:
                continue
            out.append(
                ClienteRecienteOut(
                    id=cliente.id,
                    alias=cliente.alias,
                    telefono=cliente.telefono,
                    direccion=cliente.direccion,
                    ultimo_pedido_fecha=fecha,
                    ultimo_total_centavos=p.total_centavos,
                    canal_captacion=getattr(cliente, "canal_captacion", None),
                )
            )
            if len(out) >= limit:
                break
        # silenciar warning de import sin uso cuando ddb_pedidos no se referencia
        del ddb_pedidos
        return out

    from app.infrastructure.repositories import clientes as pg

    session = _require_db(db)
    rows = pg.listar_clientes_recientes(session, limit=limit)
    return [
        ClienteRecienteOut(
            id=cliente.id,
            alias=cliente.alias,
            telefono=cliente.telefono,
            direccion=cliente.alias,
            ultimo_pedido_fecha=pedido.fecha_entrega,
            ultimo_total_centavos=_monto_total_centavos_pg(pedido),
            canal_captacion=cliente.canal_captacion,
        )
        for cliente, pedido in rows
    ]
