from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
import uuid

class Usuario(Base):
    __tablename__ = "usuarios"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entidad_id  = Column(UUID(as_uuid=True), ForeignKey("entidades.id"), nullable=True)
    nombre_completo = Column(String, nullable=True)
    cargo       = Column(String, nullable=True)
    dependencia = Column(String, nullable=True)
    rol         = Column(String, default="auditor")  # admin | auditor | consultor
    activo      = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    entidad  = relationship("Entidad", back_populates="usuarios")
    sesiones = relationship("SesionAuditoria", back_populates="usuario")
