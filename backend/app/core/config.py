import logging

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application settings, loaded from environment variables and .env file.

    Required env vars for production (set as Fly.io secrets):
        GEMINI_API_KEY      - Google Gemini API key (read directly by pydantic-ai)
        GITHUB_TOKEN        - GitHub PAT for profile ingestion
        JWT_SECRET          - Secret key for JWT signing (must change from default)
        ENCRYPTION_KEY      - Explicit key material for encrypted user secrets
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

    # LLM API Keys
    # PydanticAI's GoogleProvider requires GOOGLE_API_KEY; we bridge from GEMINI_API_KEY
    gemini_api_key: str = ""
    google_api_key: str = ""

    # LLM provider (pydantic-ai format). GOOGLE_API_KEY env var is read by pydantic-ai directly.
    default_llm_model: str = "google-gla:gemini-2.5-flash"

    # Auth
    neon_auth_jwks_url: str = ""
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_secret_previous: str = ""  # Previous JWT secret for zero-downtime rotation
    service_jwt_secret: str = (
        "dev-service-secret-change-in-production"  # Shared secret between BFF and backend
    )
    internal_api_secret: str = "dev-internal-secret-change-in-production"  # Secret for internal BFF→backend calls (e.g. /auth/sync)
    trusted_service_secret: str = (
        "dev-trusted-service-secret-change-in-production"  # Secret for trusted service→backend reads
    )
    github_device_client_id: str = ""  # GitHub OAuth App client ID for CLI/MCP device auth
    encryption_key: str = ""

    # Environment (development | staging | production)
    environment: str = "development"

    # Langfuse observability
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://us.cloud.langfuse.com"

    # Production settings
    frontend_url: str = "http://localhost:3000"  # Primary frontend URL for redirects
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"  # comma-separated origins
    debug: bool = True
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # Admin
    # Explicit dev/test admin path: comma-separated GitHub usernames trusted
    # from server-side auth claims. UserSettings.is_admin is not authoritative.
    admin_usernames: str = "alliecatowo"

    # Promo mini (anonymous chat allowed)
    promo_mini_username: str = "alliecatowo"

    # WebAuthn (passkey support -- future use)
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Minis"

    # ── Cost & rate-limit guards (ALLIE-405) ─────────────────────────────────
    # LLM kill switch: set to "true" or "1" to block all LLM calls immediately.
    disable_llm_calls: str = ""

    # Pipeline token caps: cumulative tokens allowed per mini creation run
    # Default 2_000_000 covers 5 RepoAgents + chief synthesizer comfortably.
    max_pipeline_tokens_per_mini: int = 2_000_000
    # Per-explorer soft cap: if a single explorer exceeds this, it is failed
    # but the pipeline continues with remaining explorers.
    max_agent_tokens: int = 500_000

    # Per-IP + per-mini chat throttle (in-memory sliding window)
    # 20 requests per hour is the default hourly window.
    chat_ip_mini_hourly_limit: int = 20
    # Burst cap: 5 requests per minute to prevent rapid-fire abuse.
    chat_ip_mini_burst_limit: int = 5

    # Per-IP mini creation throttle (ALLIE-416)
    # 2 per hour is conservative — creation is expensive (runs the full pipeline).
    mini_create_ip_hourly_limit: int = 2

    # Per-IP SSE progress connection rate (ALLIE-416)
    # 10 new connections per minute covers normal polling; blocks flood attacks.
    mini_sse_ip_per_min_limit: int = 10

    @property
    def llm_disabled(self) -> bool:
        """Return True when LLM kill switch is active."""
        return self.disable_llm_calls.strip().lower() in ("true", "1", "yes")


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

# Bridge GEMINI_API_KEY to GOOGLE_API_KEY for PydanticAI's GoogleProvider
if settings.gemini_api_key and not settings.google_api_key:
    import os

    os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
    settings.google_api_key = settings.gemini_api_key
elif settings.google_api_key and not settings.gemini_api_key:
    # Also bridge the other way just in case
    settings.gemini_api_key = settings.google_api_key

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Warn about missing config in production
if not settings.is_development and not settings.github_token:
    logger.warning("GITHUB_TOKEN is not set — GitHub ingestion will fail")
