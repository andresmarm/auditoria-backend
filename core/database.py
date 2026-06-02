from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from supabase import create_client, Client
from core.config import settings

# SQLAlchemy para queries directas a PostgreSQL
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Cliente Supabase (para Auth y Storage)
supabase: Client = create_client(settings.supabase_url, settings.supabase_key)
supabase_admin: Client = create_client(settings.supabase_url, settings.supabase_service_key)

def create_supabase_auth_client() -> Client:
    """Crea un cliente aislado para evitar que el login altere supabase_admin."""
    return create_client(settings.supabase_url, settings.supabase_key)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
