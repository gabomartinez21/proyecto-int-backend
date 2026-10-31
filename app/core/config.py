from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://consolidador:consolidador@localhost:5432/consolidador"
    SECRET_KEY: str = "cambia-esta-clave-en-produccion"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    JWT_ALGORITHM: str = "HS256"


settings = Settings()
