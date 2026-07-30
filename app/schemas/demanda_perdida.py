"""Schemas de demanda perdida (P1 #2): la llamada que NO se pudo atender."""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

MOTIVO_SIN_STOCK = "SIN_STOCK"
MOTIVO_FUERA_DE_ZONA = "FUERA_DE_ZONA"
MOTIVO_SATURADO = "SATURADO"
MOTIVO_OTRO = "OTRO"
MOTIVOS_VALIDOS = {
    MOTIVO_SIN_STOCK,
    MOTIVO_FUERA_DE_ZONA,
    MOTIVO_SATURADO,
    MOTIVO_OTRO,
}
PESOS_BALON_VALIDOS = {10, 45}


class DemandaPerdidaCreate(BaseModel):
    motivo: str
    zona_texto: str | None = Field(default=None, max_length=120)
    cantidad_balones: int = Field(default=1, ge=1, le=20)
    peso_balon_kg: int = Field(default=10)

    @model_validator(mode="after")
    def validar_contrato(self) -> "DemandaPerdidaCreate":
        self.motivo = self.motivo.upper()
        if self.motivo not in MOTIVOS_VALIDOS:
            raise ValueError(
                "motivo debe ser SIN_STOCK, FUERA_DE_ZONA, SATURADO u OTRO"
            )
        if self.peso_balon_kg not in PESOS_BALON_VALIDOS:
            raise ValueError("peso_balon_kg debe ser 10 o 45")
        if self.zona_texto is not None:
            self.zona_texto = self.zona_texto.strip() or None
        return self


class DemandaPerdidaOut(BaseModel):
    id: int | str
    fecha: date
    motivo: str
    zona_texto: str | None
    cantidad_balones: int
    peso_balon_kg: int
    created_at: datetime

    class Config:
        from_attributes = True


class DemandaPerdidaMotivoResumen(BaseModel):
    motivo: str
    eventos: int
    balones: int


class DemandaPerdidaResumenOut(BaseModel):
    desde: date
    hasta: date
    eventos_total: int
    balones_total: int
    balones_10kg: int
    balones_45kg: int
    por_motivo: list[DemandaPerdidaMotivoResumen]
