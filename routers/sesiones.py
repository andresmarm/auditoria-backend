from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from uuid import UUID
from typing import List
from core.database import get_db, supabase
from core.security import get_current_user, require_rol
from models.usuario import Usuario
from models.sesion import SesionAuditoria
from models.documento import Documento
from schemas.sesion import SesionCreate, SesionOut, DocumentoOut
from services.audit_logger import log_accion
from services.extractor_texto import extraer_texto

router = APIRouter()

@router.post("", response_model=SesionOut)
def crear_sesion(
    data: SesionCreate,
    db: Session = Depends(get_db),
    current: Usuario = Depends(require_rol("admin", "auditor"))
):
    """Iniciar una nueva sesión de auditoría."""
    sesion = SesionAuditoria(
        usuario_id=current.id,
        entidad_id=current.entidad_id,
        nombre_proceso=data.nombre_proceso,
        estado="iniciada"
    )
    db.add(sesion)
    db.commit()
    db.refresh(sesion)
    log_accion(db, current.id, "crear_sesion", "sesiones_auditoria", sesion.id)
    return sesion

@router.get("", response_model=List[SesionOut])
def listar_sesiones(
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user)
):
    """Listar sesiones del funcionario autenticado."""
    return db.query(SesionAuditoria)\
        .filter(SesionAuditoria.usuario_id == current.id)\
        .order_by(SesionAuditoria.created_at.desc())\
        .all()

@router.get("/{sesion_id}", response_model=SesionOut)
def obtener_sesion(
    sesion_id: UUID,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user)
):
    sesion = db.query(SesionAuditoria).filter(
        SesionAuditoria.id == sesion_id,
        SesionAuditoria.usuario_id == current.id
    ).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return sesion

@router.post("/{sesion_id}/documentos", response_model=DocumentoOut)
async def subir_documento(
    sesion_id: UUID,
    tipo: str = Form(...),  # proceso | matriz_riesgos | formato_plan
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: Usuario = Depends(require_rol("admin", "auditor"))
):
    """Subir documento a una sesión existente."""
    if tipo not in ["proceso", "matriz_riesgos", "formato_plan"]:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido")

    sesion = db.query(SesionAuditoria).filter(
        SesionAuditoria.id == sesion_id,
        SesionAuditoria.usuario_id == current.id
    ).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    # 1. Subir archivo a Supabase Storage
    contenido = await archivo.read()
    path = f"sesiones/{sesion_id}/{tipo}/{archivo.filename}"
    try:
        supabase.storage.from_("documentos").upload(path, contenido, {"upsert": "true"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo archivo: {str(e)}")

    # 2. Extraer texto
    texto = extraer_texto(contenido, archivo.filename)

    # 3. Guardar en BD
    doc = Documento(
        sesion_id=sesion_id,
        usuario_id=current.id,
        tipo=tipo,
        nombre_archivo=archivo.filename,
        storage_path=path,
        mime_type=archivo.content_type,
        tamano_bytes=len(contenido),
        texto_extraido=texto,
        estado="listo"
    )
    db.add(doc)

    # 4. Actualizar flags de la sesión
    if tipo == "matriz_riesgos":
        sesion.tiene_matriz = True
    if tipo == "formato_plan":
        sesion.tiene_formato = True

    db.commit()
    db.refresh(doc)
    log_accion(db, current.id, "subir_documento", "documentos", doc.id, {"tipo": tipo})
    return doc
