from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://reimbursement:development@127.0.0.1:15432/reimbursement_v2"
    checkpoint_url: str = (
        "postgresql://reimbursement:development@127.0.0.1:15432/reimbursement_v2"
        "?options=-csearch_path%3Dagent_runtime"
    )
    file_root: Path = Path("../data/v2/files")
    model_mode: Literal["fixture", "disabled", "provider"] = "fixture"
    model_provider: str = "deepseek"
    model_name: str = "deepseek-flash"
    model_base_url: str = "https://api.deepseek.com"
    model_api_key: SecretStr = SecretStr("")
    model_timeout_seconds: int = Field(default=45, ge=1, le=120)
    model_max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    model_image_budget_bytes: int = 16_000_000
    scheduling_enabled: bool = False
    cookie_secure: bool = False
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:18880",
        "http://127.0.0.1:18880",
    ]


@lru_cache
def settings() -> Settings:
    return Settings()
