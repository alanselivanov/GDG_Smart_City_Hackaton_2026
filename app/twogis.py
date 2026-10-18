"""One-page, one-request 2GIS Places search independent of the OSM dataset."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.models import TwoGisNearbyRequest, TwoGisNearbyResponse, TwoGisPoi
from app.recommend import distance_m


PLACES_URL = "https://catalog.api.2gis.com/3.0/items"
FIELDS = "items.point,items.description,items.reviews,items.schedule,items.rubrics"
# Rubric IDs observed in the Astana (region 68) 2GIS catalog.
RUBRIC_IDS = {"cafe": 162, "park": 168, "family": 112884}
# Places API accepts comma-separated types. Parks can be catalogued as either
# geographical places (adm_div/place) or separate attractions.
OBJECT_TYPES = {"cafe": "branch", "park": "adm_div.place,attraction", "family": "attraction"}
ASTANA_REGION_ID = 68


class TwoGisError(Exception):
    pass


def search_plan(query: str) -> tuple[str, int, str]:
    text = query.casefold()
    if any(word in text for word in ("ребён", "ребен", "детск", "площадк", "child", "kids", "балалар", "бала")):
        return "детская площадка", 3000, "family"
    if any(word in text for word in ("музе", "museum", "мұраж")):
        return "музей", 3000, "museum"
    if any(word in text for word in ("прогул", "гулять", "парк", "walk", "park", "саябақ", "серуен")):
        return "парк", 3000, "park"
    if any(word in text for word in ("коф", "кафе", "coffee", "cafe")):
        return "кафе", 1500, "cafe"
    # Other requests remain searchable, without pretending to infer a category.
    return query, 1500, "other"


def _poi(item: dict, request: TwoGisNearbyRequest, radius_m: int, intent: str) -> TwoGisPoi | None:
    point = item.get("point")
    if not isinstance(point, dict):
        return None
    try:
        lat, lon = float(point["lat"]), float(point["lon"])
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        distance = round(distance_m(request.lat, request.lon, lat, lon))
        if distance > radius_m:
            return None
        reviews = item.get("reviews") or {}
        if not isinstance(reviews, dict):
            reviews = {}
        rating = reviews.get("general_rating", reviews.get("rating"))
        count = reviews.get("general_review_count", reviews.get("review_count"))
        rating_count = reviews.get("general_review_count_with_stars")
        description = item.get("description")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            if intent != "family":
                return None
            name = {"ru": "Детская площадка", "kk": "Балалар алаңы", "en": "Playground"}[request.language]
        rubrics = item.get("rubrics")
        rubric_names = []
        if isinstance(rubrics, list):
            rubric_names = [rubric["name"] for rubric in rubrics
                            if isinstance(rubric, dict) and isinstance(rubric.get("name"), str)]
        return TwoGisPoi(
            id=str(item["id"]), name=name, lat=lat, lon=lon,
            object_type=item.get("type") if isinstance(item.get("type"), str) else None,
            object_subtype=item.get("subtype") if isinstance(item.get("subtype"), str) else None,
            address=item.get("address_name"),
            description=description if isinstance(description, str) and description.strip() else None,
            rubrics=rubric_names,
            rating=float(rating) if rating is not None else None,
            review_count=int(count) if count is not None else None,
            rating_count=int(rating_count) if rating_count is not None else None,
            schedule=item.get("schedule") if isinstance(item.get("schedule"), dict) else None,
            distance_m=distance,
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _prefer_park_places(pois: list[TwoGisPoi]) -> list[TwoGisPoi]:
    """Collapse only nearby same-name park cards, keeping the area card."""
    selected: list[TwoGisPoi] = []
    for poi in pois:
        duplicate = next((index for index, old in enumerate(selected)
                          if old.name.casefold().strip() == poi.name.casefold().strip()
                          and distance_m(old.lat, old.lon, poi.lat, poi.lon) <= 300), None)
        if duplicate is None:
            selected.append(poi)
        elif (poi.object_type, poi.object_subtype) == ("adm_div", "place") and (
                selected[duplicate].object_type, selected[duplicate].object_subtype) != ("adm_div", "place"):
            selected[duplicate] = poi
    return selected


def schedule_to_opening_hours(schedule: dict | None) -> str | None:
    """Convert only complete, unambiguous 2GIS weekly hours to planner syntax."""
    if not schedule:
        return None
    days = (("Mon", "Mo"), ("Tue", "Tu"), ("Wed", "We"), ("Thu", "Th"),
            ("Fri", "Fr"), ("Sat", "Sa"), ("Sun", "Su"))
    rules = []
    for source_day, target_day in days:
        day = schedule.get(source_day)
        if not isinstance(day, dict):
            return None
        if day.get("day_off") or day.get("is_day_off"):
            continue
        hours = day.get("working_hours")
        if not isinstance(hours, list) or not hours:
            return None
        for interval in hours:
            if not isinstance(interval, dict):
                return None
            start, end = interval.get("from"), interval.get("to")
            if not all(isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-4]):[0-5]\d", value)
                       for value in (start, end)):
                return None
            if start == "24:00" or start == end:
                return None
            rules.append(f"{target_day} {start}-{end}")
    return "; ".join(rules) if rules else None


def as_candidate(poi: TwoGisPoi, intent: str, language: str) -> dict:
    """Adapt a catalog card to the planner's source-backed POI shape."""
    rubric_text = " ".join(poi.rubrics).casefold()
    description = (poi.description or "").casefold()
    combined = f"{rubric_text} {poi.name.casefold()}"
    if any(word in combined for word in ("музе", "museum", "мұраж")):
        category = "museum"
    elif any(word in combined for word in ("площадк", "playground", "ойын алаң")):
        category = "family"
    elif any(word in combined for word in ("парк", "сквер", "park", "саябақ")):
        category = "park"
    elif any(word in combined for word in ("коф", "кафе", "coffee", "cafe")):
        category = "cafe"
    elif intent in {"family", "park", "cafe", "museum"}:
        category = intent
    else:
        # An unknown catalog rubric cannot safely be assigned an activity.
        return {}
    tags = {"2gis:rubrics": rubric_text}
    if poi.description:
        tags[f"description:{language}"] = poi.description
    if category == "museum" and any(phrase in f"{description} {poi.name.casefold()}" for phrase in (
        "интерактивный музей", "интерактивные экспонаты", "interactive museum",
    )):
        tags["interactive"] = "yes"
    return {
        "id": f"2gis/{poi.id}", "name": poi.name, "names": {"default": poi.name},
        "description": poi.description, "category": category, "tags": tags,
        "lat": poi.lat, "lon": poi.lon,
        "opening_hours": schedule_to_opening_hours(poi.schedule), "website": None, "phone": None,
        "source_url": f"https://2gis.kz/astana/{'firm' if poi.object_type == 'branch' else 'geo'}/{poi.id}",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


async def nearby(request: TwoGisNearbyRequest, config: Settings) -> TwoGisNearbyResponse:
    if not config.twogis_api_key:
        raise TwoGisError("2GIS_API_KEY is not configured")
    search_query, radius_m, intent = search_plan(request.query)
    params = {
        "key": config.twogis_api_key,
        "q": search_query,
        "point": f"{request.lon},{request.lat}",
        "location": f"{request.lon},{request.lat}",
        "radius": radius_m,
        "sort": "distance",
        "page": 1,
        "page_size": 10,
        "locale": {"ru": "ru_KZ", "kk": "kk_KZ", "en": "en_RU"}[request.language],
        "fields": FIELDS,
    }
    if intent in OBJECT_TYPES:
        params["type"] = OBJECT_TYPES[intent]
    if intent in RUBRIC_IDS:
        params["rubric_id"] = RUBRIC_IDS[intent]
        params["region_id"] = ASTANA_REGION_ID
    try:
        async with httpx.AsyncClient(timeout=config.twogis_timeout_seconds) as client:
            response = await client.get(PLACES_URL, params=params)
            # The request URL contains the key: never expose response/request exceptions.
            if response.status_code in (401, 403):
                raise TwoGisError("2GIS rejected the API key or field access")
            if response.status_code == 429:
                raise TwoGisError("2GIS request quota or rate limit reached")
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise TwoGisError(f"2GIS request failed: {type(exc).__name__}") from None
    except ValueError:
        raise TwoGisError("2GIS returned invalid JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict):
        raise TwoGisError("2GIS returned an invalid response")
    code = data["meta"].get("code")
    if code == 404:
        items, total = [], 0
    elif code == 200:
        result = data.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise TwoGisError("2GIS returned an invalid result list")
        items, total = result["items"], result.get("total")
    else:
        raise TwoGisError(f"2GIS search failed (code {code})")
    pois = [poi for item in items[:10] if isinstance(item, dict)
            if (poi := _poi(item, request, radius_m, intent)) is not None]
    if intent == "park":
        pois = _prefer_park_places(pois)
    return TwoGisNearbyResponse(
        recommendations=pois,
        context_used={
            "query": request.query, "search_query": search_query, "intent": intent,
            "origin": {"lat": request.lat, "lon": request.lon},
            "radius_m": radius_m, "page": 1, "page_size": 10,
            "object_type": params.get("type"),
            "rubric_id": params.get("rubric_id"),
            "region_id": params.get("region_id"),
            "distance_method": "straight_line_estimate",
        },
        total_found=total if isinstance(total, int) else None,
    )
