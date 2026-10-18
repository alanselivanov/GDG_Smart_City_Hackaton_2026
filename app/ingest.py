"""Collect real named Astana places from OpenStreetMap/Overpass."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings, settings
from app.db import Database


# A fixed metropolitan bounding box avoids ambiguous translated boundary names.
BBOX = "50.98,71.20,51.32,71.68"
QUERY = f"""[out:json][timeout:90];
(
 nwr["name"]["amenity"~"^(cafe|restaurant|fast_food|bar|pub|library|theatre|cinema|arts_centre|community_centre|place_of_worship)$"]({BBOX});
 nwr["name"]["tourism"~"^(museum|attraction|viewpoint|gallery|artwork|information)$"]({BBOX});
 nwr["name"]["leisure"~"^(park|playground|garden|sports_centre|fitness_centre|bowling_alley|ice_rink)$"]({BBOX});
 nwr["leisure"="playground"]({BBOX});
 nwr["name"]["historic"]({BBOX});
 nwr["name"]["shop"~"^(mall|books)$"]({BBOX});
);
out center;"""

CATEGORY_MAP = {
    "cafe": "cafe", "restaurant": "food", "fast_food": "food", "bar": "nightlife",
    "pub": "nightlife", "library": "culture", "theatre": "culture", "cinema": "culture",
    "arts_centre": "culture", "community_centre": "culture", "place_of_worship": "landmark",
    "museum": "museum", "attraction": "landmark", "viewpoint": "viewpoint",
    "gallery": "museum", "artwork": "landmark",
    "information": "landmark", "park": "park", "playground": "family",
    "garden": "park", "sports_centre": "activity", "fitness_centre": "activity",
    "bowling_alley": "activity", "ice_rink": "activity", "mall": "shopping",
    "books": "shopping",
}


class IngestError(Exception):
    pass


def normalize_element(element: dict[str, Any]) -> dict | None:
    tags = element.get("tags") or {}
    name = (tags.get("name:ru") or tags.get("name") or tags.get("name:en") or "").strip()
    unnamed_playground = not name and tags.get("leisure") == "playground"
    if unnamed_playground:
        name = "Детская площадка"
    if not name or len(name) > 180:
        return None
    location = element.get("center") or element
    try:
        lat, lon = float(location["lat"]), float(location["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (50.98 <= lat <= 51.32 and 71.20 <= lon <= 71.68):
        return None
    category = next((CATEGORY_MAP[value] for key in ("amenity", "tourism", "leisure", "shop")
                     if (value := tags.get(key)) in CATEGORY_MAP), None)
    if category is None:
        category = "landmark" if tags.get("historic") else None
    if category is None:
        return None
    element_type = element.get("type")
    element_id = element.get("id")
    if element_type not in {"node", "way", "relation"} or not isinstance(element_id, int):
        return None
    safe_tags = {k: str(v)[:300] for k, v in tags.items()
                 if k in {"amenity", "tourism", "leisure", "historic", "shop", "cuisine",
                          "outdoor_seating", "internet_access", "socket:access", "wheelchair",
                          "addr:street", "addr:housenumber", "description", "description:ru",
                          "description:en", "description:kk", "opening_hours", "website", "phone"}}
    names = {language: tags[f"name:{language}"][:180] for language in ("ru", "en", "kk")
             if isinstance(tags.get(f"name:{language}"), str) and tags[f"name:{language}"].strip()}
    names["default"] = tags.get("name", name)[:180]
    if unnamed_playground:
        names.update({"ru": "Детская площадка", "en": "Playground", "kk": "Балалар алаңы"})
    description = tags.get("description:ru") or tags.get("description")
    if description:
        description = str(description)[:500]
    website = str(tags.get("website", ""))[:300]
    parsed_website = urlparse(website)
    if parsed_website.scheme not in {"http", "https"} or not parsed_website.netloc:
        website = ""
    return {
        "id": f"{element_type}/{element_id}", "name": name,
        "names_json": json.dumps(names, ensure_ascii=False),
        "description": description, "category": category,
        "tags_json": json.dumps(safe_tags, ensure_ascii=False),
        "lat": lat, "lon": lon,
        "opening_hours": str(tags.get("opening_hours", ""))[:200] or None,
        "website": website or None,
        "phone": str(tags.get("phone", ""))[:80] or None,
        "source_url": f"https://www.openstreetmap.org/{element_type}/{element_id}",
        "source_updated_at": element.get("timestamp"),
    }


def parse_overpass(data: dict) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise IngestError("Overpass returned an invalid response")
    if data.get("remark"):
        raise IngestError("Overpass reported an incomplete response")
    pois = [poi for item in data["elements"] if (poi := normalize_element(item))]
    if not pois:
        raise IngestError("Overpass returned no usable named Astana POI; existing data was kept")
    return pois


async def fetch_pois(config: Settings = settings) -> list[dict]:
    headers = {"User-Agent": config.overpass_user_agent, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(105.0, connect=15.0), headers=headers) as client:
        for attempt in range(3):
            try:
                response = await client.post(config.overpass_url, data={"data": QUERY})
                if response.status_code in {406, 429} and attempt < 2:
                    await asyncio.sleep(30)
                    continue
                if response.status_code in {502, 503, 504} and attempt < 2:
                    await asyncio.sleep(2 ** attempt * 3)
                    continue
                response.raise_for_status()
                return parse_overpass(response.json())
            except (httpx.HTTPError, ValueError) as exc:
                if attempt == 2:
                    raise IngestError(f"Overpass request failed: {type(exc).__name__}") from exc
                await asyncio.sleep(2 ** attempt * 3)
    raise IngestError("Overpass request failed")


async def refresh(db: Database, config: Settings = settings) -> int:
    # Fetch and validate before a single transaction: failed refreshes never erase the cache.
    pois = await fetch_pois(config)
    previous_count = db.status()["poi_count"]
    if len(pois) < 100 or (previous_count and len(pois) < previous_count / 2):
        raise IngestError("Overpass returned unexpectedly few POI; existing data was kept")
    return db.upsert_pois(pois)


async def main() -> None:
    db = Database(settings.database_path)
    db.init()
    count = await refresh(db)
    print(f"Imported {count} real OSM POI at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
