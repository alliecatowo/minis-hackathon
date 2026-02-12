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
        DATABASE_URL        - PostgreSQL connection string
        NEON_DATABASE_URL   - Neon connection string (takes priority over DATABASE_URL)
    """

    model_config = {"env_file": ".env", "extra": "ignore"}

    # Database — default is local PostgreSQL; override with NEON_DATABASE_URL for Neon
    database_url: str = "postgresql+asyncpg://localhost:5432/minis"
    neon_database_url: str = ""  # Neon connection string (takes priority when set)

    @property
    def effective_database_url(self) -> str:
        """Return Neon URL if set, otherwise the default database_url."""
        return self.neon_database_url or self.database_url

    # GitHub API access for profile ingestion
    github_token: str = ""

    # LLM provider (litellm format). GEMINI_API_KEY env var is read by litellm directly.
    default_llm_model: str = "gemini/gemini-2.5-flash"

    # OAuth / Auth
    github_client_id: str = ""
    github_client_secret: str = ""
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_secret_previous: str = ""  # Previous JWT secret for zero-downtime rotation
    service_jwt_secret: str = "dev-service-secret-change-in-production"  # Shared secret between BFF and backend
    encryption_key: str = ""

    # Environment (development | staging | production)
    environment: str = "development"

    # Langfuse observability
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://us.cloud.langfuse.com"

    # Production settings
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"  # comma-separated origins
    debug: bool = True
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # Admin
    admin_usernames: str = "alliecatowo"  # comma-separated

    # Promo mini (anonymous chat allowed)
    promo_mini_username: str = "alliecatowo"

    # WebAuthn (passkey support -- future use)
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Minis"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

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
if not settings.is_development and not settings.github_token:
    logger.warning("GITHUB_TOKEN is not set — GitHub ingestion will fail")
