from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Postgres (raw pieces, match .env / docker-compose var names) ---
    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # --- API keys ---
    groq_api_key: str
    tavily_api_key: str
    openai_api_key: str | None = None

    # --- Derived, not read from .env directly ---
    database_url: str = ""

    @model_validator(mode="after")
    def assemble_database_url(self) -> "Settings":
        self.database_url = (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        return self


settings = Settings()