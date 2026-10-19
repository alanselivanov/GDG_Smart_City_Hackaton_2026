"""Resolve a mentioned Astana place before ranking recommendations."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import re
import unicodedata

import httpx

from app.config import Settings
from app.db import Database
from app.models import RecommendRequest
from app.recommend import distance_m


class LocationError(Exception):
    def __init__(self, detail: str, status_code: int = 422):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


_MENTION = re.compile(
    r"(?iu)(?:^|[\s,.;])(?:я\s+)?(?:сейчас\s+)?(?:нахожусь\s+)?"
    r"(?:возле|около|у(?!\s+меня\b)|рядом\s+с|неподал[её]ку\s+от|near|by|at)\s+"
    r"(?:(?:здания|здании|трц|тц|музея|парка|мечети)\s+)?"
    r"(?P<place>[^,;:.!?—–]+)"
)
_OTHER_MENTION = re.compile(
    r"(?iu)(?:^|[\s,.;])(?:я\s+)?(?:сейчас\s+)?(?:нахожусь\s+)?"
    r"(?:в|на|inside)\s+(?:здании|трц|тц|музее|парке)\s+(?P<place>[^,;:.!?—–]+)"
)
_TAIL = re.compile(r"(?iu)\s+(?:(?:и\s+)?(?:хочу|ищу|планирую)|подскажите|посоветуйте|что\s+посоветуете|where|want\s+to)\b")
_TIME_TAIL = re.compile(
    r"(?iu)\s+(?:в\s+\d{1,2}(?::\d{2})?\s*(?:утра|дня|вечера|ночи)|"
    r"в\s+\d{1,2}:\d{2}|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|"
    r"in\s+the\s+(?:morning|afternoon|evening)\b|"
    r"сегодня\b|завтра\b|утром\b|днём\b|днем\b|вечером\b|ночью\b)"
)
_REQUEST_TAIL = re.compile(
    r"(?iu)\s+(?:за\s+\d+\s*(?:час|минут)|на\s+\d+\s*(?:час|минут)|"
    r"в\s+течени[еи]\s+\d+\s*(?:час|минут)|"
    r"for\s+(?:(?:one|two|three|\d+)\s+)?(?:hours?|minutes?)\b|"
    r"на\s+час\b|за\s+час\b|"
    r"пешком\b|с\s+реб[её]нком\b|with\s+(?:a\s+)?child\b|"
    r"где\b|куда\b|что\s+делать\b|to\s+(?:walk|eat|visit|spend)\b)"
)
_GENERIC_PLACE = re.compile(
    r"(?iu)^(?:рядом|поближе|недалеко|здесь|тут|там|nearby|around|"
    r"за\s+\w+|на\s+\w+|for\s+\w+|"
    r"погулять|поесть|отдохнуть)(?:\b|$)"
)
_THERE = re.compile(r"(?iu)\b(?:я\s+)?(?:сейчас\s+)?(?:там|there)\b")
_TIME_AFTER_AROUND = re.compile(
    r"(?iu)^(?:\d|час(?:а|ов)?\b|минут|полчас|полутора?\b|пары?\s+час)"
)
_PLACE_ALIASES = {
    "mega silkway": "Mega Silk Way",
    "меги силквей": "Mega Silk Way",
    "мега силквей": "Mega Silk Way",
    "меги силк вей": "Mega Silk Way",
    "мега силк вей": "Mega Silk Way",
}


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def canonical_place_name(value: str) -> str:
    return _PLACE_ALIASES.get(normalize_name(value), value)


def mentioned_place(query: str) -> str | None:
    for pattern in (_MENTION, _OTHER_MENTION):
        match = pattern.search(query)
        if match:
            value = match.group("place")
            for tail in (_TAIL, _TIME_TAIL, _REQUEST_TAIL):
                value = tail.split(value, 1)[0]
            value = value.strip(" \"'«»()")
            matched_start = match.group(0).casefold().lstrip()
            if matched_start.startswith("около ") and _TIME_AFTER_AROUND.match(value):
                continue
            if matched_start.startswith("at ") and re.match(
                r"(?iu)^\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", value
            ):
                continue
            if not value or _GENERIC_PLACE.match(value):
                continue
            return value[:120] or None
    return None


def _local_place(name: str, pois: list[dict], request: RecommendRequest) -> dict | None:
    key = normalize_name(canonical_place_name(name))
    matches = [poi for poi in pois if key in {normalize_name(value) for value in poi["names"].values()}]
    if not matches:
        words = key.split()
        # Match inflected, abbreviated names such as "Национального музея" to
        # "Национальный музей Республики Казахстан", but never a generic one-word name.
        if len(words) >= 2 and all(len(word) >= 4 for word in words):
            matches = [poi for poi in pois if any(
                len(candidate_words := normalize_name(value).split()) >= len(words)
                and all(left[:4] == right[:4] for left, right in zip(words, candidate_words))
                for value in poi["names"].values()
            )]
    if not matches:
        return None
    if len(matches) > 1:
        if request.lat is None:
            raise LocationError("Several places have this name; provide location or a more specific name", 409)
        matches.sort(key=lambda poi: distance_m(request.lat, request.lon, poi["lat"], poi["lon"]))
        if distance_m(request.lat, request.lon, matches[0]["lat"], matches[0]["lon"]) > 2000:
            raise LocationError("Several places have this name; provide a more specific name", 409)
    poi = matches[0]
    return {"name": poi["name"], "lat": poi["lat"], "lon": poi["lon"],
            "source_url": poi["source_url"], "source": "local_osm"}


async def _external_place(name: str, language: str, db: Database, config: Settings) -> dict:
    key = normalize_name(name)
    cached = db.cached_geocode(key)
    if cached and datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"]) < timedelta(days=1):
        return {**cached, "source": "cached_osm_geocoder"}
    await asyncio.sleep(db.reserve_geocode_slot())
    params = {"q": name, "format": "jsonv2", "limit": 5, "countrycodes": "kz",
              "viewbox": "71.20,51.32,71.68,50.98", "bounded": 1,
              "accept-language": language}
    try:
        async with httpx.AsyncClient(timeout=config.geocoder_timeout_seconds) as client:
            response = await client.get(config.geocoder_url.rstrip("/") + "/search",
                                        params=params, headers={"User-Agent": config.geocoder_user_agent})
            response.raise_for_status()
            results = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LocationError(f"Place search unavailable: {type(exc).__name__}", 503) from exc
    if not isinstance(results, list):
        raise LocationError("Place search returned an invalid response", 503)
    options = []
    for result in results:
        try:
            primary = result["display_name"].split(",", 1)[0]
            lat, lon = float(result["lat"]), float(result["lon"])
            osm_type, osm_id = result["osm_type"], int(result["osm_id"])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if osm_type not in {"node", "way", "relation"} or not (50.98 <= lat <= 51.32 and 71.20 <= lon <= 71.68):
            continue
        similarity = SequenceMatcher(None, key, normalize_name(primary)).ratio()
        if similarity < 0.78:
            continue
        options.append((similarity, {"name": primary, "lat": lat, "lon": lon,
                                     "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}"}))
    if not options:
        messages = {
            "ru": f"Место «{name}» не найдено в Астане. Уточните название или отправьте геолокацию без названия места.",
            "en": f"Place '{name}' was not found in Astana. Check the name or send device location without a named place.",
            "kk": f"«{name}» орны Астанада табылмады. Атауын нақтылаңыз немесе орын атауынсыз геолокация жіберіңіз.",
        }
        raise LocationError(messages[language], 404)
    options.sort(key=lambda item: -item[0])
    chosen = options[0][1]
    if len(options) > 1 and options[1][0] >= options[0][0] - 0.03 and \
            distance_m(chosen["lat"], chosen["lon"], options[1][1]["lat"], options[1][1]["lon"]) > 300:
        raise LocationError("Place name is ambiguous; provide a more specific name", 409)
    db.save_geocode(key, chosen)
    return {**chosen, "source": "osm_geocoder"}


async def resolve_origin(request: RecommendRequest, pois: list[dict], db: Database,
                         config: Settings) -> dict:
    mention = mentioned_place(request.query)
    if mention:
        name, kind = mention, "query"
    elif _THERE.search(request.query):
        if not request.reference_place:
            raise LocationError("'там' needs reference_place from the previous place", 422)
        name, kind = request.reference_place, "reference_place"
    elif request.lat is not None:
        return {"name": None, "lat": request.lat, "lon": request.lon,
                "source_url": None, "source": "device_location"}
    elif request.reference_place:
        name, kind = request.reference_place, "reference_place"
    else:
        raise LocationError("Provide device lat/lon or mention a starting place in query", 422)
    place = _local_place(name, pois, request)
    if place is None:
        place = await _external_place(canonical_place_name(name), request.language, db, config)
    return {**place, "mentioned_name": name, "resolved_from": kind}
