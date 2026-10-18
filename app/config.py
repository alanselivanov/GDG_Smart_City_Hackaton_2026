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
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "512"))
    routing_url: str = os.getenv("ROUTING_URL", "https://valhalla1.openstreetmap.de")
    routing_timeout_seconds: float = float(os.getenv("ROUTING_TIMEOUT_SECONDS", "20"))
    geocoder_url: str = os.getenv("GEOCODER_URL", "https://nominatim.openstreetmap.org")
    geocoder_user_agent: str = os.getenv("GEOCODER_USER_AGENT", "AstanaWalksHackathon/1.0 (Astana city recommendations)")
    geocoder_timeout_seconds: float = float(os.getenv("GEOCODER_TIMEOUT_SECONDS", "15"))
    twogis_api_key: str = os.getenv("2GIS_API_KEY", "")
    twogis_timeout_seconds: float = float(os.getenv("2GIS_TIMEOUT_SECONDS", "15"))
    # OSM node identity is stable; its coordinates are fetched with every POI refresh.
    airport_route_osm_node_id: int = int(os.getenv("AIRPORT_ROUTE_OSM_NODE_ID", "14089441237"))
    osm_api_url: str = os.getenv("OSM_API_URL", "https://api.openstreetmap.org")


settings = Settings()
