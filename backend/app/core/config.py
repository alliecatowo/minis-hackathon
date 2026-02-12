import logging

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application settings, loaded from environment variables and .env file.

    Required env vars for production (set as Fly.io secrets):
        GEMINI_API_KEY      - Google Gemini API key (read directly by litellm)
        GITHUB_TOKEN        - GitHub PAT for profile ingestion
        GITHUB_CLIENT_ID    - GitHub OAuth app client ID
        GITHUB_CLIENT_SECRET - GitHub OAuth app client secret
        JWT_SECRET          - Secret key for JWT signing (must change from default)
        CORS_ORIGINS        - Comma-separated allowed origins (include Vercel URL)
        DATABASE_URL        - SQLite connection string (set in fly.toml for prod)
    """

    model_config = {"env_file": ".env", "extra": "ignore"}

    # Database — dev default is local file; prod uses /data/ volume on Fly.io
    database_url: str = "sqlite+aiosqlite:///./minis.db"

    # GitHub API access for profile ingestion
    github_token: str = ""

    # LLM provider (litellm format). GEMINI_API_KEY env var is read by litellm directly.
    default_llm_model: str = "gemini/gemini-2.5-flash"

    # OAuth / Auth
    github_client_id: str = ""
    github_client_secret: str = ""
    jwt_secret: str = "dev-secret-change-in-production"

    # Production settings
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"  # comma-separated origins
    debug: bool = True
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # Admin
    admin_usernames: str = "allie"  # comma-separated

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_username_list(self) -> list[str]:
        return [u.strip().lower() for u in self.admin_usernames.split(",") if u.strip()]


settings = Settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Warn about missing config in production
if not settings.debug and not settings.github_token:
    logger.warning("GITHUB_TOKEN is not set — GitHub ingestion will fail")
