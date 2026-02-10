import logging

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    database_url: str = "sqlite+aiosqlite:///./minis.db"
    github_token: str = ""
    default_llm_model: str = "gemini/gemini-2.5-flash"

    # OAuth / Auth
    github_client_id: str = ""
    github_client_secret: str = ""
    jwt_secret: str = "dev-secret-change-in-production"

    # Production settings
    cors_origins: str = "http://localhost:3000"  # comma-separated origins
    debug: bool = True
    log_level: str = "INFO"
    port: int = 8000

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Warn about missing config in production
if not settings.debug and not settings.github_token:
    logger.warning("GITHUB_TOKEN is not set — GitHub ingestion will fail")
