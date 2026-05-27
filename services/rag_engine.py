"""
RAG ENGINE
==========
Búsqueda semántica en pgvector + prompt enriquecido + Claude con streaming.

Esquema real usado:
  normas:       id, codigo, nombre, tipo, entidad_emisora, fecha_vigencia, vigente
  chunks_normas: id, norma_id, articulo, titulo, contenido, embedding, vigente
"""

import os
from typing import AsyncGenerator
from openai import OpenAI
from anthropic import Anthropic
from supabase import create_client, Client

# ── Clientes ──────────────────────────────────────────────
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
claude_client  = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EMBEDDING_MODEL = "text-embedding-3-small"
CLAUDE_MODEL    = "claude-sonnet-4-20250514"
TOP_K           = 6
MAX_TOKENS      = 2048

# ── System prompt ─────────────────────────────────────────
SYSTEM_PROMPT = """Eres un asistente especializado en normatividad colombiana para el sector público.
Respondes preguntas de funcionarios públicos con base EXCLUSIVAMENTE en los fragmentos normativos
que se te proporcionan como contexto.

REGLAS:
- Cita siempre la fuente: código de la norma, nombre y artículo cuando estén disponibles
- Si la respuesta no está en el contexto, dilo claramente: "Esta información no se encuentra
  en la normatividad cargada en el sistema"
- Nunca inventes normas, artículos ni fechas
- Usa lenguaje claro y accesible para funcionarios públicos
- Si una norma tiene fecha de vigencia próxima a vencer o ya venció, adviértelo
- Organiza la respuesta con secciones claras cuando haya múltiples aspectos

Responde siempre en español."""


# ── Paso 1: Vectorizar la pregunta ────────────────────────

def vectorizar_consulta(pregunta: str) -> list[float]:
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=pregunta
    )
    return response.data[0].embedding


# ── Paso 2: Buscar chunks en pgvector ────────────────────

def buscar_chunks_relevantes(vector: list[float], top_k: int = TOP_K) -> list[dict]:
    resultado = supabase.rpc(
        "buscar_normas",
        {"query_embedding": vector, "match_count": top_k}
    ).execute()
    return resultado.data or []


# ── Paso 3: Construir prompt con contexto ─────────────────

def construir_prompt(pregunta: str, chunks: list[dict]) -> str:
    if not chunks:
        contexto = "No se encontraron fragmentos normativos relacionados con esta consulta."
    else:
        partes = []
        for i, chunk in enumerate(chunks, 1):
            # Encabezado con toda la info disponible de la norma
            codigo   = chunk.get("codigo_norma") or ""
            nombre   = chunk.get("titulo_norma") or "Norma desconocida"
            tipo     = chunk.get("tipo_norma") or ""
            entidad  = chunk.get("entidad_emisora") or ""
            vigencia = chunk.get("fecha_vigencia") or ""
            articulo = chunk.get("articulo") or ""
            similitud = chunk.get("similitud", 0)

            encabezado_partes = [f"Fragmento {i}"]
            if codigo:
                encabezado_partes.append(codigo)
            encabezado_partes.append(nombre)
            if tipo:
                encabezado_partes.append(tipo)
            if entidad:
                encabezado_partes.append(f"Emisor: {entidad}")
            if vigencia:
                encabezado_partes.append(f"Vigente desde: {vigencia}")
            if articulo:
                encabezado_partes.append(articulo)
            encabezado_partes.append(f"Relevancia: {similitud:.0%}")

            encabezado = " | ".join(encabezado_partes)
            partes.append(f"[{encabezado}]\n{chunk.get('contenido', '')}\n")

        contexto = "\n---\n".join(partes)

    return f"""CONTEXTO NORMATIVO RECUPERADO DEL SISTEMA:
{contexto}

---

PREGUNTA DEL FUNCIONARIO:
{pregunta}

INSTRUCCIÓN: Responde basándote únicamente en el contexto normativo anterior.
Cita los fragmentos relevantes indicando su fuente (código y artículo cuando estén disponibles)."""


# ── Paso 4: Claude con streaming ─────────────────────────

async def consultar_claude_streaming(
    pregunta: str,
    historial: list[dict] | None = None
) -> AsyncGenerator[str, None]:
    """Yields tokens en tiempo real para SSE."""
    vector = vectorizar_consulta(pregunta)
    chunks = buscar_chunks_relevantes(vector)
    prompt = construir_prompt(pregunta, chunks)

    mensajes = (historial or []) + [{"role": "user", "content": prompt}]

    with claude_client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=mensajes
    ) as stream:
        for text in stream.text_stream:
            yield text

    # Emitir fuentes al final
    if chunks:
        fuentes = []
        vistos = set()
        for c in chunks:
            key = c.get("codigo_norma") or c.get("titulo_norma", "")
            if key and key not in vistos:
                vistos.add(key)
                fuentes.append(key)
        if fuentes:
            yield f"\n\n---\n**Fuentes consultadas:** {', '.join(fuentes)}"


# ── Versión síncrona (testing / endpoints simples) ────────

def consultar_claude_sync(
    pregunta: str,
    historial: list[dict] | None = None
) -> dict:
    vector = vectorizar_consulta(pregunta)
    chunks = buscar_chunks_relevantes(vector)
    prompt = construir_prompt(pregunta, chunks)

    mensajes = (historial or []) + [{"role": "user", "content": prompt}]

    response = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=mensajes
    )

    fuentes = []
    vistos = set()
    for c in chunks:
        key = c.get("codigo_norma") or c.get("titulo_norma", "")
        if key and key not in vistos:
            vistos.add(key)
            fuentes.append(key)

    return {
        "respuesta": response.content[0].text,
        "fuentes": fuentes,
        "chunks_usados": len(chunks),
        "tokens_entrada": response.usage.input_tokens,
        "tokens_salida": response.usage.output_tokens
    }
