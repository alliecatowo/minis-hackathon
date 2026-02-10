from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    database_url: str = "sqlite+aiosqlite:///./minis.db"
    github_token: str = ""
    default_llm_model: str = "gemini/gemini-2.0-flash"


settings = Settings()
