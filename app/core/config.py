from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/literature"
    secret_key: str = "dev-only-secret-change-me-in-production"
    access_token_expire_minutes: int = 60 * 24


settings = Settings()
