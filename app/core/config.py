from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/literature"
    secret_key: str = "dev-only-secret-change-me-in-production"
    access_token_expire_minutes: int = 60 * 24
    store_search_url: str = "https://oz.by/search/?q={query}"

    # The AI scripts share DATABASE_URL and need a plain libpq URL; SQLAlchemy needs the driver.
    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)


settings = Settings()
