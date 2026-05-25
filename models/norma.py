from sqlalchemy import Column, String, Boolean, Integer, Text, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.schema import FetchedValue
from pgvector.sqlalchemy import Vector
from core.database import Base
import uuid

class Norma(Base):
    __tablename__ = "normas"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo           = Column(String, unique=True, nullable=False)
    nombre           = Column(String, nullable=False)
    tipo             = Column(String, nullable=True)
    entidad_emisora  = Column(String, nullable=True)
    fecha_expedicion = Column(Date, nullable=True)
    fecha_vigencia   = Column(Date, nullable=True)
    fecha_derogacion = Column(Date, nullable=True)
    vigente          = Column(Boolean, FetchedValue())  # Calculada automáticamente por la BD
    url_fuente       = Column(String, nullable=True)
    storage_path     = Column(String, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    chunks = relationship("ChunkNorma", back_populates="norma", cascade="all, delete-orphan")


class ChunkNorma(Base):
    __tablename__ = "chunks_normas"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    norma_id   = Column(UUID(as_uuid=True), ForeignKey("normas.id", ondelete="CASCADE"))
    articulo   = Column(String, nullable=True)
    titulo     = Column(String, nullable=True)
    contenido  = Column(Text, nullable=False)
    embedding  = Column(Vector(1536), nullable=True)
    tokens     = Column(Integer, nullable=True)
    vigente    = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    norma = relationship("Norma", back_populates="chunks")
