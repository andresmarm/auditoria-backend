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
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse

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


# ── Endpoint principal ────────────────────────────────────

@router.post("/generar/stream")
async def generar_plan_stream(
    documento_proceso: UploadFile = File(...),
    matriz_riesgos:    UploadFile = File(None),
    formato_salida:    UploadFile = File(None),
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
                nombre_archivo = f"Plan_Auditoria_{documento_proceso.filename.split('.')[0]}.docx"
                fmt = "docx"

            else:
                # Word estructurado estándar
                archivo_bytes = generar_word_estandar(plan_completo, documento_proceso.filename)
                nombre_archivo = f"Plan_Auditoria_{documento_proceso.filename.split('.')[0]}.docx"
                fmt = "docx"

            # Guardar en memoria para la descarga posterior
            _archivos_temp[file_id] = {
                "bytes":  archivo_bytes,
                "nombre": nombre_archivo,
                "fmt":    fmt
            }

            yield f"data: {json.dumps({'tipo': 'archivo', 'file_id': file_id, 'formato': fmt, 'nombre': nombre_archivo})}\n\n"
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

=== PLAN DE AUDITORÍA GENERADO ===
{plan_texto[:6000]}

=== PROCEDIMIENTO ORIGINAL ===
{texto_proceso[:2000]}
"""
    if texto_matriz:
        prompt += f"\n=== MATRIZ DE RIESGOS ===\n{texto_matriz[:1500]}"

    response = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    # Limpiar posibles bloques ```json ... ```
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    plan_json = json.loads(raw)
    excel_bytes = llenar_formato_excel(plan_json, bytes_formato)
    nombre = f"Plan_Auditoria_{plan_json.get('proceso', 'auditoria')[:30].replace(' ', '_')}.xlsx"
    return excel_bytes, nombre


# ── Endpoint de descarga ──────────────────────────────────

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
        headers={"Content-Disposition": f'attachment; filename="{info["nombre"]}"'}
    )
