from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from core.database import create_supabase_auth_client, get_db, supabase_admin
from core.security import crear_token, get_current_user, require_rol
from models.usuario import Usuario
from schemas.auth import RegisterSchema, LoginSchema, TokenSchema, UsuarioOut

router = APIRouter()

@router.post("/register", response_model=UsuarioOut)
def register(
    data: RegisterSchema,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_rol("admin"))
):
    """Registrar nuevo funcionario. Solo admin."""
    try:
        auth_user = supabase_admin.auth.admin.create_user({
            "email": data.email,
            "password": data.password,
            "email_confirm": True
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error creando usuario: {str(e)}")

    usuario = Usuario(
        id=auth_user.user.id,
        entidad_id=data.entidad_id,
        nombre_completo=data.nombre_completo,
        cargo=data.cargo,
        dependencia=data.dependencia,
        rol=data.rol
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario

@router.post("/login", response_model=TokenSchema)
def login(data: LoginSchema):
    """Iniciar sesión y obtener JWT."""
    try:
        session = create_supabase_auth_client().auth.sign_in_with_password({
            "email": data.email,
            "password": data.password
        })
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas"
        )
    token = crear_token({"sub": str(session.user.id)})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=UsuarioOut)
def me(current: Usuario = Depends(get_current_user)):
    """Perfil del usuario autenticado."""
    return current
