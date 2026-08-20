from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./aegis.db"
    BUSINESS_HOURS_START: str = "09:00"
    BUSINESS_HOURS_END: str = "17:00"
    BUSINESS_HOURS_TIMEZONE: str = "UTC"
    VIOLATION_THRESHOLD: int = 3
    HITL_EXPIRY_MINUTES: int = 60
    LLM_PROVIDER: str = "mock"
    LLM_API_KEY: str = ""
    CORS_ORIGINS: str = "http://localhost:5173"
    LOG_LEVEL: str = "INFO"
    DEFAULT_POLICY_ID: str = "base_policy"
    SEED_DEMO_DATA: bool = True
    LLM_PROVIDER: str = "mock"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    model_config = {"env_file": ".env", "extra": "ignore"}

@lru_cache()
def get_settings() -> Settings:
    return Settings()
