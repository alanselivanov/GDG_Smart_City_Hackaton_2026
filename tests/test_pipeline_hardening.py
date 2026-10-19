"""Regression checks for failures found by the live backend audit."""
import asyncio
import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.attraction_facts import ATTRACTIONS, name_matched_facts
from app.config import settings
from app.generation import _local_guard, _place_context
from app.geocoding import mentioned_place
from app.ingest import fetch_pois
from app.models import PoiFact, PoiOut, Recommendation
from app.rate_limit import ApiLimiter


def test_origin_parser_separates_place_from_activity_and_duration():
    assert mentioned_place("Хочу прогуляться в парке рядом за час") is None
    assert mentioned_place("I want to walk near Mega Silk Way for one hour") == "Mega Silk Way"
    assert mentioned_place("Я рядом с Mega Silk Way, где погулять 2 часа?") == "Mega Silk Way"
    assert mentioned_place("Я у здания Экспо 2017, хочу что-то необычное на 1–2 часа") == "Экспо 2017"


def test_overpass_switches_mirror_after_406_without_losing_real_poi():
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "primary.test":
            return httpx.Response(406, text="not acceptable")
        return httpx.Response(200, json={"elements": [{"type": "node", "id": 456,
            "lat": 51.09, "lon": 71.4, "tags": {"name": "Real Cafe", "amenity": "cafe"}}]})

    original_client = httpx.AsyncClient
    config = replace(settings, overpass_url="https://primary.test/api/interpreter",
                     overpass_fallback_urls=("https://mirror.test/api/interpreter",))
    with patch("app.ingest.httpx.AsyncClient", side_effect=lambda **kwargs:
               original_client(transport=httpx.MockTransport(handler), **kwargs)), \
         patch("app.ingest.asyncio.sleep", new=AsyncMock(return_value=None)):
        pois = asyncio.run(fetch_pois(config))
    assert calls == ["primary.test", "mirror.test"]
    assert pois[0]["id"] == "node/456"


def test_api_budget_limits_per_client_and_daily_total():
    limiter = ApiLimiter(per_minute=1, per_day=2)
    asyncio.run(limiter.charge("client-a"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(limiter.charge("client-a"))
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"]
    asyncio.run(limiter.charge("client-b"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(limiter.charge("client-c"))
    assert exc.value.status_code == 429
    assert "Daily" in exc.value.detail


def test_reviewed_sight_facts_have_sources_and_spatial_matching():
    assert ATTRACTIONS["way/240860325"]["facts"][0]["source_url"].startswith("https://visitastana.kz/")
    assert name_matched_facts("ЭКСПО-парк", 51.09, 71.4)[0]["key"] == "expo_walkways"
    assert name_matched_facts("ЭКСПО-парк", 51.2, 71.4) == []


def test_ai_copy_rejects_scheduled_event_claim_from_generic_attribute():
    rec = Recommendation(
        poi=PoiOut(id="2gis/1", name="Sports Bar", category="nightlife", lat=51.1, lon=71.4,
                   description=None, opening_hours="24/7", website=None, phone=None,
                   source_url="https://2gis.kz/astana/firm/1", fetched_at="2026-10-19T00:00:00Z",
                   facts=[PoiFact(key="sports", kind="distinctive", text="Спортивные трансляции",
                                  source_url="https://2gis.kz/astana/firm/1", verified_at="2026-10-19")]),
        distance_m=400, walking_minutes=6, walking_seconds=360, visit_minutes=30,
        open_status="open", open_status_reason="Listed hours", why="", what_to_do="",
    )
    place = _place_context(rec, "Что делать ночью?", datetime(2026, 10, 20, 23,
                            tzinfo=ZoneInfo("Asia/Almaty")))
    item = {"why": "В заведении указаны спортивные трансляции.",
            "what_to_do": "Посмотрите спортивную трансляцию здесь.", "used_fact_ids": ["e0"]}
    assert _local_guard(item, rec, place) is False
    item["what_to_do"] = "Уточните расписание спортивных трансляций перед визитом."
    assert _local_guard(item, rec, place) is True


def test_ai_copy_cannot_claim_feasible_visit_exceeds_budget():
    rec = Recommendation(
        poi=PoiOut(id="osm/park", name="Парк", category="park", lat=51.1, lon=71.4,
                   description=None, opening_hours=None, website=None, phone=None,
                   source_url="https://www.openstreetmap.org/way/1", fetched_at="2026-10-19T00:00:00Z"),
        distance_m=2000, walking_minutes=27, walking_seconds=1620, visit_minutes=35,
        open_status="unknown", open_status_reason="Hours unknown", why="", what_to_do="",
    )
    place = _place_context(rec, "Где погулять 2 часа?", None, time_budget_minutes=120)
    item = {"why": "Парк в 27 минутах ходьбы, что превышает ваше время прогулки.",
            "what_to_do": "Прогуляйтесь по парку и вернитесь.",
            "used_fact_ids": ["route_and_category"]}
    assert _local_guard(item, rec, place) is False
