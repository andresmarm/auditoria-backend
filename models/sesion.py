from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
import uuid

class SesionAuditoria(Base):
    __tablename__ = "sesiones_auditoria"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id     = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    entidad_id     = Column(UUID(as_uuid=True), ForeignKey("entidades.id"))
    nombre_proceso = Column(String, nullable=True)
    tiene_matriz   = Column(Boolean, default=False)
    tiene_formato  = Column(Boolean, default=False)
    estado         = Column(String, default="iniciada")
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    completada_at  = Column(DateTime(timezone=True), nullable=True)

    usuario    = relationship("Usuario", back_populates="sesiones")
    documentos = relationship("Documento", back_populates="sesion")
    plan       = relationship("PlanAuditoria", back_populates="sesion", uselist=False)
