from pydantic import BaseModel, Field

class ClienteCreate(BaseModel):
    alias: str = Field(min_length=3, max_length=120, description="Ej: Las Higueras 371")
    telefono: str = Field(min_length=6, max_length=30)

class ClienteOut(BaseModel):
    id: int
    alias: str
    telefono: str
    direccion: str
    
    class Config:
        from_attributes = True
