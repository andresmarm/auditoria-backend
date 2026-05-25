import io
from typing import Optional

def extraer_texto(contenido: bytes, nombre_archivo: str) -> Optional[str]:
    """
    Extrae texto plano de PDF o DOCX.
    Usado para los documentos que sube el funcionario (proceso, matriz, formato).
    """
    extension = nombre_archivo.lower().split(".")[-1] if nombre_archivo else ""

    try:
        if extension == "pdf":
            return _extraer_pdf(contenido)
        elif extension in ["docx", "doc"]:
            return _extraer_docx(contenido)
        elif extension in ["txt"]:
            return contenido.decode("utf-8", errors="ignore")
        else:
            # Intentar como texto plano
            return contenido.decode("utf-8", errors="ignore")
    except Exception as e:
        return f"[Error extrayendo texto: {str(e)}]"

def _extraer_pdf(contenido: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(contenido))
    paginas = []
    for page in reader.pages:
        texto = page.extract_text()
        if texto:
            paginas.append(texto)
    return "\n\n".join(paginas)

def _extraer_docx(contenido: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(contenido))
    parrafos = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(parrafos)
