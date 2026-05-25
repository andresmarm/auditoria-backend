from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List
from datetime import datetime

class SesionCreate(BaseModel):
    nombre_proceso: str

class SesionOut(BaseModel):
    id: UUID
    nombre_proceso: Optional[str]
    tiene_matriz: bool
    tiene_formato: bool
    estado: str
    created_at: datetime

    class Config:
        from_attributes = True

class DocumentoOut(BaseModel):
    id: UUID
    tipo: str
    nombre_archivo: Optional[str]
    estado: str

    class Config:
        from_attributes = True

class PlanGuardar(BaseModel):
    sesion_id: UUID
    contenido_texto: str
    normas_citadas: Optional[List[dict]] = []
    chunks_ids: Optional[List[UUID]] = []
    tokens_usados: Optional[int] = 0

class PlanOut(BaseModel):
    id: UUID
    sesion_id: UUID
    contenido_texto: Optional[str]
    normas_citadas: Optional[List[dict]]
    storage_docx: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
