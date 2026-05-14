from datetime import date, datetime

from pydantic import BaseModel, Field


class StockIniciarDiaIn(BaseModel):
    fecha: date | None = None
    stock_inicial: int = Field(ge=0)
    observacion: str | None = Field(default=None, max_length=250)


class StockEntradaIn(BaseModel):
    fecha: date | None = None
    cantidad: int = Field(gt=0)
    observacion: str | None = Field(default=None, max_length=250)


class StockAjusteIn(BaseModel):
    fecha: date | None = None
    stock_fisico: int = Field(ge=0)
    observacion: str | None = Field(default=None, max_length=250)


class MovimientoStockOut(BaseModel):
    id: int | str
    tipo: str
    cantidad_delta: int
    stock_resultante: int
    pedido_id: int | str | None
    observacion: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class StockResumenOut(BaseModel):
    fecha: date
    stock_iniciado: bool
    stock_inicial: int | None = None
    entradas: int = 0
    salidas: int = 0
    ajustes: int = 0
    stock_actual: int | None = None
    stock_final_fisico: int | None = None
    cerrado: bool = False


class StockDiaOut(StockResumenOut):
    movimientos: list[MovimientoStockOut] = Field(default_factory=list)


class StockOperacionOut(BaseModel):
    fecha: date
    tipo: str
    cantidad_delta: int
    stock_actual: int
    observacion: str | None = None
