"""Service `reportes` con dispatch PostgreSQL/DynamoDB."""

from __future__ import annotations

from calendar import monthrange
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.core.storage import is_dynamodb_enabled
from app.core.time import fecha_hoy_lima
from app.schemas.reportes import (
    PedidoDeudaOut,
    PedidoReporteDiaOut,
    ReporteDeudasOut,
    ReporteDiaOut,
    ResumenDiaDetalle,
    ResumenMes,
    ResumenSemana,
)
from app.services import stock as service_stock

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _require_db(db: "Session | None") -> "Session":
    if db is None:
        raise RuntimeError(
            "Servicio PostgreSQL requiere sesion; "
            "storage actual no esta inyectando una."
        )
    return db


def _ddb_pedido_to_reporte_dia(p) -> PedidoReporteDiaOut:
    try:
        fecha = date_cls.fromisoformat(p.fecha_entrega)
    except ValueError:
        fecha = fecha_hoy_lima()
    try:
        created_at = datetime.fromisoformat(p.created_at)
    except ValueError:
        created_at = datetime.utcnow()
    return PedidoReporteDiaOut(
        id=p.id,
        cliente_id=p.cliente_id,
        cliente_alias=p.cliente_alias,
        cantidad_balones=p.cantidad_balones,
        tipo_balon=p.tipo_balon,
        marca_balon=p.marca_balon,
        precio_unitario_centavos=p.precio_unitario_centavos,
        monto_total_centavos=p.total_centavos,
        monto_pendiente_centavos=p.pendiente_centavos,
        pagado=p.pagado,
        fecha_entrega=fecha,
        created_at=created_at,
        peso_balon_kg=getattr(p, "peso_balon_kg", 10),
        metodo_pago=getattr(p, "metodo_pago", None),
    )


def _ddb_pedido_to_deuda(p) -> PedidoDeudaOut:
    base = _ddb_pedido_to_reporte_dia(p)
    return PedidoDeudaOut(**base.model_dump())


def _cobrado_por_metodo(
    pedidos: list, get_pagado, get_metodo, get_cobrado_centavos
) -> tuple[int, int]:
    """Suma lo cobrado por metodo de pago.

    Solo cuenta pedidos pagado=True con metodo seteado. Pedidos pagados
    sin metodo (legacy o creados antes de V2.6) no se atribuyen a ningun
    bucket para que la suma efectivo+yape <= cobrado_total.
    """
    efectivo = 0
    yape = 0
    for p in pedidos:
        if not get_pagado(p):
            continue
        metodo = get_metodo(p)
        if metodo is None:
            continue
        metodo_up = str(metodo).upper()
        cobrado = get_cobrado_centavos(p)
        if metodo_up == "YAPE":
            yape += cobrado
        elif metodo_up == "EFECTIVO":
            efectivo += cobrado
    return efectivo, yape


def reporte_dia(db: "Session | None", *, fecha: date_cls) -> ReporteDiaOut:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories import pedidos as ddb_pedidos

        items = ddb_pedidos.listar_pedidos_por_fecha(fecha.isoformat())
        pedidos_out = [_ddb_pedido_to_reporte_dia(p) for p in items]
        monto_total = sum(p.monto_total_centavos for p in pedidos_out)
        monto_pendiente = sum(p.monto_pendiente_centavos for p in pedidos_out)
        efectivo, yape = _cobrado_por_metodo(
            pedidos_out,
            lambda p: p.pagado,
            lambda p: p.metodo_pago,
            lambda p: p.monto_total_centavos - p.monto_pendiente_centavos,
        )
        return ReporteDiaOut(
            fecha=fecha,
            pedidos_count=len(pedidos_out),
            balones_vendidos=sum(p.cantidad_balones for p in pedidos_out),
            monto_total_centavos=monto_total,
            monto_pagado_centavos=monto_total - monto_pendiente,
            monto_pendiente_centavos=monto_pendiente,
            monto_cobrado_efectivo_centavos=efectivo,
            monto_cobrado_yape_centavos=yape,
            stock=service_stock.resumen(db, fecha=fecha),
            pedidos=pedidos_out,
        )

    from app.infrastructure.repositories import reportes as repo_reportes

    session = _require_db(db)
    pedidos = repo_reportes.listar_pedidos_por_fecha(session, fecha_entrega=fecha)
    monto_total = sum(p["monto_total_centavos"] for p in pedidos)
    monto_pendiente = sum(p["monto_pendiente_centavos"] for p in pedidos)
    efectivo, yape = _cobrado_por_metodo(
        pedidos,
        lambda p: p["pagado"],
        lambda p: p.get("metodo_pago"),
        lambda p: p["monto_total_centavos"] - p["monto_pendiente_centavos"],
    )
    return ReporteDiaOut(
        fecha=fecha,
        pedidos_count=len(pedidos),
        balones_vendidos=sum(p["cantidad_balones"] for p in pedidos),
        monto_total_centavos=monto_total,
        monto_pagado_centavos=monto_total - monto_pendiente,
        monto_pendiente_centavos=monto_pendiente,
        monto_cobrado_efectivo_centavos=efectivo,
        monto_cobrado_yape_centavos=yape,
        stock=service_stock.resumen(db, fecha=fecha),
        pedidos=pedidos,
    )


def reporte_deudas(db: "Session | None") -> ReporteDeudasOut:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories.reportes import (
            _scan_all_pedidos,
        )

        all_pedidos = _scan_all_pedidos()
        con_deuda = [p for p in all_pedidos if p.pendiente_centavos > 0]
        con_deuda.sort(
            key=lambda p: (p.fecha_entrega, p.created_at),
            reverse=True,
        )
        items = [_ddb_pedido_to_deuda(p) for p in con_deuda]
        return ReporteDeudasOut(
            pedidos_count=len(items),
            monto_pendiente_centavos=sum(p.monto_pendiente_centavos for p in items),
            pedidos=items,
        )

    from app.infrastructure.repositories import reportes as repo_reportes

    session = _require_db(db)
    pedidos = repo_reportes.listar_pedidos_con_deuda(session)
    return ReporteDeudasOut(
        pedidos_count=len(pedidos),
        monto_pendiente_centavos=sum(p["monto_pendiente_centavos"] for p in pedidos),
        pedidos=pedidos,
    )


# ---------------------------------------------------------------------------
# V4: reportes semana y mes
# ---------------------------------------------------------------------------


def _monto_total_centavos_ddb(p) -> int:
    return p.total_centavos


def _monto_pendiente_centavos_ddb(p) -> int:
    return p.pendiente_centavos


def _agrupar_por_dia(pedidos_rows: list[dict] | list) -> dict[date_cls, dict]:
    """Agrupa pedidos por `fecha_entrega` y suma metricas por dia.

    Acepta dicts (PostgreSQL row TypedDict) o DynamoPedido. Detecta el
    formato por la presencia de la clave `id` como int (PG) o por el
    atributo `total_centavos` (DDB).
    """
    by_day: dict[date_cls, dict] = {}
    for row in pedidos_rows:
        if isinstance(row, dict):
            fecha = row["fecha_entrega"]
            cantidad = row["cantidad_balones"]
            peso = row.get("peso_balon_kg") or 10
            monto_total = row["monto_total_centavos"]
            monto_pendiente = row["monto_pendiente_centavos"]
            pagado = row.get("pagado", False)
            metodo = row.get("metodo_pago")
        else:
            try:
                fecha = date_cls.fromisoformat(row.fecha_entrega)
            except (TypeError, ValueError):
                continue
            cantidad = row.cantidad_balones
            peso = getattr(row, "peso_balon_kg", 10) or 10
            monto_total = row.total_centavos
            monto_pendiente = row.pendiente_centavos
            pagado = getattr(row, "pagado", False)
            metodo = getattr(row, "metodo_pago", None)

        bucket = by_day.setdefault(
            fecha,
            {
                "pedidos_count": 0,
                "balones_10kg": 0,
                "balones_45kg": 0,
                "vendido_centavos": 0,
                "cobrado_centavos": 0,
                "pendiente_centavos": 0,
                "cobrado_efectivo_centavos": 0,
                "cobrado_yape_centavos": 0,
            },
        )
        bucket["pedidos_count"] += 1
        if int(peso) == 45:
            bucket["balones_45kg"] += cantidad
        else:
            bucket["balones_10kg"] += cantidad
        bucket["vendido_centavos"] += monto_total
        cobrado_pedido = monto_total - monto_pendiente
        bucket["cobrado_centavos"] += cobrado_pedido
        bucket["pendiente_centavos"] += monto_pendiente
        if pagado and metodo is not None:
            metodo_up = str(metodo).upper()
            if metodo_up == "YAPE":
                bucket["cobrado_yape_centavos"] += cobrado_pedido
            elif metodo_up == "EFECTIVO":
                bucket["cobrado_efectivo_centavos"] += cobrado_pedido
    return by_day


def _construir_dias_detalle(
    by_day: dict[date_cls, dict],
    desde: date_cls,
    hasta: date_cls,
    db: "Session | None",
) -> list[ResumenDiaDetalle]:
    detalles: list[ResumenDiaDetalle] = []
    actual = desde
    while actual <= hasta:
        info = by_day.get(actual)
        stock_info = _stock_resumen_para_reporte(db, actual)
        if info is None:
            detalles.append(
                ResumenDiaDetalle(
                    fecha=actual,
                    pedidos_count=0,
                    balones_10kg=0,
                    balones_45kg=0,
                    compras_10kg=stock_info["compras_10kg"],
                    compras_45kg=stock_info["compras_45kg"],
                    stock_final_10kg=stock_info["stock_final_10kg"],
                    stock_final_45kg=stock_info["stock_final_45kg"],
                    vendido_centavos=0,
                    cobrado_centavos=0,
                    pendiente_centavos=0,
                )
            )
        else:
            detalles.append(
                ResumenDiaDetalle(fecha=actual, **info, **stock_info)
            )
        actual = actual + timedelta(days=1)
    return detalles


def _stock_resumen_para_reporte(db: "Session | None", fecha: date_cls) -> dict:
    resumen = service_stock.resumen(db, fecha=fecha)
    por_peso = resumen.por_peso
    if por_peso is None:
        return {
            "compras_10kg": 0,
            "compras_45kg": 0,
            "stock_final_10kg": 0,
            "stock_final_45kg": 0,
        }
    return {
        "compras_10kg": por_peso.diez_kg.compras,
        "compras_45kg": por_peso.cuarenta_y_cinco_kg.compras,
        "stock_final_10kg": por_peso.diez_kg.stock_disponible,
        "stock_final_45kg": por_peso.cuarenta_y_cinco_kg.stock_disponible,
    }


def _totales_desde_dias(dias: list[ResumenDiaDetalle]) -> dict:
    return {
        "total_pedidos": sum(d.pedidos_count for d in dias),
        "total_vendido_centavos": sum(d.vendido_centavos for d in dias),
        "total_cobrado_centavos": sum(d.cobrado_centavos for d in dias),
        "total_pendiente_centavos": sum(d.pendiente_centavos for d in dias),
        "total_cobrado_efectivo_centavos": sum(
            d.cobrado_efectivo_centavos for d in dias
        ),
        "total_cobrado_yape_centavos": sum(d.cobrado_yape_centavos for d in dias),
        "balones_10kg": sum(d.balones_10kg for d in dias),
        "balones_45kg": sum(d.balones_45kg for d in dias),
        "total_compras_10kg": sum(d.compras_10kg for d in dias),
        "total_compras_45kg": sum(d.compras_45kg for d in dias),
    }


def reporte_semana(db: "Session | None", *, desde: date_cls) -> ResumenSemana:
    hasta = desde + timedelta(days=6)
    pedidos_rows = _listar_pedidos_rango(db, desde=desde, hasta=hasta)
    by_day = _agrupar_por_dia(pedidos_rows)
    dias = _construir_dias_detalle(by_day, desde, hasta, db)
    totales = _totales_desde_dias(dias)
    return ResumenSemana(desde=desde, hasta=hasta, dias=dias, **totales)


def reporte_mes(db: "Session | None", *, mes: str) -> ResumenMes:
    """`mes` en formato YYYY-MM."""
    try:
        anio_str, mes_str = mes.split("-")
        anio = int(anio_str)
        mes_num = int(mes_str)
        if not (1 <= mes_num <= 12):
            raise ValueError("mes fuera de rango")
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Formato de mes invalido: '{mes}'. Use YYYY-MM.") from exc

    desde = date_cls(anio, mes_num, 1)
    _, ultimo = monthrange(anio, mes_num)
    hasta = date_cls(anio, mes_num, ultimo)
    pedidos_rows = _listar_pedidos_rango(db, desde=desde, hasta=hasta)
    by_day = _agrupar_por_dia(pedidos_rows)
    dias = _construir_dias_detalle(by_day, desde, hasta, db)
    totales = _totales_desde_dias(dias)
    return ResumenMes(desde=desde, hasta=hasta, mes=mes, dias=dias, **totales)


def _listar_pedidos_rango(
    db: "Session | None",
    *,
    desde: date_cls,
    hasta: date_cls,
) -> list:
    if is_dynamodb_enabled():
        from app.infrastructure.dynamodb.repositories.reportes import (
            _scan_all_pedidos,
        )

        # _scan_all_pedidos ya excluye ANULADO; filtramos por rango en memoria
        # (volumen MVP). Para AWS produccion con volumen alto, GSI por fecha.
        items = []
        for p in _scan_all_pedidos():
            try:
                fecha = date_cls.fromisoformat(p.fecha_entrega)
            except (TypeError, ValueError):
                continue
            if desde <= fecha <= hasta:
                items.append(p)
        return items

    from app.infrastructure.repositories import reportes as repo_reportes

    session = _require_db(db)
    pedidos = repo_reportes.listar_pedidos_por_rango(
        session, desde=desde, hasta=hasta
    )
    rows: list[dict] = []
    for p in pedidos:
        monto_total = (
            p.monto_total_centavos
            if p.monto_total_centavos is not None
            else int(p.total_soles * 100)
        )
        monto_pendiente = (
            p.monto_pendiente_centavos
            if p.monto_pendiente_centavos is not None
            else int(p.saldo_pendiente * 100)
        )
        rows.append(
            {
                "fecha_entrega": p.fecha_entrega,
                "cantidad_balones": p.cantidad_balones,
                "peso_balon_kg": p.peso_balon_kg or 10,
                "monto_total_centavos": monto_total,
                "monto_pendiente_centavos": monto_pendiente,
                "pagado": p.pagado,
                "metodo_pago": p.metodo_pago,
            }
        )
    return rows
