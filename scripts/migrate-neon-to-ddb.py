"""
Migracion Neon Postgres -> AWS DynamoDB.

Ejecutar SOLO cuando AWS este operativo y el bug de transact_write_items
ya este resuelto. Ver docs/aws/GAS-AWS-DEPLOY-STATUS.md y
docs/deploy/GAS-FLY-TO-AWS-MIGRATION.md.

Diferencias de schema importantes:
- PG usa PK enteros autoincrementales. DDB usa UUID strings.
- El script genera UUIDs nuevos y mantiene un diccionario in-memory
  de remapeo old_int_id -> new_uuid_str para preservar las FK.
- En PG cada Cliente tiene N Direcciones. En DDB la direccion es un
  campo del Cliente (mvp). Se toma la primera direccion activa de cada
  cliente como `direccion` del DDB cliente.
- En PG StockJornada tiene id int + fecha unica. En DDB usa fecha
  (string YYYY-MM-DD) como hash key. No hay remapeo necesario.

Uso:
    python scripts/migrate-neon-to-ddb.py \\
        --pg-url "postgresql://...neon.tech/db?sslmode=require" \\
        --aws-profile gas-dev \\
        --aws-region us-east-1 \\
        --env-prefix gas-dev \\
        [--dry-run]

Pre-requisitos:
    pip install psycopg[binary] boto3
    (ya estan en gas-backend/requirements.txt)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import boto3
import psycopg
from psycopg.rows import dict_row


def normalize_alias(alias: str) -> str:
    import re
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", alias.strip().lower())
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_accents).strip()


def alias_lock_id(alias_normalizado: str) -> str:
    return f"alias#{alias_normalizado}"


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def to_iso(dt: Any) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def to_centavos(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int((value * 100).to_integral_value())
    if isinstance(value, float):
        return int(round(value * 100))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass
class IdMaps:
    cliente: dict[int, str] = field(default_factory=dict)
    direccion: dict[int, str] = field(default_factory=dict)
    direccion_cliente: dict[int, int] = field(default_factory=dict)
    pedido: dict[int, str] = field(default_factory=dict)
    stock_jornada_fecha: dict[int, str] = field(default_factory=dict)


@dataclass
class Counts:
    clientes_pg: int = 0
    pedidos_pg: int = 0
    stock_jornadas_pg: int = 0
    movimientos_pg: int = 0
    clientes_ddb_written: int = 0
    pedidos_ddb_written: int = 0
    stock_jornadas_ddb_written: int = 0
    movimientos_ddb_written: int = 0
    errors: list[str] = field(default_factory=list)


def fetch_pg_rows(pg_conn, sql: str) -> list[dict[str, Any]]:
    with pg_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return cur.fetchall()


def migrate_clientes(
    pg_conn,
    ddb,
    table_name: str,
    id_maps: IdMaps,
    counts: Counts,
    dry_run: bool,
) -> None:
    clientes = fetch_pg_rows(pg_conn, "SELECT id, alias, telefono, nombre FROM clientes ORDER BY id")
    counts.clientes_pg = len(clientes)
    direcciones = fetch_pg_rows(
        pg_conn,
        "SELECT id, cliente_id, texto_original, activa FROM direcciones ORDER BY cliente_id, id"
    )
    direcciones_por_cliente: dict[int, list[dict]] = {}
    for d in direcciones:
        direcciones_por_cliente.setdefault(d["cliente_id"], []).append(d)
        id_maps.direccion_cliente[d["id"]] = d["cliente_id"]

    table = ddb.Table(table_name)
    for c in clientes:
        new_id = str(uuid4())
        id_maps.cliente[c["id"]] = new_id
        alias = (c["alias"] or "").strip()
        if not alias:
            counts.errors.append(f"cliente pg_id={c['id']} sin alias")
            continue
        alias_norm = normalize_alias(alias)
        direcciones_cli = direcciones_por_cliente.get(c["id"], [])
        primera_activa = next((d for d in direcciones_cli if d.get("activa")), None)
        if primera_activa is None and direcciones_cli:
            primera_activa = direcciones_cli[0]
        direccion = (primera_activa["texto_original"] if primera_activa else alias)
        now = iso_now()
        cliente_item = {
            "cliente_id": new_id,
            "item_type": "CLIENTE",
            "alias": alias,
            "alias_normalizado": alias_norm,
            "telefono": (c["telefono"] or "").strip(),
            "direccion": direccion,
            "created_at": now,
            "updated_at": now,
        }
        alias_lock = {
            "cliente_id": alias_lock_id(alias_norm),
            "item_type": "ALIAS_UNICO",
            "alias_normalizado": alias_norm,
            "cliente_ref": new_id,
            "created_at": now,
        }
        if dry_run:
            print(f"[dry-run] cliente pg_id={c['id']} -> {new_id} (alias={alias})")
        else:
            try:
                table.put_item(Item=cliente_item, ConditionExpression="attribute_not_exists(cliente_id)")
                table.put_item(Item=alias_lock, ConditionExpression="attribute_not_exists(cliente_id)")
                counts.clientes_ddb_written += 1
            except Exception as e:
                counts.errors.append(f"cliente pg_id={c['id']} fallo: {e}")


def migrate_pedidos(
    pg_conn,
    ddb,
    table_name: str,
    id_maps: IdMaps,
    counts: Counts,
    dry_run: bool,
) -> None:
    pedidos = fetch_pg_rows(pg_conn, """
        SELECT p.id, p.cliente_id, p.fecha_entrega, p.cantidad_balones,
               p.total_soles, p.tipo_balon, p.marca_balon,
               p.precio_unitario_centavos, p.monto_total_centavos,
               p.monto_pendiente_centavos, p.pagado, p.saldo_pendiente,
               p.created_at, c.alias AS cliente_alias
          FROM pedidos p
          LEFT JOIN clientes c ON c.id = p.cliente_id
         ORDER BY p.id
    """)
    counts.pedidos_pg = len(pedidos)
    table = ddb.Table(table_name)
    for p in pedidos:
        new_cli = id_maps.cliente.get(p["cliente_id"])
        if not new_cli:
            counts.errors.append(f"pedido pg_id={p['id']}: cliente_id pg={p['cliente_id']} sin mapeo")
            continue
        new_pid = str(uuid4())
        id_maps.pedido[p["id"]] = new_pid
        total_centavos = (
            p["monto_total_centavos"]
            if p["monto_total_centavos"] is not None
            else to_centavos(p["total_soles"])
        )
        pendiente_centavos = (
            p["monto_pendiente_centavos"]
            if p["monto_pendiente_centavos"] is not None
            else to_centavos(p["saldo_pendiente"])
        )
        pagado_centavos = max(0, total_centavos - pendiente_centavos)
        pagado_bool = bool(p["pagado"]) and pendiente_centavos == 0
        item: dict[str, Any] = {
            "pedido_id": new_pid,
            "cliente_id": new_cli,
            "cliente_alias": (p.get("cliente_alias") or "").strip(),
            "fecha_entrega": str(p["fecha_entrega"]),
            "cantidad_balones": int(p["cantidad_balones"] or 0),
            "total_centavos": int(total_centavos),
            "pagado_centavos": int(pagado_centavos),
            "pendiente_centavos": int(pendiente_centavos),
            "pagado": pagado_bool,
            "tipo_balon": (p["tipo_balon"] or "NORMAL"),
            "marca_balon": (p["marca_balon"] or "PETROPERU"),
            "created_at": to_iso(p["created_at"]),
            "updated_at": to_iso(p["created_at"]),
        }
        if p["precio_unitario_centavos"] is not None:
            item["precio_unitario_centavos"] = int(p["precio_unitario_centavos"])
        if dry_run:
            print(f"[dry-run] pedido pg_id={p['id']} -> {new_pid} (cliente {new_cli}, fecha {item['fecha_entrega']})")
        else:
            try:
                table.put_item(Item=item, ConditionExpression="attribute_not_exists(pedido_id)")
                counts.pedidos_ddb_written += 1
            except Exception as e:
                counts.errors.append(f"pedido pg_id={p['id']} fallo: {e}")


def migrate_stock_jornadas(
    pg_conn,
    ddb,
    table_name: str,
    id_maps: IdMaps,
    counts: Counts,
    dry_run: bool,
) -> None:
    rows = fetch_pg_rows(pg_conn, """
        SELECT id, fecha, stock_inicial, stock_actual,
               stock_final_fisico, cerrado, created_at, updated_at
          FROM stock_jornadas ORDER BY fecha
    """)
    counts.stock_jornadas_pg = len(rows)
    table = ddb.Table(table_name)
    for r in rows:
        fecha_str = str(r["fecha"])
        id_maps.stock_jornada_fecha[r["id"]] = fecha_str
        item: dict[str, Any] = {
            "fecha": fecha_str,
            "stock_inicial": int(r["stock_inicial"] or 0),
            "stock_actual": int(r["stock_actual"] or 0),
            "cerrado": bool(r["cerrado"]),
            "created_at": to_iso(r["created_at"]),
            "updated_at": to_iso(r["updated_at"]),
        }
        if r["stock_final_fisico"] is not None:
            item["stock_final_fisico"] = int(r["stock_final_fisico"])
        if dry_run:
            print(f"[dry-run] stock_jornada fecha={fecha_str}")
        else:
            try:
                table.put_item(Item=item)
                counts.stock_jornadas_ddb_written += 1
            except Exception as e:
                counts.errors.append(f"stock_jornada fecha={fecha_str} fallo: {e}")


def migrate_movimientos(
    pg_conn,
    ddb,
    table_name: str,
    id_maps: IdMaps,
    counts: Counts,
    dry_run: bool,
) -> None:
    rows = fetch_pg_rows(pg_conn, """
        SELECT id, stock_jornada_id, fecha, tipo, cantidad_delta,
               stock_resultante, pedido_id, marca_balon, tipo_balon,
               observacion, created_at
          FROM movimientos_stock ORDER BY id
    """)
    counts.movimientos_pg = len(rows)
    table = ddb.Table(table_name)
    for r in rows:
        new_mid = str(uuid4())
        item: dict[str, Any] = {
            "movimiento_id": new_mid,
            "fecha": str(r["fecha"]),
            "tipo": r["tipo"],
            "cantidad_delta": int(r["cantidad_delta"] or 0),
            "stock_resultante": int(r["stock_resultante"] or 0),
            "created_at": to_iso(r["created_at"]),
        }
        if r["pedido_id"] is not None:
            mapped = id_maps.pedido.get(r["pedido_id"])
            if mapped:
                item["pedido_id"] = mapped
        if r["marca_balon"]:
            item["marca_balon"] = r["marca_balon"]
        if r["tipo_balon"]:
            item["tipo_balon"] = r["tipo_balon"]
        if r["observacion"]:
            item["observacion"] = r["observacion"]
        if dry_run:
            print(f"[dry-run] movimiento pg_id={r['id']} -> {new_mid}")
        else:
            try:
                table.put_item(Item=item, ConditionExpression="attribute_not_exists(movimiento_id)")
                counts.movimientos_ddb_written += 1
            except Exception as e:
                counts.errors.append(f"movimiento pg_id={r['id']} fallo: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migra Neon Postgres a DynamoDB GAS")
    parser.add_argument("--pg-url", required=True, help="Connection string Postgres (direct, no pooled)")
    parser.add_argument("--aws-profile", default="gas-dev")
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--env-prefix", default="gas-dev", help="Prefijo tablas DDB (gas-dev / gas-prd)")
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada, solo simula")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.aws_profile, region_name=args.aws_region)
    ddb = session.resource("dynamodb")

    tables = {
        "clientes": f"{args.env_prefix}-clientes",
        "pedidos": f"{args.env_prefix}-pedidos",
        "stock_jornadas": f"{args.env_prefix}-stock-jornadas",
        "movimientos_stock": f"{args.env_prefix}-movimientos-stock",
    }
    if not args.dry_run:
        try:
            ddb.Table(tables["clientes"]).load()
        except Exception as e:
            print(f"[ERROR] No se puede acceder a {tables['clientes']}: {e}", file=sys.stderr)
            return 2

    id_maps = IdMaps()
    counts = Counts()

    print(f"Conectando a Postgres...")
    with psycopg.connect(args.pg_url, autocommit=True) as pg_conn:
        print("Migrando clientes...")
        migrate_clientes(pg_conn, ddb, tables["clientes"], id_maps, counts, args.dry_run)
        print("Migrando pedidos...")
        migrate_pedidos(pg_conn, ddb, tables["pedidos"], id_maps, counts, args.dry_run)
        print("Migrando stock_jornadas...")
        migrate_stock_jornadas(pg_conn, ddb, tables["stock_jornadas"], id_maps, counts, args.dry_run)
        print("Migrando movimientos_stock...")
        migrate_movimientos(pg_conn, ddb, tables["movimientos_stock"], id_maps, counts, args.dry_run)

    print("\n=========== Resumen ===========")
    print(f"  clientes PG -> DDB:    {counts.clientes_pg} -> {counts.clientes_ddb_written}")
    print(f"  pedidos PG -> DDB:     {counts.pedidos_pg} -> {counts.pedidos_ddb_written}")
    print(f"  stock_jornadas PG -> DDB: {counts.stock_jornadas_pg} -> {counts.stock_jornadas_ddb_written}")
    print(f"  movimientos PG -> DDB: {counts.movimientos_pg} -> {counts.movimientos_ddb_written}")
    print(f"  errores: {len(counts.errors)}")
    for e in counts.errors[:20]:
        print(f"    - {e}")
    if len(counts.errors) > 20:
        print(f"    ... y {len(counts.errors) - 20} mas")
    return 0 if not counts.errors else 1


if __name__ == "__main__":
    sys.exit(main())
