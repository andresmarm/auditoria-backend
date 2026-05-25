from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
import uuid

class Entidad(Base):
    __tablename__ = "entidades"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre     = Column(String, nullable=False)
    nit        = Column(String(20), unique=True, nullable=True)
    sector     = Column(String, nullable=True)
    activa     = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    usuarios = relationship("Usuario", back_populates="entidad")
