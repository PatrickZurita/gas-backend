from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

TIPO_BALON_NORMAL = "NORMAL"
TIPO_BALON_PREMIUM = "PREMIUM"
MARCA_BALON_SOLGAS = "SOLGAS"
MARCA_BALON_PETROPERU = "PETROPERU"
TIPOS_BALON_VALIDOS = {TIPO_BALON_NORMAL, TIPO_BALON_PREMIUM}
MARCAS_BALON_VALIDAS = {MARCA_BALON_SOLGAS, MARCA_BALON_PETROPERU}

PESOS_BALON_VALIDOS = {10, 45}

METODO_PAGO_EFECTIVO = "EFECTIVO"
METODO_PAGO_YAPE = "YAPE"
METODOS_PAGO_VALIDOS = {METODO_PAGO_EFECTIVO, METODO_PAGO_YAPE}


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
    peso_balon_kg: int = Field(default=10)
    metodo_pago: str | None = None

    @model_validator(mode="after")
    def validar_contrato(self) -> "PedidoCreate":
        self.tipo_balon = self.tipo_balon.upper()
        self.marca_balon = self.marca_balon.upper()

        if self.tipo_balon not in TIPOS_BALON_VALIDOS:
            raise ValueError("tipo_balon debe ser NORMAL o PREMIUM")
        if self.marca_balon not in MARCAS_BALON_VALIDAS:
            raise ValueError("marca_balon debe ser SOLGAS o PETROPERU")
        if self.peso_balon_kg not in PESOS_BALON_VALIDOS:
            raise ValueError("peso_balon_kg debe ser 10 o 45")
        if self.metodo_pago is not None:
            self.metodo_pago = self.metodo_pago.upper()
            if self.metodo_pago not in METODOS_PAGO_VALIDOS:
                raise ValueError("metodo_pago debe ser EFECTIVO o YAPE")
            if not self.pagado:
                raise ValueError(
                    "metodo_pago solo aplica cuando pagado=True"
                )
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
    estado: str = "ACTIVO"
    anulado_at: datetime | None = None
    anulado_motivo: str | None = None
    peso_balon_kg: int = 10
    metodo_pago: str | None = None

    class Config:
        from_attributes = True


class PedidoAnularRequest(BaseModel):
    motivo: str | None = Field(default=None, max_length=250)


class PedidoPatch(BaseModel):
    cantidad_balones: int | None = Field(default=None, ge=1, le=20)
    precio_unitario_centavos: int | None = Field(default=None, ge=0)
    monto_total_centavos: int | None = Field(default=None, ge=0)
    monto_pendiente_centavos: int | None = Field(default=None, ge=0)
    pagado: bool | None = None
    fecha_entrega: date | None = None
    peso_balon_kg: int | None = None
    metodo_pago: str | None = None
    motivo_edicion: str | None = Field(default=None, max_length=250)

    @model_validator(mode="after")
    def validar_patch(self) -> "PedidoPatch":
        if self.peso_balon_kg is not None and self.peso_balon_kg not in (10, 45):
            raise ValueError("peso_balon_kg debe ser 10 o 45")
        if self.metodo_pago is not None:
            self.metodo_pago = self.metodo_pago.upper()
            if self.metodo_pago not in METODOS_PAGO_VALIDOS:
                raise ValueError("metodo_pago debe ser EFECTIVO o YAPE")
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
