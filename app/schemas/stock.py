from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

PESOS_BALON_VALIDOS = {10, 45}


def _validar_peso_opcional(value: int | None) -> int | None:
    if value is not None and value not in PESOS_BALON_VALIDOS:
        raise ValueError("peso_balon_kg debe ser 10 o 45")
    return value


class StockIniciarDiaIn(BaseModel):
    fecha: date | None = None
    stock_inicial: int = Field(ge=0)
    observacion: str | None = Field(default=None, max_length=250)


class StockEntradaIn(BaseModel):
    fecha: date | None = None
    cantidad: int = Field(gt=0)
    observacion: str | None = Field(default=None, max_length=250)
    peso_balon_kg: int | None = None

    @field_validator("peso_balon_kg")
    @classmethod
    def _check_peso(cls, value: int | None) -> int | None:
        return _validar_peso_opcional(value)


class StockAjusteIn(BaseModel):
    fecha: date | None = None
    stock_fisico: int = Field(ge=0)
    observacion: str | None = Field(default=None, max_length=250)
    peso_balon_kg: int | None = None

    @field_validator("peso_balon_kg")
    @classmethod
    def _check_peso(cls, value: int | None) -> int | None:
        return _validar_peso_opcional(value)


class MovimientoStockOut(BaseModel):
    id: int | str
    tipo: str
    cantidad_delta: int
    stock_resultante: int
    pedido_id: int | str | None
    observacion: str | None
    created_at: datetime
    peso_balon_kg: int | None = None

    class Config:
        from_attributes = True


class StockPorPesoOut(BaseModel):
    salidas: int = 0
    entradas: int = 0
    reversas: int = 0
    ajustes: int = 0
    stock_disponible: int = 0


class StockPorPesoBloqueOut(BaseModel):
    """Bloque informativo de stock segregado por peso 10kg / 45kg.

    `stock_disponible` parte del stock_inicial global (legado, sin peso) +
    movimientos de cada peso. Movimientos legacy sin `peso_balon_kg` van
    al bucket `10kg`.
    """

    diez_kg: StockPorPesoOut = Field(default_factory=StockPorPesoOut, alias="10kg")
    cuarenta_y_cinco_kg: StockPorPesoOut = Field(
        default_factory=StockPorPesoOut, alias="45kg"
    )

    class Config:
        populate_by_name = True


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
    por_peso: StockPorPesoBloqueOut | None = None


class StockDiaOut(StockResumenOut):
    movimientos: list[MovimientoStockOut] = Field(default_factory=list)


class StockOperacionOut(BaseModel):
    fecha: date
    tipo: str
    cantidad_delta: int
    stock_actual: int
    observacion: str | None = None


class StockContinuarPreviewOut(BaseModel):
    """Vista previa del stock disponible para arrastrar de la ultima
    jornada anterior (si existe).
    """

    puede_continuar: bool
    fecha_origen: date | None = None
    stock_10kg: int = 0
    stock_45kg: int = 0
