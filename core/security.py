from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from core.config import settings
from core.database import get_db
from models.usuario import Usuario
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends

http_bearer = HTTPBearer()

def oauth2_scheme(credentials: HTTPAuthorizationCredentials = Depends(http_bearer)):
    return credentials.credentials



def crear_token(data: dict) -> str:
    payload = data.copy()
    expira = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload.update({"exp": expira})
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Usuario:
    credenciales_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credenciales_exception
    except JWTError:
        raise credenciales_exception

    usuario = db.query(Usuario).filter(Usuario.id == user_id).first()
    if usuario is None or not usuario.activo:
        raise credenciales_exception
    return usuario

def require_rol(*roles: str):
    """Dependencia para restringir endpoint por rol."""
    def verificar(current: Usuario = Depends(get_current_user)):
        if current.rol not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere rol: {', '.join(roles)}"
            )
        return current
    return verificar
