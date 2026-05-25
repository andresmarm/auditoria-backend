from sqlalchemy import Column, String, BigInteger, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
import uuid

class Documento(Base):
    __tablename__ = "documentos"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sesion_id      = Column(UUID(as_uuid=True), ForeignKey("sesiones_auditoria.id"))
    usuario_id     = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    tipo           = Column(String, nullable=False)  # proceso | matriz_riesgos | formato_plan
    nombre_archivo = Column(String, nullable=True)
    storage_path   = Column(String, nullable=True)
    mime_type      = Column(String, nullable=True)
    tamano_bytes   = Column(BigInteger, nullable=True)
    texto_extraido = Column(Text, nullable=True)
    estado         = Column(String, default="subido")  # subido | procesando | listo | error
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    sesion = relationship("SesionAuditoria", back_populates="documentos")
