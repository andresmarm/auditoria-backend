from datetime import datetime
from enum import Enum
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from typing import Optional

class RolUsuario(str, Enum):
    admin = "admin"
    auditor = "auditor"
    consultor = "consultor"

class RegisterSchema(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nombre_completo: str
    cargo: Optional[str] = None
    dependencia: Optional[str] = None
    entidad_id: Optional[UUID] = None
    rol: RolUsuario = RolUsuario.auditor

class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UsuarioOut(BaseModel):
    id: UUID
    email: Optional[EmailStr] = None
    nombre_completo: Optional[str]
    cargo: Optional[str]
    dependencia: Optional[str] = None
    entidad_id: Optional[UUID] = None
    rol: RolUsuario
    activo: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class UsuarioUpdateSchema(BaseModel):
    nombre_completo: Optional[str] = None
    cargo: Optional[str] = None
    dependencia: Optional[str] = None
    entidad_id: Optional[UUID] = None
    rol: Optional[RolUsuario] = None

class UsuarioEstadoSchema(BaseModel):
    activo: bool

class PasswordResetSchema(BaseModel):
    password: str = Field(min_length=8)

class BootstrapAdminSchema(RegisterSchema):
    rol: RolUsuario = RolUsuario.admin
