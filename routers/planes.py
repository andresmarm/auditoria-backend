"""
ROUTER — Planes de Auditoría
=============================
POST /api/v1/planes/generar/stream

Recibe:
  - documento_proceso  (PDF/DOCX/TXT) — obligatorio
  - matriz_riesgos     (PDF/DOCX/XLSX/TXT) — opcional
  - formato_salida     (XLSX o DOCX) — opcional

Lógica de salida:
  - Sin formato      → Word estructurado estándar (.docx)
  - Formato .docx    → Word respetando la estructura del formato cargado
  - Formato .xlsx    → Excel llenando las celdas del formato cargado (JSON estructurado)

El endpoint hace streaming SSE del plan como texto mientras lo genera,
y al final emite un evento con la URL de descarga del archivo.
"""

import io
import json
import uuid
import tempfile
import os
import re
import unicodedata
from typing import Optional
from json import JSONDecodeError
from uuid import UUID

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session

from core.database import get_db, supabase_admin
from core.security import get_current_user
from models.usuario import Usuario
from models.sesion import SesionAuditoria
from models.plan import PlanAuditoria
from services.rag_engine import (
    vectorizar_consulta,
    buscar_chunks_relevantes,
    construir_prompt,
    claude_client,
    CLAUDE_MODEL,
    SYSTEM_PROMPT,
)
from services.generador_word import generar_word_estandar, generar_word_con_formato
from services.generador_excel import llenar_formato_excel, PROMPT_JSON_PLAN

router = APIRouter()
PLANES_BUCKET = os.getenv("PLANES_BUCKET", "documentos")

# Almacén temporal de archivos generados {file_id: bytes}
_archivos_temp: dict[str, dict] = {}


# ── Helpers de extracción de texto ────────────────────────

def extraer_texto(archivo: UploadFile) -> str:
    """Extrae texto de PDF, DOCX o TXT."""
    contenido = archivo.file.read()
    archivo.file.seek(0)
    nombre = (archivo.filename or "").lower()

    if nombre.endswith(".pdf"):
        return _texto_pdf(contenido)
    elif nombre.endswith(".docx") or nombre.endswith(".doc"):
        return _texto_docx(contenido)
    elif nombre.endswith((".xlsx", ".xls")):
        return _texto_xlsx(contenido)
    else:
        return contenido.decode("utf-8", errors="ignore")


def _texto_pdf(data: bytes) -> str:
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(p.get_text("text") for p in doc if p.get_text("text").strip())
    except Exception as e:
        return f"[Error extrayendo PDF: {e}]"


def _texto_docx(data: bytes) -> str:
    try:
        import mammoth
        result = mammoth.extract_raw_text(io.BytesIO(data))
        return result.value
    except Exception:
        try:
            from docx import Document
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            return f"[Error extrayendo DOCX: {e}]"


def _texto_xlsx(data: bytes) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        lineas = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                fila = "\t".join(str(c) for c in row if c is not None)
                if fila.strip():
                    lineas.append(fila)
        return "\n".join(lineas)
    except Exception as e:
        return f"[Error extrayendo XLSX: {e}]"


def _detectar_tipo_formato(filename: str) -> str:
    """Devuelve 'xlsx', 'docx' o 'ninguno'."""
    nombre = (filename or "").lower()
    if nombre.endswith(".xlsx") or nombre.endswith(".xls"):
        return "xlsx"
    if nombre.endswith(".docx") or nombre.endswith(".doc"):
        return "docx"
    return "ninguno"


def _nombre_archivo_seguro(nombre: str, extension: str) -> str:
    """Genera un filename ASCII valido para Content-Disposition."""
    base = os.path.splitext(nombre or "")[0] or "Plan_Auditoria"
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", base).strip("._-")
    base = base[:80] or "Plan_Auditoria"
    return f"{base}.{extension.lstrip('.')}"


def _media_type(fmt: str) -> str:
    return {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(fmt, "application/octet-stream")


def _fuentes_desde_chunks(chunks: list[dict]) -> list[dict]:
    fuentes, vistos = [], set()
    for chunk in chunks:
        key = chunk.get("codigo_norma") or chunk.get("titulo_norma")
        if not key or key in vistos:
            continue
        vistos.add(key)
        fuentes.append({
            "codigo": chunk.get("codigo_norma"),
            "titulo": chunk.get("titulo_norma"),
            "articulo": chunk.get("articulo"),
        })
    return fuentes


def _subir_plan_storage(path: str, contenido: bytes, fmt: str) -> None:
    supabase_admin.storage.from_(PLANES_BUCKET).upload(
        path,
        contenido,
        {"content-type": _media_type(fmt), "upsert": "true"},
    )


def _crear_registro_plan(
    db: Session,
    current: Usuario,
    nombre_proceso: str,
    plan_texto: str,
    chunks: list[dict],
    storage_path: str,
    nombre_archivo: str,
    fmt: str,
    file_id: str,
) -> PlanAuditoria:
    sesion = SesionAuditoria(
        usuario_id=current.id,
        entidad_id=current.entidad_id,
        nombre_proceso=nombre_proceso,
        estado="plan_generado",
    )
    db.add(sesion)
    db.flush()

    plan = PlanAuditoria(
        sesion_id=sesion.id,
        contenido_json={
            "file_id": file_id,
            "nombre_archivo": nombre_archivo,
            "formato": fmt,
            "bucket": PLANES_BUCKET,
        },
        contenido_texto=plan_texto,
        normas_citadas=_fuentes_desde_chunks(chunks),
        chunks_usados=[],
        storage_docx=storage_path,
        modelo_ia=CLAUDE_MODEL,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


# ── Endpoint principal ────────────────────────────────────

@router.post("/generar/stream")
async def generar_plan_stream(
    documento_proceso: UploadFile = File(...),
    matriz_riesgos:    UploadFile = File(None),
    formato_salida:    UploadFile = File(None),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """
    Genera el plan de auditoría en streaming SSE.

    Eventos SSE:
      {"tipo": "inicio",    "file_id": "uuid"}
      {"tipo": "token",     "contenido": "..."}
      {"tipo": "progreso",  "mensaje": "..."}
      {"tipo": "archivo",   "file_id": "uuid", "formato": "xlsx|docx", "nombre": "Plan_Auditoria.xlsx"}
      {"tipo": "fin"}
      {"tipo": "error",     "detalle": "..."}
    """
    # Leer archivos en memoria antes del streaming
    texto_proceso  = extraer_texto(documento_proceso)
    texto_matriz   = extraer_texto(matriz_riesgos)  if matriz_riesgos   else None
    texto_formato  = extraer_texto(formato_salida)  if formato_salida   else None
    bytes_formato  = formato_salida.file.read()     if formato_salida   else None
    tipo_formato   = _detectar_tipo_formato(formato_salida.filename if formato_salida else "")

    if not texto_proceso.strip():
        raise HTTPException(status_code=400, detail="No se pudo extraer texto del procedimiento.")

    file_id = str(uuid.uuid4())

    async def sse():
        plan_texto = []

        yield f"data: {json.dumps({'tipo': 'inicio', 'file_id': file_id})}\n\n"

        try:
            # ── FASE 1: Streaming del plan como texto ─────
            # Buscar chunks normativos relevantes
            vector = vectorizar_consulta(
                f"{documento_proceso.filename or ''} {texto_proceso[:2000]}"
            )
            chunks = buscar_chunks_relevantes(vector, top_k=8)
            prompt_rag = construir_prompt(
                f"Genera un plan de auditoría para el siguiente proceso:\n\n{texto_proceso[:4000]}",
                chunks
            )

            # Agregar contexto de matriz y formato si existen
            prompt_completo = prompt_rag
            if texto_matriz:
                prompt_completo += f"\n\n=== MATRIZ DE RIESGOS ===\n{texto_matriz[:2000]}"
            if texto_formato:
                prompt_completo += f"\n\n=== FORMATO INSTITUCIONAL (respetar esta estructura) ===\n{texto_formato[:1500]}"

            with claude_client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt_completo}]
            ) as stream:
                for token in stream.text_stream:
                    plan_texto.append(token)
                    yield f"data: {json.dumps({'tipo': 'token', 'contenido': token})}\n\n"

            plan_completo = "".join(plan_texto)

            # ── FASE 2: Generar el archivo de descarga ────
            yield f"data: {json.dumps({'tipo': 'progreso', 'mensaje': 'Generando archivo de descarga...'})}\n\n"

            if tipo_formato == "xlsx":
                # Pedir a Claude el JSON estructurado para llenar el Excel
                archivo_bytes, nombre_archivo = await _generar_xlsx(
                    plan_completo, texto_proceso, texto_matriz, bytes_formato
                )
                fmt = "xlsx"

            elif tipo_formato == "docx":
                # Word respetando la estructura del formato cargado
                archivo_bytes = generar_word_con_formato(plan_completo, bytes_formato)
                nombre_archivo = _nombre_archivo_seguro(f"Plan_Auditoria_{documento_proceso.filename}", "docx")
                fmt = "docx"

            else:
                # Word estructurado estándar
                archivo_bytes = generar_word_estandar(plan_completo, documento_proceso.filename)
                nombre_archivo = _nombre_archivo_seguro(f"Plan_Auditoria_{documento_proceso.filename}", "docx")
                fmt = "docx"

            # Guardar en memoria para la descarga posterior
            _archivos_temp[file_id] = {
                "bytes":  archivo_bytes,
                "nombre": nombre_archivo,
                "fmt":    fmt
            }

            storage_path = f"planes/{current.id}/{file_id}/{nombre_archivo}"
            _subir_plan_storage(storage_path, archivo_bytes, fmt)
            plan = _crear_registro_plan(
                db=db,
                current=current,
                nombre_proceso=documento_proceso.filename or nombre_archivo,
                plan_texto=plan_completo,
                chunks=chunks,
                storage_path=storage_path,
                nombre_archivo=nombre_archivo,
                fmt=fmt,
                file_id=file_id,
            )

            yield f"data: {json.dumps({'tipo': 'archivo', 'file_id': file_id, 'plan_id': str(plan.id), 'formato': fmt, 'nombre': nombre_archivo, 'storage_path': storage_path, 'download_url': f'/api/v1/planes/{plan.id}/descargar'})}\n\n"
            yield f"data: {json.dumps({'tipo': 'fin'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'tipo': 'error', 'detalle': str(e)})}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


async def _generar_xlsx(plan_texto: str, texto_proceso: str, texto_matriz: Optional[str], bytes_formato: bytes) -> tuple[bytes, str]:
    """Llama a Claude para obtener el JSON y llena el Excel del usuario."""
    prompt = f"""{PROMPT_JSON_PLAN}

Reglas adicionales:
- Devuelve solo un objeto JSON valido.
- No incluyas markdown.
- No incluyas saltos de linea literales dentro de strings.
- Usa textos concisos para evitar truncamiento.

=== PLAN DE AUDITORÍA GENERADO ===
{plan_texto[:6000]}

=== PROCEDIMIENTO ORIGINAL ===
{texto_proceso[:2000]}
"""
    if texto_matriz:
        prompt += f"\n=== MATRIZ DE RIESGOS ===\n{texto_matriz[:1500]}"

    response = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    plan_json = _parsear_plan_json(raw)
    if plan_json is None:
        plan_json = _reparar_plan_json(raw, plan_texto)
    if plan_json is None:
        raise ValueError("No se pudo convertir la respuesta de IA en un JSON valido para Excel.")

    excel_bytes = llenar_formato_excel(plan_json, bytes_formato)
    nombre = _nombre_archivo_seguro(f"Plan_Auditoria_{plan_json.get('proceso', 'auditoria')[:30]}", "xlsx")
    return excel_bytes, nombre


def _parsear_plan_json(raw: str) -> dict | None:
    """Extrae y parsea el primer objeto JSON de una respuesta de Claude."""
    candidato = _extraer_objeto_json(raw)
    if not candidato:
        return None
    try:
        return json.loads(candidato)
    except JSONDecodeError:
        return None


def _extraer_objeto_json(raw: str) -> str | None:
    texto = raw.strip()
    if texto.startswith("```"):
        partes = texto.split("```")
        texto = partes[1] if len(partes) > 1 else texto
        texto = texto.strip()
        if texto.startswith("json"):
            texto = texto[4:].strip()

    inicio = texto.find("{")
    if inicio == -1:
        return None

    en_string = False
    escape = False
    profundidad = 0
    for i, ch in enumerate(texto[inicio:], inicio):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            en_string = not en_string
            continue
        if en_string:
            continue
        if ch == "{":
            profundidad += 1
        elif ch == "}":
            profundidad -= 1
            if profundidad == 0:
                return texto[inicio:i + 1]
    return texto[inicio:]


def _reparar_plan_json(raw: str, plan_texto: str) -> dict | None:
    prompt = f"""Corrige la siguiente respuesta y devuelve UNICAMENTE un JSON valido.
No uses markdown. No agregues explicaciones. No incluyas saltos de linea literales dentro de strings.

Debe conservar esta estructura:
{{
  "auditoria": "",
  "fecha_inicio": "YYYY-MM-DD",
  "fecha_fin": "YYYY-MM-DD",
  "proceso": "",
  "ubicacion": "",
  "lugar": "",
  "antecedentes": "",
  "objetivo_general": "",
  "alcance": "",
  "actividades": [
    {{"proceso": "", "fecha": "YYYY-MM-DD", "hora": "HH:MM", "auditado": "", "auditor": ""}}
  ],
  "documentos_referencia": "",
  "observaciones": ""
}}

=== RESPUESTA JSON INVALIDA ===
{raw[:8000]}

=== PLAN DE REFERENCIA ===
{plan_texto[:3000]}
"""
    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception:
        return None
    return _parsear_plan_json(response.content[0].text)


# ── Endpoint de descarga ──────────────────────────────────
@router.get("")
async def listar_planes(
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Lista planes generados por el usuario autenticado."""
    planes = (
        db.query(PlanAuditoria)
        .join(SesionAuditoria, PlanAuditoria.sesion_id == SesionAuditoria.id)
        .filter(SesionAuditoria.usuario_id == current.id)
        .order_by(PlanAuditoria.created_at.desc())
        .all()
    )
    resultado = []
    for plan in planes:
        meta = plan.contenido_json or {}
        fmt = meta.get("formato") or "docx"
        nombre = meta.get("nombre_archivo") or _nombre_archivo_seguro("Plan_Auditoria", fmt)
        resultado.append({
            "id": str(plan.id),
            "sesion_id": str(plan.sesion_id),
            "nombre": nombre,
            "formato": fmt,
            "storage_path": plan.storage_docx,
            "modelo_ia": plan.modelo_ia,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "download_url": f"/api/v1/planes/{plan.id}/descargar",
        })
    return {"planes": resultado, "total": len(resultado)}


@router.get("/{plan_id}/descargar")
async def descargar_plan_persistido(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Descarga un plan persistido en Supabase Storage."""
    plan = (
        db.query(PlanAuditoria)
        .join(SesionAuditoria, PlanAuditoria.sesion_id == SesionAuditoria.id)
        .filter(PlanAuditoria.id == plan_id, SesionAuditoria.usuario_id == current.id)
        .first()
    )
    if not plan or not plan.storage_docx:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    meta = plan.contenido_json or {}
    fmt = meta.get("formato") or "docx"
    nombre = meta.get("nombre_archivo") or _nombre_archivo_seguro("Plan_Auditoria", fmt)

    try:
        contenido = supabase_admin.storage.from_(PLANES_BUCKET).download(plan.storage_docx)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error descargando plan: {str(e)}")

    return StreamingResponse(
        io.BytesIO(contenido),
        media_type=_media_type(fmt),
        headers={"Content-Disposition": f'attachment; filename="{_nombre_archivo_seguro(nombre, fmt)}"'},
    )


@router.get("/descargar/{file_id}")
async def descargar_plan(file_id: str):
    """Descarga el archivo generado por su ID temporal."""
    if file_id not in _archivos_temp:
        raise HTTPException(status_code=404, detail="Archivo no encontrado o expirado.")

    info = _archivos_temp[file_id]
    fmt  = info["fmt"]

    media_types = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    return StreamingResponse(
        io.BytesIO(info["bytes"]),
        media_type=media_types.get(fmt, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{_nombre_archivo_seguro(info["nombre"], fmt)}"'}
    )
