from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import date, datetime

class NormaCreate(BaseModel):
    codigo: str
    nombre: str
    tipo: str
    entidad_emisora: Optional[str] = None
    fecha_expedicion: Optional[date] = None
    fecha_vigencia: Optional[date] = None
    url_fuente: Optional[str] = None

class NormaOut(BaseModel):
    id: UUID
    codigo: str
    nombre: str
    tipo: Optional[str]
    vigente: bool
    fecha_expedicion: Optional[date]
    created_at: datetime

    class Config:
        from_attributes = True
