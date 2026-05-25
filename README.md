# Asistente de Auditoría — Backend API

Backend FastAPI para generación automática de planes de auditoría del sector público colombiano usando IA (RAG + Claude API).

## Estructura
```
auditoria-backend/
├── main.py              # App principal
├── Dockerfile           # Para Railway/Docker
├── requirements.txt
├── .env.example         # Variables de entorno requeridas
├── core/                # Configuración y seguridad
├── models/              # Modelos SQLAlchemy (PostgreSQL)
├── schemas/             # Validación Pydantic
├── routers/             # Endpoints REST
├── services/            # Lógica de negocio
│   ├── rag_engine.py    # RAG + Claude API
│   ├── pipeline_ingesta.py  # Procesamiento de normas
│   ├── generador_docx.py    # Generación de archivos
│   └── audit_logger.py
└── prompts/             # Prompts del sistema
```

## Requisitos previos
- Proyecto en **Supabase** con las tablas creadas (ver esquema SQL)
- Extensión **pgvector** activada en Supabase
- API Key de **Anthropic** (Claude)
- API Key de **OpenAI** (embeddings)

## Configuración local

```bash
# 1. Clonar y entrar al proyecto
git clone https://github.com/tu-usuario/auditoria-backend.git
cd auditoria-backend

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales reales

# 5. Correr en desarrollo
uvicorn main:app --reload --port 8000
```

## Documentación de la API
Una vez corriendo, visita:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Deploy en Railway

1. Subir este repositorio a GitHub
2. Crear proyecto en [railway.app](https://railway.app)
3. Conectar el repositorio
4. Agregar las variables de entorno del `.env.example`
5. Railway detecta el Dockerfile automáticamente y despliega

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/v1/auth/login` | Iniciar sesión |
| POST | `/api/v1/sesiones` | Crear sesión de auditoría |
| POST | `/api/v1/sesiones/{id}/documentos` | Subir documento |
| POST | `/api/v1/planes/generar/{sesion_id}` | ⭐ Generar plan (streaming) |
| POST | `/api/v1/planes/guardar` | Guardar plan generado |
| GET  | `/api/v1/planes/{id}/descargar` | Descargar DOCX/PDF |
| POST | `/api/v1/normas` | Cargar norma al sistema (admin) |
