import anthropic
from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, AsyncIterator
from core.config import settings
from core.database import SessionLocal

PROMPT_SISTEMA = """Eres un experto en auditoría del sector público colombiano con profundo conocimiento 
en control interno, gestión de riesgos y normatividad vigente. Tu función es generar planes de auditoría 
profesionales, detallados y alineados con el marco normativo colombiano.

INSTRUCCIONES CRÍTICAS:
1. Basa ÚNICAMENTE tu respuesta en los documentos del proceso y la normatividad proporcionada.
2. Cita siempre la norma exacta (ley, artículo, decreto) que fundamenta cada criterio de auditoría.
3. Si se proporcionó una matriz de riesgos, úsala para definir los riesgos a verificar.
4. Si se proporcionó un formato institucional, respeta su estructura exactamente.
5. Si no se proporcionó formato, usa la estructura estándar de auditoría interna colombiana.
6. Nunca inventes normatividad. Si no encuentras una norma aplicable en el contexto, indícalo.
7. El plan debe ser accionable, con actividades concretas y verificables."""

PROMPT_PLAN = """
=== NORMATIVIDAD APLICABLE (recuperada del sistema) ===
{chunks_normativos}

=== DOCUMENTO DEL PROCESO A AUDITAR ===
{texto_proceso}

{seccion_matriz}

{seccion_formato}

=== INSTRUCCIÓN ===
Genera un plan de auditoría completo para el proceso descrito. El plan debe incluir:

1. **OBJETIVO DE LA AUDITORÍA**
   - Objetivo general
   - Objetivos específicos

2. **ALCANCE**
   - Procesos y actividades a auditar
   - Dependencias involucradas
   - Período a auditar

3. **CRITERIOS DE AUDITORÍA**
   - Lista de normas aplicables con artículo exacto y texto relevante
   - Estándares técnicos aplicables

4. **RIESGOS A VERIFICAR**
   - Lista de riesgos identificados (de la matriz si fue proporcionada)
   - Nivel de riesgo y controles esperados

5. **PROGRAMA DE AUDITORÍA**
   - Tabla de actividades con: Actividad | Responsable | Técnica | Evidencia esperada | Tiempo estimado

6. **LISTA DE VERIFICACIÓN**
   - Preguntas específicas por cada actividad del proceso
   - Basadas en la normatividad citada

7. **RECURSOS Y CRONOGRAMA**
   - Equipo auditor recomendado
   - Duración estimada

Fundamenta cada sección en la normatividad proporcionada. Cita artículos específicos.
"""

class RAGEngine:
    def __init__(self):
        self.anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.openai = OpenAI(api_key=settings.openai_api_key)

    def vectorizar_texto(self, texto: str) -> list[float]:
        """Convierte texto en vector de embeddings."""
        response = self.openai.embeddings.create(
            input=texto[:8000],  # Límite de tokens
            model="text-embedding-3-small"
        )
        return response.data[0].embedding

    def buscar_chunks(self, query: str, top_k: int = 8) -> list[dict]:
        """Busca los fragmentos normativos más relevantes por similitud semántica."""
        embedding = self.vectorizar_texto(query)
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"

        db = SessionLocal()
        try:
            resultado = db.execute(text("""
                SELECT 
                    cn.id,
                    cn.articulo,
                    cn.titulo,
                    cn.contenido,
                    n.nombre AS norma_nombre,
                    n.codigo AS norma_codigo,
                    n.tipo AS norma_tipo,
                    1 - (cn.embedding <=> :embedding::vector) AS similitud
                FROM chunks_normas cn
                JOIN normas n ON cn.norma_id = n.id
                WHERE cn.vigente = true AND n.vigente = true
                ORDER BY cn.embedding <=> :embedding::vector
                LIMIT :top_k
            """), {"embedding": embedding_str, "top_k": top_k})

            return [dict(row._mapping) for row in resultado]
        finally:
            db.close()

    def formatear_chunks(self, chunks: list[dict]) -> str:
        """Formatea los chunks para incluirlos en el prompt."""
        if not chunks:
            return "No se encontraron normas específicas. Aplica el marco general de control interno colombiano."

        partes = []
        for chunk in chunks:
            partes.append(
                f"[{chunk['norma_codigo']} - {chunk['norma_nombre']}]\n"
                f"{chunk['articulo'] or ''}: {chunk['titulo'] or ''}\n"
                f"{chunk['contenido']}\n"
            )
        return "\n---\n".join(partes)

    async def generar_plan_stream(
        self,
        texto_proceso: str,
        texto_matriz: Optional[str],
        texto_formato: Optional[str],
        nombre_proceso: Optional[str]
    ) -> AsyncIterator[str]:
        """Genera el plan de auditoría en streaming usando RAG + Claude."""

        # 1. Buscar chunks normativos relevantes
        query_busqueda = f"{nombre_proceso or ''} {texto_proceso[:2000]}"
        chunks = self.buscar_chunks(query_busqueda, top_k=8)
        chunks_texto = self.formatear_chunks(chunks)

        # 2. Construir secciones opcionales
        seccion_matriz = ""
        if texto_matriz:
            seccion_matriz = f"""=== MATRIZ DE RIESGOS PROPORCIONADA ===
{texto_matriz[:3000]}
"""

        seccion_formato = ""
        if texto_formato:
            seccion_formato = f"""=== FORMATO INSTITUCIONAL DEL PLAN (respetar esta estructura) ===
{texto_formato[:2000]}
"""

        # 3. Construir prompt completo
        prompt = PROMPT_PLAN.format(
            chunks_normativos=chunks_texto,
            texto_proceso=texto_proceso[:4000],
            seccion_matriz=seccion_matriz,
            seccion_formato=seccion_formato
        )

        # 4. Llamar a Claude en streaming
        with self.anthropic.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=PROMPT_SISTEMA,
            messages=[{"role": "user", "content": prompt}]
        ) as stream:
            for text_chunk in stream.text_stream:
                yield text_chunk
