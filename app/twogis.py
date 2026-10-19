"""2GIS Places search independent of the OSM dataset."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.models import (TwoGisAttribute, TwoGisAttributeGroup, TwoGisNearbyRequest,
                        TwoGisNearbyResponse, TwoGisPoi)
from app.attraction_facts import NUR_ALEM_2GIS_BUILDING_ID, VERIFIED_AT, name_matched_facts
from app.recommend import distance_m


PLACES_URL = "https://catalog.api.2gis.com/3.0/items"
FIELDS = "items.point,items.description,items.reviews,items.schedule,items.rubrics,items.attribute_groups"
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
    # Dining with children is a restaurant request, not a playground request.
    if any(word in text for word in ("детское меню", "детским меню", "kids menu", "балалар мәзір")):
        return "кафе", 1500, "cafe"
    if any(word in text for word in ("коф", "кафе", "coffee", "cafe", "ресторан", "restaurant")):
        return "кафе", 1500, "cafe"
    if any(word in text for word in ("поесть", "поем", "поужин", "ужин", "обед", "завтрак", "позавтрак", "breakfast", "eat", "dinner", "lunch", "тамақ")):
        return "ресторан", 3000, "food"
    if any(word in text for word in ("прогул", "гулять", "парк", "walk", "park", "саябақ", "серуен")):
        return "парк", 3000, "park"
    if any(word in text for word in ("смотров", "обзорная площадка", "viewpoint", "көрініс алаң")):
        return "смотровая площадка", 3000, "viewpoint"
    if any(word in text for word in ("памятник", "монумент", "мемориал", "скульптур", "monument", "memorial")):
        return "памятник", 3000, "landmark"
    if any(word in text for word in ("ночью", "ночное", "ночной", "ночная", "night", "түнгі", "түнде")):
        return "бар", 3000, "nightlife"
    if any(word in text for word in ("музе", "museum", "мұраж")) and not any(
        word in text for word in ("площадк", "playground", "ойын алаң")
    ):
        return "музей", 3000, "museum"
    if any(word in text for word in ("ребён", "ребен", "детск", "площадк", "child", "kids", "балалар", "бала")):
        return "детская площадка", 3000, "family"
    if any(word in text for word in ("музе", "museum", "мұраж")):
        return "музей", 3000, "museum"
    # Other requests remain searchable, without pretending to infer a category.
    return query, 1500, "other"


def _attribute_groups(raw: object) -> list[TwoGisAttributeGroup]:
    """Keep every named 2GIS Info fact, including menu, prices and services."""
    if not isinstance(raw, list):
        return []
    groups = []
    for group in raw[:100]:
        if not isinstance(group, dict) or not isinstance(group.get("attributes"), list):
            continue
        name = group.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        attributes = []
        for raw_attribute in group["attributes"][:500]:
            if not isinstance(raw_attribute, dict):
                continue
            label = raw_attribute.get("name")
            if not isinstance(label, str) or not label.strip():
                continue
            tag = raw_attribute.get("tag")
            identity = raw_attribute.get("id")
            attributes.append(TwoGisAttribute(
                name=label.strip()[:200], tag=tag[:120] if isinstance(tag, str) else None,
                id=identity if isinstance(identity, (str, int)) and not isinstance(identity, bool) else None,
            ))
        if attributes:
            groups.append(TwoGisAttributeGroup(name=name.strip()[:200], attributes=attributes))
    return groups


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
            source_url=f"https://2gis.kz/astana/{'firm' if item.get('type') == 'branch' else 'geo'}/{item['id']}",
            object_type=item.get("type") if isinstance(item.get("type"), str) else None,
            object_subtype=item.get("subtype") if isinstance(item.get("subtype"), str) else None,
            address=item.get("address_name"),
            description=description if isinstance(description, str) and description.strip() else None,
            rubrics=rubric_names,
            attribute_groups=_attribute_groups(item.get("attribute_groups")),
            # The Astana catalog search is reliably populated in ru_KZ. The
            # response language describes catalog facts, not the UI language.
            attributes_language="ru",
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
    matched_facts = name_matched_facts(poi.name, poi.lat, poi.lon, f"2gis/{poi.id}")
    expo_sphere = poi.id == NUR_ALEM_2GIS_BUILDING_ID and bool(matched_facts)
    if not matched_facts and re.match(
        r"(?iu)^\s*(?:улица|ул\.|проспект|пр-т|переулок|проезд|шоссе|street|avenue)\b",
        poi.name,
    ):
        # An address card with a broad attraction rubric is not a named POI.
        return {}
    if any(word in combined for word in ("музе", "museum", "мұраж")):
        category = "museum"
    elif re.search(r"(?iu)\b(?:бар|паб|ночной клуб|караоке|лаунж|pub|bar|night club)\b", combined):
        category = "nightlife"
    elif any(word in combined for word in ("смотровая площадка", "обзорная площадка", "viewpoint", "көрініс алаң")):
        category = "viewpoint"
    elif any(word in combined for word in ("площадк", "playground", "ойын алаң")):
        category = "family"
    elif any(word in rubric_text for word in ("памятник", "монумент", "мемориал", "скульптур", "monument", "memorial")):
        category = "landmark"
    elif any(word in combined for word in ("парк", "сквер", "park", "саябақ")):
        category = "park"
    elif any(word in combined for word in ("памятник", "монумент", "мемориал", "скульптур", "monument", "memorial")):
        category = "landmark"
    elif any(word in combined for word in ("коф", "кафе", "coffee", "cafe")):
        category = "cafe"
    elif any(word in combined for word in ("ресторан", "restaurant", "столов", "кухня", "dining")):
        category = "food"
    elif matched_facts:
        category = "landmark"
    elif intent in {"family", "park", "cafe", "museum"}:
        category = intent
    else:
        # An unknown catalog rubric cannot safely be assigned an activity.
        return {}
    tags = {"2gis:rubrics": rubric_text}
    if expo_sphere:
        tags["2gis:catalog_name"] = poi.name
    if poi.description:
        tags[f"description:{poi.attributes_language or language}"] = poi.description
    if category == "museum" and any(phrase in f"{description} {poi.name.casefold()}" for phrase in (
        "интерактивный музей", "интерактивные экспонаты", "interactive museum",
    )):
        tags["interactive"] = "yes"
    return {
        "id": f"2gis/{poi.id}", "name": "Нур-Алем" if expo_sphere else poi.name,
        "names": ({"default": "Нур-Алем", "ru": "Нур-Алем", "en": "Nur Alem", "kk": "Нұр Әлем"}
                  if expo_sphere else {"default": poi.name}),
        "description": poi.description, "category": category, "tags": tags,
        "attribute_groups": [group.model_dump() for group in poi.attribute_groups],
        "attributes_language": poi.attributes_language,
        "rating": poi.rating, "review_count": poi.review_count,
        "facts": [{"fact_key": fact["key"], "kind": fact["kind"],
                   "text_ru": fact["ru"], "text_en": fact["en"], "text_kk": fact["kk"],
                   "action_ru": fact["action_ru"], "action_en": fact["action_en"],
                   "action_kk": fact["action_kk"], "source_url": fact["source_url"],
                   "verified_at": VERIFIED_AT} for fact in matched_facts],
        "lat": poi.lat, "lon": poi.lon,
        "opening_hours": schedule_to_opening_hours(poi.schedule), "website": None, "phone": None,
        "source_url": poi.source_url or f"https://2gis.kz/astana/{'firm' if poi.object_type == 'branch' else 'geo'}/{poi.id}",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


async def nearby(request: TwoGisNearbyRequest, config: Settings, *, open_at: datetime | None = None) -> TwoGisNearbyResponse:
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
        # The Astana catalog returns meta.code=404 with en_RU and rejects en_KZ.
        # Search in the working Russian catalog, then label raw facts honestly.
        # kk_KZ can omit nearby attractions that ru_KZ returns. Keep retrieval
        # independent of the requested answer language; localize the response
        # afterwards and label Russian catalog attributes honestly.
        "locale": "ru_KZ",
        "fields": FIELDS,
    }
    if intent in OBJECT_TYPES:
        params["type"] = OBJECT_TYPES[intent]
    if intent in RUBRIC_IDS:
        params["rubric_id"] = RUBRIC_IDS[intent]
        params["region_id"] = ASTANA_REGION_ID
    # A filtered search surfaces venues known to be open even when they are not
    # among the ten closest. The unfiltered search also keeps places with no
    # listed schedule. The planner verifies the entire visit afterwards.
    queries = [params]
    if open_at and intent in {"food", "cafe", "nightlife", "museum", "family"}:
        local = open_at.astimezone(ZoneInfo("Asia/Almaty"))
        work_time = f"{('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[local.weekday()]},{local:%H:%M}"
        queries.insert(0, {**params, "work_time": work_time})
    all_items: list[dict] = []
    total = None
    try:
        async with httpx.AsyncClient(timeout=config.twogis_timeout_seconds) as client:
            for search_params in queries:
                response = await client.get(PLACES_URL, params=search_params)
                # The request URL contains the key: never expose response/request exceptions.
                if response.status_code in (401, 403):
                    raise TwoGisError("2GIS rejected the API key or field access")
                if response.status_code == 429:
                    raise TwoGisError("2GIS request quota or rate limit reached")
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("meta"), dict):
                    raise TwoGisError("2GIS returned an invalid response")
                code = data["meta"].get("code")
                if code == 404:
                    continue
                if code != 200:
                    raise TwoGisError(f"2GIS search failed (code {code})")
                result = data.get("result")
                if not isinstance(result, dict) or not isinstance(result.get("items"), list):
                    raise TwoGisError("2GIS returned an invalid result list")
                if search_params is params:
                    total = result.get("total")
                all_items.extend(item for item in result["items"][:10] if isinstance(item, dict))
    except httpx.HTTPError as exc:
        raise TwoGisError(f"2GIS request failed: {type(exc).__name__}") from None
    except ValueError:
        raise TwoGisError("2GIS returned invalid JSON") from None
    pois = []
    seen_ids = set()
    for item in all_items:
        poi = _poi(item, request, radius_m, intent)
        if poi is not None and poi.id not in seen_ids:
            pois.append(poi)
            seen_ids.add(poi.id)
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
            "catalog_locale": params["locale"],
            "catalog_work_time": queries[0].get("work_time"),
        },
        total_found=total if isinstance(total, int) else None,
    )
