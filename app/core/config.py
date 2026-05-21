from pydantic_settings import BaseSettings


def _normalize_db_url(url: str | None) -> str | None:
    if not url:
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings(BaseSettings):
    DATABASE_URL: str | None = None

    class Config:
        env_file = ".env"

    def model_post_init(self, _ctx) -> None:
        self.DATABASE_URL = _normalize_db_url(self.DATABASE_URL)


settings = Settings()
