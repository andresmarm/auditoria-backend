import io
import re
from typing import Optional
from openai import OpenAI
from sqlalchemy.orm import Session
from core.config import settings
from models.norma import ChunkNorma

class PipelineIngesta:
    """
    Procesa documentos normativos: extrae texto, divide en chunks por artículo
    y vectoriza para almacenar en pgvector.
    """

    def __init__(self):
        self.openai = OpenAI(api_key=settings.openai_api_key)

    def extraer_texto_pdf(self, contenido: bytes) -> str:
        """Extrae texto de un PDF."""
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(contenido))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            raise ValueError(f"Error extrayendo texto del PDF: {str(e)}")

    def extraer_texto_docx(self, contenido: bytes) -> str:
        """Extrae texto de un DOCX."""
        try:
            from docx import Document
            doc = Document(io.BytesIO(contenido))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            raise ValueError(f"Error extrayendo texto del DOCX: {str(e)}")

    def dividir_en_chunks(self, texto: str) -> list[dict]:
        """
        Divide el texto normativo en chunks por artículo/sección.
        Detecta patrones como 'Artículo 1.', 'ARTÍCULO 2°', 'Art. 3.'
        """
        patron = r'(Art[íi]culo\s+\d+[°º]?\.?|ARTÍCULO\s+\d+[°º]?\.?|Art\.\s*\d+\.?)'
        partes = re.split(patron, texto, flags=re.IGNORECASE)

        chunks = []
        i = 0

        # Texto antes del primer artículo (preámbulo)
        if partes and not re.match(patron, partes[0], re.IGNORECASE):
            preambulo = partes[0].strip()
            if len(preambulo) > 50:
                chunks.append({
                    "articulo": "Preámbulo",
                    "titulo": "Preámbulo / Considerandos",
                    "contenido": preambulo[:2000]
                })
            i = 1

        # Artículos
        while i < len(partes) - 1:
            if re.match(patron, partes[i], re.IGNORECASE):
                articulo_num = partes[i].strip()
                contenido = partes[i + 1].strip() if i + 1 < len(partes) else ""

                # Extraer título si existe (primera línea)
                lineas = contenido.split("\n", 2)
                titulo = lineas[0].strip() if lineas else ""
                cuerpo = "\n".join(lineas[1:]).strip() if len(lineas) > 1 else contenido

                chunk_texto = f"{articulo_num}\n{contenido}"

                if len(chunk_texto) > 50:
                    chunks.append({
                        "articulo": articulo_num,
                        "titulo": titulo[:200] if titulo else articulo_num,
                        "contenido": chunk_texto[:3000]  # Límite por chunk
                    })
                i += 2
            else:
                i += 1

        # Si no se detectaron artículos, dividir por párrafos
        if not chunks:
            parrafos = [p.strip() for p in texto.split("\n\n") if len(p.strip()) > 100]
            for idx, parrafo in enumerate(parrafos[:50]):
                chunks.append({
                    "articulo": f"Sección {idx + 1}",
                    "titulo": parrafo[:100],
                    "contenido": parrafo[:3000]
                })

        return chunks

    def vectorizar(self, texto: str) -> list[float]:
        """Genera embedding para un texto."""
        response = self.openai.embeddings.create(
            input=texto[:8000],
            model="text-embedding-3-small"
        )
        return response.data[0].embedding

    def procesar_norma(
        self,
        db: Session,
        norma_id,
        contenido: bytes,
        nombre_archivo: str
    ) -> int:
        """
        Pipeline completo: extrae → divide → vectoriza → guarda.
        Retorna el número de chunks creados.
        """
        # 1. Extraer texto según formato
        extension = nombre_archivo.lower().split(".")[-1]
        if extension == "pdf":
            texto = self.extraer_texto_pdf(contenido)
        elif extension in ["docx", "doc"]:
            texto = self.extraer_texto_docx(contenido)
        else:
            texto = contenido.decode("utf-8", errors="ignore")

        # 2. Dividir en chunks por artículo
        chunks_data = self.dividir_en_chunks(texto)

        # 3. Vectorizar y guardar cada chunk
        chunks_guardados = 0
        for chunk_data in chunks_data:
            try:
                embedding = self.vectorizar(chunk_data["contenido"])
                tokens_aprox = len(chunk_data["contenido"].split())

                chunk = ChunkNorma(
                    norma_id=norma_id,
                    articulo=chunk_data["articulo"],
                    titulo=chunk_data["titulo"],
                    contenido=chunk_data["contenido"],
                    embedding=embedding,
                    tokens=tokens_aprox,
                    vigente=True
                )
                db.add(chunk)
                chunks_guardados += 1
            except Exception:
                continue  # Saltar chunks con error

        db.commit()
        return chunks_guardados
