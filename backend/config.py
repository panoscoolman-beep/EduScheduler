"""
Application configuration loaded from environment variables.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from .env file."""

    postgres_user: str = "edscheduler"
    postgres_password: str = "change_me_in_production"
    postgres_db: str = "edscheduler"
    database_url: str = "postgresql://edscheduler:change_me_in_production@db:5432/edscheduler"

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_env: str = "development"
    secret_key: str = "change_me_to_random_string"

    # Bearer token required on cross-service /api/* calls (see backend/auth.py).
    # The middleware reads it from os.environ; declared here so pydantic
    # accepts the key in .env instead of failing with extra_forbidden.
    edscheduler_api_token: str = ""

    allowed_origins: str = "http://localhost:8080,http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
