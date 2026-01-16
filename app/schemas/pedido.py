from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field

class PedidoCreate(BaseModel):
    cliente_id: int
    fecha_entrega: date | None = None
    cantidad_balones: int = Field(ge=1, le=20)
    total_soles: int = Field(ge=0)
    pagado: bool = True
    saldo_pendiente: int | None = Field(default=None, ge=0)
    observacion: str | None = Field(default=None, max_length=250)

class PedidoOut(BaseModel):
    id: int
    cliente_id: int
    direccion_id: int
    created_at: datetime
    fecha_entrega: date
    cantidad_balones: int
    total_soles: int
    pagado: bool
    saldo_pendiente: int

    class Config:
        from_attributes = True
