from pydantic import BaseModel, EmailStr
from uuid import UUID
from typing import Optional

class RegisterSchema(BaseModel):
    email: EmailStr
    password: str
    nombre_completo: str
    cargo: Optional[str] = None
    dependencia: Optional[str] = None
    entidad_id: Optional[UUID] = None
    rol: str = "auditor"

class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UsuarioOut(BaseModel):
    id: UUID
    nombre_completo: Optional[str]
    cargo: Optional[str]
    rol: str
    activo: bool

    class Config:
        from_attributes = True
