from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field

class PedidoCreate(BaseModel):
    cliente_id: int
    fecha_pedido: date
    cantidad_balones: int = Field(ge=1, le=20)
    total_soles: Decimal = Field(ge=0)
    pagado: bool = True
    saldo_pendiente: Decimal = Field(ge=0, default=Decimal("0.00"))
    observacion: str | None = Field(default=None, max_length=250)

class PedidoOut(BaseModel):
    id: int
    cliente_id: int
    direccion_id: int
    fecha_pedido: date
    cantidad_balones: int
    total_soles: Decimal
    pagado: bool
    saldo_pendiente: Decimal

    class Config:
        from_attributes = True
