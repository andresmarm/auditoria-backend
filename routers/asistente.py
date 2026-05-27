"""
ROUTER — Asistente IA (chat conversacional)
============================================
Diferente al generador de planes: este endpoint permite al funcionario
hacer preguntas libres sobre normatividad en formato conversacional.

Endpoints:
  POST /api/v1/asistente/consulta         → respuesta completa JSON
  POST /api/v1/asistente/consulta/stream  → streaming SSE token a token
  GET  /api/v1/asistente/historial/{id}   → historial de sesión
  DELETE /api/v1/asistente/historial/{id} → limpiar sesión
"""

import json
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Usa el RAGEngine que ya existe en el proyecto
from services.rag_engine import RAGEngine

router  = APIRouter()
engine  = RAGEngine()

# Historial en memoria por sesión (máx 10 mensajes = 5 turnos)
_historial: dict[str, list[dict]] = {}
MAX_HIST = 10

SYSTEM_ASISTENTE = """Eres un asistente especializado en normatividad colombiana para el sector público.
Respondes preguntas de funcionarios con base EXCLUSIVAMENTE en los fragmentos normativos proporcionados.

REGLAS:
- Cita siempre el código de la norma y el artículo cuando estén disponibles
- Si la respuesta no está en el contexto: "Esta información no se encuentra en la normatividad cargada"
- Nunca inventes normas ni artículos
- Usa lenguaje claro para funcionarios públicos
- Si una norma tiene fecha de vigencia relevante, menciónala

Responde siempre en español."""


# ── Schemas ───────────────────────────────────────────────

class ConsultaRequest(BaseModel):
    pregunta: str
    sesion_id: str | None = None

class ConsultaResponse(BaseModel):
    respuesta: str
    sesion_id: str
    fuentes: list[str]
    chunks_usados: int


# ── Helpers ───────────────────────────────────────────────

def _get_historial(sesion_id: str) -> list[dict]:
    return _historial.get(sesion_id, [])[-MAX_HIST:]

def _add_historial(sesion_id: str, role: str, content: str):
    if sesion_id not in _historial:
        _historial[sesion_id] = []
    _historial[sesion_id].append({"role": role, "content": content})

def _extraer_fuentes(chunks: list[dict]) -> list[str]:
    fuentes, vistos = [], set()
    for c in chunks:
        key = c.get("norma_codigo") or c.get("norma_nombre") or c.get("titulo_norma", "")
        if key and key not in vistos:
            vistos.add(key)
            fuentes.append(key)
    return fuentes

def _construir_prompt(pregunta: str, chunks: list[dict]) -> str:
    """Usa el formateador del RAGEngine existente más contexto conversacional."""
    contexto = engine.formatear_chunks(chunks)
    return f"""CONTEXTO NORMATIVO:
{contexto}

---
PREGUNTA: {pregunta}

Responde basándote únicamente en el contexto normativo anterior. Cita las fuentes."""


# ── Endpoints ─────────────────────────────────────────────

@router.post("/consulta", response_model=ConsultaResponse)
async def consulta_sincrona(body: ConsultaRequest):
    """Respuesta completa en un solo JSON."""
    if not body.pregunta.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")

    sesion_id = body.sesion_id or str(uuid.uuid4())
    chunks    = engine.buscar_chunks(body.pregunta, top_k=6)
    prompt    = _construir_prompt(body.pregunta, chunks)

    historial = _get_historial(sesion_id)
    mensajes  = historial + [{"role": "user", "content": prompt}]

    try:
        response = engine.anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=SYSTEM_ASISTENTE,
            messages=mensajes
        )
        respuesta = response.content[0].text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error IA: {str(e)}")

    _add_historial(sesion_id, "user", body.pregunta)
    _add_historial(sesion_id, "assistant", respuesta)

    return ConsultaResponse(
        respuesta=respuesta,
        sesion_id=sesion_id,
        fuentes=_extraer_fuentes(chunks),
        chunks_usados=len(chunks)
    )


@router.post("/consulta/stream")
async def consulta_streaming(body: ConsultaRequest):
    """
    Streaming SSE — el frontend recibe tokens en tiempo real.

    Formato de eventos:
      data: {"tipo": "inicio",  "sesion_id": "..."}
      data: {"tipo": "token",   "contenido": "..."}
      data: {"tipo": "fuentes", "lista": [...]}
      data: {"tipo": "fin"}
      data: {"tipo": "error",   "detalle": "..."}
    """
    if not body.pregunta.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")

    sesion_id = body.sesion_id or str(uuid.uuid4())
    chunks    = engine.buscar_chunks(body.pregunta, top_k=6)
    prompt    = _construir_prompt(body.pregunta, chunks)
    historial = _get_historial(sesion_id)
    mensajes  = historial + [{"role": "user", "content": prompt}]
    fuentes   = _extraer_fuentes(chunks)

    respuesta_completa: list[str] = []

    async def sse():
        yield f"data: {json.dumps({'tipo': 'inicio', 'sesion_id': sesion_id})}\n\n"
        try:
            with engine.anthropic.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=SYSTEM_ASISTENTE,
                messages=mensajes
            ) as stream:
                for token in stream.text_stream:
                    respuesta_completa.append(token)
                    yield f"data: {json.dumps({'tipo': 'token', 'contenido': token})}\n\n"

            texto_final = "".join(respuesta_completa)
            _add_historial(sesion_id, "user", body.pregunta)
            _add_historial(sesion_id, "assistant", texto_final)

            yield f"data: {json.dumps({'tipo': 'fuentes', 'lista': fuentes})}\n\n"
            yield f"data: {json.dumps({'tipo': 'fin'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'tipo': 'error', 'detalle': str(e)})}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/historial/{sesion_id}")
async def get_historial(sesion_id: str):
    msgs = _historial.get(sesion_id, [])
    return {"sesion_id": sesion_id, "mensajes": msgs, "total": len(msgs)}


@router.delete("/historial/{sesion_id}")
async def delete_historial(sesion_id: str):
    _historial.pop(sesion_id, None)
    return {"mensaje": "Historial eliminado", "sesion_id": sesion_id}
