from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path(os.getenv("DATABASE_PATH", "./data/astana.sqlite3"))
    overpass_url: str = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
    overpass_user_agent: str = os.getenv("OVERPASS_USER_AGENT", "AstanaWalksHackathon/1.0 (contact: unset)")
    poi_refresh_hours: int = int(os.getenv("POI_REFRESH_HOURS", "24"))
    auto_refresh: bool = _bool("AUTO_REFRESH", True)
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))


settings = Settings()
