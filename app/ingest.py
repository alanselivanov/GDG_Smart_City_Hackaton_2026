"""Collect real named Astana places from OpenStreetMap/Overpass."""
from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
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
 nwr["name"~"Nur.?Alem|Нур.?Алем|Нұр.?Әлем",i]({BBOX});
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
    if category is None and any(word in name.casefold().replace("-", " ") for word in
                                ("nur alem", "нур алем", "нұр әлем")):
        category = "landmark"
    if category is None:
        return None
    element_type = element.get("type")
    element_id = element.get("id")
    if element_type not in {"node", "way", "relation"} or not isinstance(element_id, int):
        return None
    safe_tags = {k: str(v)[:300] for k, v in tags.items()
                 if k in {"amenity", "tourism", "leisure", "historic", "shop", "cuisine",
                          "outdoor_seating", "internet_access", "socket:access", "wheelchair",
                          "interactive", "quiet",
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


def parse_airport_reference(xml: str, node_id: int) -> dict:
    """Validate current coordinates returned by the official OSM node API."""
    try:
        root = ET.fromstring(xml)
        nodes = [item for item in root.findall("node") if item.get("id") == str(node_id)]
        if len(nodes) != 1 or nodes[0].get("visible", "true") != "true":
            raise ValueError("missing OSM node")
        lat, lon = float(nodes[0].attrib["lat"]), float(nodes[0].attrib["lon"])
    except (ET.ParseError, KeyError, TypeError, ValueError) as exc:
        raise IngestError("Airport road-access OSM node is missing or invalid") from exc
    if not (51.0 <= lat <= 51.07 and 71.42 <= lon <= 71.51):
        raise IngestError("Airport road-access OSM node moved outside the expected area")
    return {"lat": lat, "lon": lon,
            "source_url": f"https://www.openstreetmap.org/node/{node_id}"}


async def fetch_pois(config: Settings = settings) -> list[dict]:
    headers = {"User-Agent": config.overpass_user_agent, "Accept": "application/json"}
    endpoints = tuple(dict.fromkeys((config.overpass_url, *config.overpass_fallback_urls)))
    failures: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(105.0, connect=15.0), headers=headers) as client:
        for endpoint in endpoints:
            host = httpx.URL(endpoint).host or "unknown"
            for attempt in range(3):
                try:
                    response = await client.post(endpoint, data={"data": QUERY})
                    response.raise_for_status()
                    return parse_overpass(response.json())
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status in {400, 401, 403, 404, 406, 413}:
                        failures.append(f"{host}: HTTP {status}")
                        if status == 406:
                            await asyncio.sleep(30)
                        break
                    if attempt == 2:
                        failures.append(f"{host}: HTTP {status}")
                    else:
                        await asyncio.sleep(3 * (2 ** attempt) if status != 429 else 30 * (2 ** attempt))
                except (httpx.HTTPError, ValueError, IngestError) as exc:
                    if attempt == 2:
                        failures.append(f"{host}: {type(exc).__name__}")
                    else:
                        await asyncio.sleep(3 * (2 ** attempt))
    raise IngestError("Overpass request failed (" + "; ".join(failures) + "); cached POIs kept")


async def refresh_airport_reference(db: Database, config: Settings = settings) -> dict:
    node_id = config.airport_route_osm_node_id
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": config.overpass_user_agent}) as client:
            response = await client.get(config.osm_api_url.rstrip("/") + f"/api/0.6/node/{node_id}")
            response.raise_for_status()
            reference = parse_airport_reference(response.text, node_id)
    except httpx.HTTPError as exc:
        raise IngestError(f"OSM airport reference request failed: {type(exc).__name__}") from exc
    db.save_route_reference("airport", reference)
    return db.route_reference("airport")


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
    await refresh_airport_reference(db)
    count = await refresh(db)
    print(f"Imported {count} real OSM POI at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
