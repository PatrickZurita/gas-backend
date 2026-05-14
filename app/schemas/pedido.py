from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

TIPO_BALON_NORMAL = "NORMAL"
TIPO_BALON_PREMIUM = "PREMIUM"
MARCA_BALON_SOLGAS = "SOLGAS"
MARCA_BALON_PETROPERU = "PETROPERU"
TIPOS_BALON_VALIDOS = {TIPO_BALON_NORMAL, TIPO_BALON_PREMIUM}
MARCAS_BALON_VALIDAS = {MARCA_BALON_SOLGAS, MARCA_BALON_PETROPERU}

class PedidoCreate(BaseModel):
    cliente_id: int | str
    fecha_entrega: date | None = None
    cantidad_balones: int = Field(ge=1, le=20)
    total_soles: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    tipo_balon: str = TIPO_BALON_NORMAL
    marca_balon: str = MARCA_BALON_PETROPERU
    precio_unitario_centavos: int | None = Field(default=None, ge=0)
    monto_total_centavos: int | None = Field(default=None, ge=0)
    pagado: bool = True
    saldo_pendiente: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    monto_pendiente_centavos: int | None = Field(default=None, ge=0)
    observacion: str | None = Field(default=None, max_length=250)

    @model_validator(mode="after")
    def validar_contrato(self) -> "PedidoCreate":
        self.tipo_balon = self.tipo_balon.upper()
        self.marca_balon = self.marca_balon.upper()

        if self.tipo_balon not in TIPOS_BALON_VALIDOS:
            raise ValueError("tipo_balon debe ser NORMAL o PREMIUM")
        if self.marca_balon not in MARCAS_BALON_VALIDAS:
            raise ValueError("marca_balon debe ser SOLGAS o PETROPERU")
        if self.total_soles is None and self.monto_total_centavos is None:
            if self.precio_unitario_centavos is None:
                raise ValueError(
                    "Enviar total_soles, monto_total_centavos o "
                    "precio_unitario_centavos"
                )
        if (
            self.monto_total_centavos is not None
            and self.monto_pendiente_centavos is not None
            and self.monto_pendiente_centavos > self.monto_total_centavos
        ):
            raise ValueError(
                "monto_pendiente_centavos no puede ser mayor que "
                "monto_total_centavos"
            )
        return self

class PedidoOut(BaseModel):
    id: int | str
    cliente_id: int | str
    direccion_id: int | str
    created_at: datetime
    fecha_entrega: date
    cantidad_balones: int
    total_soles: Decimal
    tipo_balon: str
    marca_balon: str
    precio_unitario_centavos: int | None
    monto_total_centavos: int | None
    pagado: bool
    saldo_pendiente: Decimal
    monto_pendiente_centavos: int | None

    class Config:
        from_attributes = True
