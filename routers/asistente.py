"""
ROUTER — Asistente IA
=====================
Endpoints:
  POST /api/v1/asistente/consulta          → respuesta completa (JSON)
  POST /api/v1/asistente/consulta/stream   → streaming (SSE)
  GET  /api/v1/asistente/historial/{id}    → historial de una sesión
  DELETE /api/v1/asistente/historial/{id}  → limpiar historial
"""

import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.rag_engine import consultar_claude_sync, consultar_claude_streaming

router = APIRouter()

# Historial en memoria (por sesión)
# En producción puedes persistirlo en la tabla `conversaciones` de Supabase
_historial_sesiones: dict[str, list[dict]] = {}
MAX_HISTORIAL = 10  # mensajes máximos por sesión (5 turnos)


# ── Schemas ───────────────────────────────────────────────

class ConsultaRequest(BaseModel):
    pregunta: str
    sesion_id: str | None = None  # None → nueva sesión

class ConsultaResponse(BaseModel):
    respuesta: str
    sesion_id: str
    fuentes: list[str]
    chunks_usados: int


# ── Helpers ───────────────────────────────────────────────

def _obtener_historial(sesion_id: str) -> list[dict]:
    """Devuelve el historial de la sesión (máx MAX_HISTORIAL mensajes)."""
    historial = _historial_sesiones.get(sesion_id, [])
    # Mantener solo los últimos N mensajes para no exceder el context window
    return historial[-MAX_HISTORIAL:]


def _agregar_al_historial(sesion_id: str, role: str, content: str):
    """Agrega un mensaje al historial de la sesión."""
    if sesion_id not in _historial_sesiones:
        _historial_sesiones[sesion_id] = []
    _historial_sesiones[sesion_id].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


# ── Endpoints ─────────────────────────────────────────────

@router.post("/consulta", response_model=ConsultaResponse)
async def consulta_sincrona(body: ConsultaRequest):
    """
    Respuesta completa en un solo JSON.
    Ideal para clientes que no soporten SSE.
    """
    sesion_id = body.sesion_id or str(uuid.uuid4())

    if not body.pregunta.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")

    historial = _obtener_historial(sesion_id)

    try:
        resultado = consultar_claude_sync(body.pregunta, historial)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error del motor IA: {str(e)}")

    # Guardar en historial
    _agregar_al_historial(sesion_id, "user", body.pregunta)
    _agregar_al_historial(sesion_id, "assistant", resultado["respuesta"])

    return ConsultaResponse(
        respuesta=resultado["respuesta"],
        sesion_id=sesion_id,
        fuentes=resultado["fuentes"],
        chunks_usados=resultado["chunks_usados"]
    )


@router.post("/consulta/stream")
async def consulta_streaming(body: ConsultaRequest):
    """
    Respuesta en streaming usando Server-Sent Events (SSE).
    El frontend recibe los tokens a medida que Claude los genera.
    
    Formato SSE:
      data: {"tipo": "token", "contenido": "..."}
      data: {"tipo": "fin", "sesion_id": "...", "fuentes": [...]}
      data: {"tipo": "error", "detalle": "..."}
    """
    sesion_id = body.sesion_id or str(uuid.uuid4())

    if not body.pregunta.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")

    historial = _obtener_historial(sesion_id)
    respuesta_completa = []

    async def generador_sse():
        nonlocal respuesta_completa

        # Evento inicial con el sesion_id
        yield f"data: {json.dumps({'tipo': 'inicio', 'sesion_id': sesion_id})}\n\n"

        try:
            async for token in consultar_claude_streaming(body.pregunta, historial):
                respuesta_completa.append(token)
                payload = json.dumps({"tipo": "token", "contenido": token})
                yield f"data: {payload}\n\n"

            # Evento de cierre con metadatos
            texto_final = "".join(respuesta_completa)
            _agregar_al_historial(sesion_id, "user", body.pregunta)
            _agregar_al_historial(sesion_id, "assistant", texto_final)

            yield f"data: {json.dumps({'tipo': 'fin', 'sesion_id': sesion_id})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'tipo': 'error', 'detalle': str(e)})}\n\n"

    return StreamingResponse(
        generador_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Desactiva buffer en Nginx/Railway
        }
    )


@router.get("/historial/{sesion_id}")
async def obtener_historial(sesion_id: str):
    """Devuelve el historial de conversación de una sesión."""
    historial = _historial_sesiones.get(sesion_id, [])
    return {
        "sesion_id": sesion_id,
        "mensajes": historial,
        "total": len(historial)
    }


@router.delete("/historial/{sesion_id}")
async def limpiar_historial(sesion_id: str):
    """Reinicia la conversación de una sesión."""
    _historial_sesiones.pop(sesion_id, None)
    return {"mensaje": "Historial eliminado", "sesion_id": sesion_id}
