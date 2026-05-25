from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import date
from typing import List
from core.database import get_db
from core.security import get_current_user, require_rol
from models.usuario import Usuario
from models.norma import Norma, ChunkNorma
from schemas.norma import NormaCreate, NormaOut
from services.pipeline_ingesta import PipelineIngesta

router = APIRouter()
pipeline = PipelineIngesta()

@router.post("", response_model=NormaOut)
async def cargar_norma(
    data: NormaCreate = Depends(),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_rol("admin"))
):
    """Cargar nueva norma al sistema. Solo admin."""
    # Verificar que no exista
    existente = db.query(Norma).filter(Norma.codigo == data.codigo).first()
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe una norma con ese código")

    # Guardar metadatos
    norma = Norma(
        codigo=data.codigo,
        nombre=data.nombre,
        tipo=data.tipo,
        entidad_emisora=data.entidad_emisora,
        fecha_expedicion=data.fecha_expedicion,
        fecha_vigencia=data.fecha_vigencia,
        url_fuente=data.url_fuente,
        vigente=True
    )
    db.add(norma)
    db.commit()
    db.refresh(norma)

    # Procesar y vectorizar en background
    contenido = await archivo.read()
    try:
        chunks_creados = pipeline.procesar_norma(db, norma.id, contenido, archivo.filename)
    except Exception as e:
        # La norma queda guardada aunque falle el procesamiento
        pass

    return norma

@router.put("/{norma_id}/derogar")
def derogar_norma(
    norma_id: UUID,
    fecha_derogacion: date,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_rol("admin"))
):
    """Marcar una norma como derogada. Solo admin."""
    norma = db.query(Norma).filter(Norma.id == norma_id).first()
    if not norma:
        raise HTTPException(status_code=404, detail="Norma no encontrada")

    norma.fecha_derogacion = fecha_derogacion
    norma.vigente = False

    # Marcar todos sus chunks como no vigentes
    db.query(ChunkNorma)\
        .filter(ChunkNorma.norma_id == norma_id)\
        .update({"vigente": False})

    db.commit()
    return {"mensaje": f"Norma '{norma.nombre}' marcada como derogada desde {fecha_derogacion}"}

@router.get("", response_model=List[NormaOut])
def listar_normas(
    solo_vigentes: bool = True,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user)
):
    """Listar normas del sistema."""
    q = db.query(Norma)
    if solo_vigentes:
        q = q.filter(Norma.vigente == True)
    return q.order_by(Norma.fecha_expedicion.desc()).all()

@router.get("/{norma_id}", response_model=NormaOut)
def obtener_norma(
    norma_id: UUID,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user)
):
    norma = db.query(Norma).filter(Norma.id == norma_id).first()
    if not norma:
        raise HTTPException(status_code=404, detail="Norma no encontrada")
    return norma
