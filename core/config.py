from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_key: str
    database_url: str
    anthropic_api_key: str
    openai_api_key: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    environment: str = "development"
    # "*" mantiene compatibles frontends estáticos o abiertos como archivo local.
    # En producción se recomienda definir una lista explícita separada por comas.
    allowed_origins: str = "*"
    bootstrap_admin_token: str | None = None

    @property
    def allowed_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def cors_allow_credentials(self) -> bool:
        # Starlette no debe combinar credenciales de navegador con origen comodín.
        return "*" not in self.allowed_origins_list

    class Config:
        env_file = ".env"

settings = Settings()
