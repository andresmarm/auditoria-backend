from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from uuid import UUID
from typing import List
from core.database import get_db, supabase
from core.security import get_current_user, require_rol
from models.usuario import Usuario
from models.sesion import SesionAuditoria
from models.documento import Documento
from models.plan import PlanAuditoria
from schemas.sesion import PlanGuardar, PlanOut
from services.rag_engine import RAGEngine
from services.generador_docx import generar_docx
from services.audit_logger import log_accion

router = APIRouter()
rag = RAGEngine()

@router.post("/generar/{sesion_id}")
async def generar_plan(
    sesion_id: UUID,
    db: Session = Depends(get_db),
    current: Usuario = Depends(require_rol("admin", "auditor"))
):
    """
    ⭐ Endpoint principal: genera el plan de auditoría en streaming.
    Combina documentos del funcionario + normatividad del RAG + Claude API.
    """
    # 1. Verificar sesión
    sesion = db.query(SesionAuditoria).filter(
        SesionAuditoria.id == sesion_id,
        SesionAuditoria.usuario_id == current.id
    ).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    # 2. Obtener documentos subidos
    docs = db.query(Documento).filter(
        Documento.sesion_id == sesion_id,
        Documento.estado == "listo"
    ).all()

    docs_dict = {d.tipo: d for d in docs}
    if "proceso" not in docs_dict:
        raise HTTPException(status_code=400, detail="Debe subir el documento del proceso primero")

    texto_proceso  = docs_dict["proceso"].texto_extraido
    texto_matriz   = docs_dict.get("matriz_riesgos", None)
    texto_formato  = docs_dict.get("formato_plan", None)

    texto_matriz  = texto_matriz.texto_extraido  if texto_matriz  else None
    texto_formato = texto_formato.texto_extraido if texto_formato else None

    # 3. Actualizar estado
    sesion.estado = "procesando"
    db.commit()

    # 4. Generar en streaming
    async def stream_plan():
        try:
            async for chunk in rag.generar_plan_stream(
                texto_proceso=texto_proceso,
                texto_matriz=texto_matriz,
                texto_formato=texto_formato,
                nombre_proceso=sesion.nombre_proceso
            ):
                yield f"data: {chunk}\n\n"

            sesion.estado = "completada"
            sesion.completada_at = func.now()
            db.commit()
            log_accion(db, current.id, "generar_plan", "sesiones_auditoria", sesion_id)

        except Exception as e:
            sesion.estado = "error"
            db.commit()
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(stream_plan(), media_type="text/event-stream")

@router.post("/guardar", response_model=PlanOut)
def guardar_plan(
    data: PlanGuardar,
    db: Session = Depends(get_db),
    current: Usuario = Depends(require_rol("admin", "auditor"))
):
    """Guardar el plan generado y crear el archivo DOCX."""
    # Verificar que no exista ya un plan para esta sesión
    existente = db.query(PlanAuditoria).filter(
        PlanAuditoria.sesion_id == data.sesion_id
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe un plan para esta sesión")

    plan = PlanAuditoria(
        sesion_id=data.sesion_id,
        contenido_texto=data.contenido_texto,
        normas_citadas=data.normas_citadas,
        chunks_usados=data.chunks_ids,
        tokens_usados=data.tokens_usados,
        modelo_ia="claude-sonnet-4-20250514"
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    # Generar DOCX
    try:
        docx_bytes = generar_docx(plan)
        path = f"planes/{plan.id}/plan_auditoria.docx"
        supabase.storage.from_("planes").upload(path, docx_bytes)
        plan.storage_docx = path
        db.commit()
    except Exception as e:
        pass  # El plan se guarda aunque falle el DOCX

    log_accion(db, current.id, "guardar_plan", "planes_auditoria", plan.id)
    return plan

@router.get("/{plan_id}/descargar")
def descargar_plan(
    plan_id: UUID,
    formato: str = "docx",
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user)
):
    """Descargar el plan en DOCX o PDF."""
    plan = db.query(PlanAuditoria).filter(PlanAuditoria.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    path = plan.storage_docx if formato == "docx" else plan.storage_pdf
    if not path:
        raise HTTPException(status_code=404, detail="Archivo no disponible aún")

    try:
        archivo = supabase.storage.from_("planes").download(path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error descargando archivo: {str(e)}")

    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if formato == "docx" else "application/pdf"
    )
    return Response(
        content=archivo,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=plan_auditoria_{plan_id}.{formato}"}
    )

@router.get("", response_model=List[PlanOut])
def listar_planes(
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user)
):
    """Historial de planes del funcionario."""
    return db.query(PlanAuditoria)\
        .join(SesionAuditoria)\
        .filter(SesionAuditoria.usuario_id == current.id)\
        .order_by(PlanAuditoria.created_at.desc())\
        .all()
