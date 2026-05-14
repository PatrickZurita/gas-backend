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


class ReporteDiaOut(BaseModel):
    fecha: date
    pedidos_count: int
    balones_vendidos: int
    monto_total_centavos: int
    monto_pagado_centavos: int
    monto_pendiente_centavos: int
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


class ReporteDeudasOut(BaseModel):
    pedidos_count: int
    monto_pendiente_centavos: int
    pedidos: list[PedidoDeudaOut]
