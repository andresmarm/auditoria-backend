from hmac import compare_digest
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from core.config import settings
from core.database import create_supabase_auth_client, get_db, supabase_admin
from core.security import crear_token, get_current_user, require_rol
from models.usuario import Usuario
from schemas.auth import (
    BootstrapAdminSchema, LoginSchema, PasswordResetSchema, RegisterSchema,
    RolUsuario, TokenSchema, UsuarioEstadoSchema, UsuarioOut, UsuarioUpdateSchema,
)

router = APIRouter()

def _email_por_usuario() -> dict[str, str]:
    try:
        usuarios_auth = supabase_admin.auth.admin.list_users(per_page=1000)
        return {str(user.id): user.email for user in usuarios_auth if user.email}
    except Exception:
        return {}


def _email_de_usuario(usuario_id: UUID) -> str | None:
    try:
        respuesta = supabase_admin.auth.admin.get_user_by_id(str(usuario_id))
        return respuesta.user.email
    except Exception:
        return None


def _usuario_out(usuario: Usuario, email: str | None = None) -> dict:
    return {
        "id": usuario.id, "email": email,
        "nombre_completo": usuario.nombre_completo, "cargo": usuario.cargo,
        "dependencia": usuario.dependencia, "entidad_id": usuario.entidad_id,
        "rol": usuario.rol, "activo": usuario.activo, "created_at": usuario.created_at,
    }


def _crear_usuario(data: RegisterSchema, db: Session) -> dict:
    auth_user_id = None
    try:
        auth_user = supabase_admin.auth.admin.create_user({
            "email": str(data.email), "password": data.password, "email_confirm": True
        })
        auth_user_id = auth_user.user.id
        usuario = Usuario(
            id=auth_user_id, entidad_id=data.entidad_id,
            nombre_completo=data.nombre_completo, cargo=data.cargo,
            dependencia=data.dependencia, rol=data.rol.value,
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
        return _usuario_out(usuario, str(data.email))
    except Exception as exc:
        db.rollback()
        if auth_user_id is not None:
            try:
                supabase_admin.auth.admin.delete_user(str(auth_user_id))
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=f"Error creando usuario: {str(exc)}")


def _obtener_usuario(usuario_id: UUID, db: Session) -> Usuario:
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario


def _cantidad_admins_activos(db: Session) -> int:
    return db.query(Usuario).filter(
        Usuario.rol == RolUsuario.admin.value, Usuario.activo.is_(True)
    ).count()


@router.post("/register", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def register(
    data: RegisterSchema,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_rol(RolUsuario.admin.value))
):
    return _crear_usuario(data, db)


@router.post("/bootstrap-admin", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def bootstrap_admin(
    data: BootstrapAdminSchema,
    x_bootstrap_token: str = Header(...),
    db: Session = Depends(get_db),
):
    if not settings.bootstrap_admin_token or not compare_digest(
        x_bootstrap_token, settings.bootstrap_admin_token
    ):
        raise HTTPException(status_code=403, detail="Bootstrap no autorizado")
    if db.query(Usuario).count() > 0:
        raise HTTPException(status_code=409, detail="El sistema ya tiene usuarios")
    data.rol = RolUsuario.admin
    return _crear_usuario(data, db)

@router.post("/login", response_model=TokenSchema)
def login(data: LoginSchema):
    """Iniciar sesión y obtener JWT."""
    try:
        session = create_supabase_auth_client().auth.sign_in_with_password({
            "email": str(data.email),
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
    return _usuario_out(current, _email_de_usuario(current.id))


@router.get("/users", response_model=list[UsuarioOut])
def listar_usuarios(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_rol(RolUsuario.admin.value)),
):
    emails = _email_por_usuario()
    usuarios = db.query(Usuario).order_by(Usuario.created_at.desc()).all()
    return [_usuario_out(usuario, emails.get(str(usuario.id))) for usuario in usuarios]


@router.patch("/users/{usuario_id}", response_model=UsuarioOut)
def actualizar_usuario(
    usuario_id: UUID,
    data: UsuarioUpdateSchema,
    db: Session = Depends(get_db),
    current: Usuario = Depends(require_rol(RolUsuario.admin.value)),
):
    usuario = _obtener_usuario(usuario_id, db)
    cambios = data.model_dump(exclude_unset=True)
    nuevo_rol = cambios.get("rol")
    if nuevo_rol:
        nuevo_rol = nuevo_rol.value
        if (
            usuario.rol == RolUsuario.admin.value
            and nuevo_rol != RolUsuario.admin.value
            and _cantidad_admins_activos(db) <= 1
        ):
            raise HTTPException(status_code=409, detail="Debe existir al menos un administrador activo")
        cambios["rol"] = nuevo_rol
    if usuario.id == current.id and cambios.get("rol") not in (None, RolUsuario.admin.value):
        raise HTTPException(status_code=409, detail="No puedes retirar tu propio rol de administrador")
    for campo, valor in cambios.items():
        setattr(usuario, campo, valor)
    db.commit()
    db.refresh(usuario)
    return _usuario_out(usuario, _email_de_usuario(usuario.id))


@router.patch("/users/{usuario_id}/estado", response_model=UsuarioOut)
def cambiar_estado_usuario(
    usuario_id: UUID,
    data: UsuarioEstadoSchema,
    db: Session = Depends(get_db),
    current: Usuario = Depends(require_rol(RolUsuario.admin.value)),
):
    usuario = _obtener_usuario(usuario_id, db)
    if usuario.id == current.id and not data.activo:
        raise HTTPException(status_code=409, detail="No puedes desactivar tu propio usuario")
    if (
        usuario.rol == RolUsuario.admin.value and usuario.activo and not data.activo
        and _cantidad_admins_activos(db) <= 1
    ):
        raise HTTPException(status_code=409, detail="Debe existir al menos un administrador activo")
    usuario.activo = data.activo
    db.commit()
    db.refresh(usuario)
    return _usuario_out(usuario, _email_de_usuario(usuario.id))


@router.post("/users/{usuario_id}/reset-password")
def resetear_password(
    usuario_id: UUID,
    data: PasswordResetSchema,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_rol(RolUsuario.admin.value)),
):
    usuario = _obtener_usuario(usuario_id, db)
    try:
        respuesta = supabase_admin.auth.admin.update_user_by_id(
            str(usuario.id), {"password": data.password}
        )
        email = respuesta.user.email if respuesta and respuesta.user else None
        if not email:
            raise RuntimeError("Supabase no devolvió el correo del usuario actualizado")

        # Verificación real: el endpoint solo confirma éxito si la nueva clave autentica.
        verificacion = create_supabase_auth_client().auth.sign_in_with_password({
            "email": email,
            "password": data.password,
        })
        if not verificacion.user or str(verificacion.user.id) != str(usuario.id):
            raise RuntimeError("Supabase no confirmó la nueva contraseña")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo verificar el cambio de contraseña: {str(exc)}",
        )
    return {"mensaje": "Contraseña actualizada y verificada", "usuario_id": str(usuario.id)}
