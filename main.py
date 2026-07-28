from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.openapi.utils import get_openapi
from core.config import settings
from routers import auth, sesiones, planes, normas, asistente

app = FastAPI(
    title="Asistente de Auditoría - API",
    description="Backend para generación de planes de auditoría con IA para COMCAJA",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,      prefix="/api/v1/auth",      tags=["Autenticación"])
app.include_router(sesiones.router,  prefix="/api/v1/sesiones",  tags=["Sesiones"])
app.include_router(planes.router,    prefix="/api/v1/planes",    tags=["Planes"])
app.include_router(normas.router,    prefix="/api/v1/normas",    tags=["Normas"])
app.include_router(asistente.router, prefix="/api/v1/asistente", tags=["Asistente IA"])

@app.get("/")
def root():
    return {"mensaje": "API Asistente de Auditoría COMCAJA activa", "docs": "/docs"}

@app.get("/health")
def health():
    return {"estado": "ok"}

@app.get("/debug/rutas")
def debug_rutas():
    return [{"path": r.path, "methods": list(r.methods)} for r in app.routes if hasattr(r, "methods")]

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["components"]["securitySchemes"] = {
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
        }
    }
    public_paths = {"/", "/health", "/debug/rutas", "/api/v1/auth/login", "/api/v1/auth/bootstrap-admin"}
    for route_path, path in schema["paths"].items():
        for method in path.values():
            if route_path not in public_paths:
                method["security"] = [{"HTTPBearer": []}]
    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi
