from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.openapi.utils import get_openapi
from routers import auth, sesiones, planes, normas

app = FastAPI(
    title="Asistente de Auditoría - API",
    description="Backend para generación de planes de auditoría con IA para COMCAJA",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,     prefix="/api/v1/auth",     tags=["Autenticación"])
app.include_router(sesiones.router, prefix="/api/v1/sesiones", tags=["Sesiones"])
app.include_router(planes.router,   prefix="/api/v1/planes",   tags=["Planes"])
app.include_router(normas.router,   prefix="/api/v1/normas",   tags=["Normas"])

@app.get("/")
def root():
    return {"mensaje": "API Asistente de Auditoría COMCAJA activa", "docs": "/docs"}

@app.get("/health")
def health():
    return {"estado": "ok"}

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    # Registrar HTTPBearer en el esquema OpenAPI
    schema["components"]["securitySchemes"] = {
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
        }
    }
    # Aplicar seguridad a todos los endpoints
    for path in schema["paths"].values():
        for method in path.values():
            method["security"] = [{"HTTPBearer": []}]
    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi
