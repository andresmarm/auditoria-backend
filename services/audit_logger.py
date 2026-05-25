from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID
from typing import Optional
import json

def log_accion(
    db: Session,
    usuario_id: UUID,
    accion: str,
    entidad_afectada: str,
    registro_id: Optional[UUID] = None,
    detalle: Optional[dict] = None
):
    """
    Registra una acción en el audit_log.
    Inmutable: solo INSERT, nunca UPDATE ni DELETE.
    """
    try:
        db.execute(text("""
            INSERT INTO audit_log (usuario_id, accion, entidad_afectada, registro_id, detalle)
            VALUES (:usuario_id, :accion, :entidad, :registro_id, :detalle)
        """), {
            "usuario_id": str(usuario_id),
            "accion": accion,
            "entidad": entidad_afectada,
            "registro_id": str(registro_id) if registro_id else None,
            "detalle": json.dumps(detalle) if detalle else None
        })
        db.commit()
    except Exception:
        pass  # El log nunca debe interrumpir el flujo principal
