from pydantic import BaseModel, Field, model_validator
from datetime import date

CANAL_VOLANTE = "VOLANTE"
CANAL_FACEBOOK = "FACEBOOK"
CANAL_RECOMENDACION = "RECOMENDACION"
CANAL_CARTEL = "CARTEL"
CANAL_ANTIGUO = "ANTIGUO"
CANAL_OTRO = "OTRO"
CANALES_CAPTACION_VALIDOS = {
    CANAL_VOLANTE,
    CANAL_FACEBOOK,
    CANAL_RECOMENDACION,
    CANAL_CARTEL,
    CANAL_ANTIGUO,
    CANAL_OTRO,
}


class ClienteCreate(BaseModel):
    alias: str = Field(min_length=3, max_length=120, description="Ej: Las Higueras 371")
    telefono: str = Field(min_length=6, max_length=30)
    # P1 #1: opcional (cero friccion). Se pregunta una vez, en el alta.
    canal_captacion: str | None = None

    @model_validator(mode="after")
    def validar_canal(self) -> "ClienteCreate":
        if self.canal_captacion is not None:
            self.canal_captacion = self.canal_captacion.upper()
            if self.canal_captacion not in CANALES_CAPTACION_VALIDOS:
                raise ValueError(
                    "canal_captacion debe ser VOLANTE, FACEBOOK, RECOMENDACION, "
                    "CARTEL, ANTIGUO u OTRO"
                )
        return self


class ClienteOut(BaseModel):
    id: int | str
    alias: str
    telefono: str
    direccion: str
    canal_captacion: str | None = None

    class Config:
        from_attributes = True


class ClienteRecienteOut(BaseModel):
    id: int | str
    alias: str
    telefono: str
    direccion: str
    ultimo_pedido_fecha: date
    ultimo_total_centavos: int
    canal_captacion: str | None = None
