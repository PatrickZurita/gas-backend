from datetime import date, datetime
from pydantic import BaseModel

from app.schemas.stock import StockResumenOut


class PedidoReporteDiaOut(BaseModel):
    id: int | str
    cliente_id: int | str
    cliente_alias: str
    cantidad_balones: int
    tipo_balon: str
    marca_balon: str
    precio_unitario_centavos: int | None
    monto_total_centavos: int
    monto_pendiente_centavos: int
    pagado: bool
    fecha_entrega: date
    created_at: datetime
    peso_balon_kg: int = 10
    metodo_pago: str | None = None


class ReporteDiaOut(BaseModel):
    fecha: date
    pedidos_count: int
    balones_vendidos: int
    monto_total_centavos: int
    monto_pagado_centavos: int
    monto_pendiente_centavos: int
    # V2.8: breakdown del cobrado por metodo de pago para control de caja.
    # Solo cuenta pedidos pagado=True con metodo_pago seteado. Pedidos
    # pagados sin metodo (legacy o cobrados antes de V2.6) se omiten.
    monto_cobrado_efectivo_centavos: int = 0
    monto_cobrado_yape_centavos: int = 0
    stock: StockResumenOut
    pedidos: list[PedidoReporteDiaOut]


class PedidoDeudaOut(BaseModel):
    id: int | str
    cliente_id: int | str
    cliente_alias: str
    cantidad_balones: int
    tipo_balon: str
    marca_balon: str
    precio_unitario_centavos: int | None
    monto_total_centavos: int
    monto_pendiente_centavos: int
    pagado: bool
    fecha_entrega: date
    created_at: datetime
    peso_balon_kg: int = 10
    metodo_pago: str | None = None


class ReporteDeudasOut(BaseModel):
    pedidos_count: int
    monto_pendiente_centavos: int
    pedidos: list[PedidoDeudaOut]


class ResumenDiaDetalle(BaseModel):
    """Detalle agregado de un dia operativo (V4 reportes semanal/mensual)."""

    fecha: date
    pedidos_count: int
    balones_10kg: int
    balones_45kg: int
    vendido_centavos: int
    cobrado_centavos: int
    pendiente_centavos: int
    # V2.8: breakdown del cobrado por metodo de pago.
    cobrado_efectivo_centavos: int = 0
    cobrado_yape_centavos: int = 0


class ResumenSemana(BaseModel):
    desde: date
    hasta: date
    total_pedidos: int
    total_vendido_centavos: int
    total_cobrado_centavos: int
    total_pendiente_centavos: int
    # V2.8: breakdown del cobrado por metodo de pago en el rango completo.
    total_cobrado_efectivo_centavos: int = 0
    total_cobrado_yape_centavos: int = 0
    balones_10kg: int
    balones_45kg: int
    dias: list[ResumenDiaDetalle]


class ResumenMes(BaseModel):
    desde: date
    hasta: date
    mes: str  # YYYY-MM
    total_pedidos: int
    total_vendido_centavos: int
    total_cobrado_centavos: int
    total_pendiente_centavos: int
    total_cobrado_efectivo_centavos: int = 0
    total_cobrado_yape_centavos: int = 0
    balones_10kg: int
    balones_45kg: int
    dias: list[ResumenDiaDetalle]
