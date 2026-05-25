from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
import uuid

class PlanAuditoria(Base):
    __tablename__ = "planes_auditoria"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sesion_id       = Column(UUID(as_uuid=True), ForeignKey("sesiones_auditoria.id"), unique=True)
    contenido_json  = Column(JSONB, nullable=True)
    contenido_texto = Column(Text, nullable=True)
    normas_citadas  = Column(JSONB, nullable=True)
    chunks_usados   = Column(ARRAY(UUID(as_uuid=True)), nullable=True)
    storage_docx    = Column(String, nullable=True)
    storage_pdf     = Column(String, nullable=True)
    tokens_usados   = Column(Integer, nullable=True)
    modelo_ia       = Column(String, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    sesion = relationship("SesionAuditoria", back_populates="plan")
