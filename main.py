from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, sesiones, planes, normas

app = FastAPI(
    title="Asistente de Auditoría - API",
    description="Backend para generación de planes de auditoría con IA",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cambiar a dominio del frontend en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,     prefix="/api/v1/auth",    tags=["Autenticación"])
app.include_router(sesiones.router, prefix="/api/v1/sesiones", tags=["Sesiones"])
app.include_router(planes.router,   prefix="/api/v1/planes",   tags=["Planes"])
app.include_router(normas.router,   prefix="/api/v1/normas",   tags=["Normas"])

@app.get("/")
def root():
    return {"mensaje": "API Asistente de Auditoría activa", "docs": "/docs"}

@app.get("/health")
def health():
    return {"estado": "ok"}
