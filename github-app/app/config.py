from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    # GitHub App credentials
    github_app_id: str = ""
    github_private_key: str = ""  # PEM contents or path to .pem file
    github_webhook_secret: str = ""

    # Minis backend
    minis_api_url: str = "http://localhost:8000"

    # LLM
    default_llm_model: str = "gemini/gemini-2.0-flash"

    # Mini username suffix (e.g., "alliecatowo" -> check for "alliecatowo" mini)
    mini_mention_suffix: str = "-mini"


settings = Settings()
