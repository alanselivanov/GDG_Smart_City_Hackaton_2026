from datetime import datetime
from dataclasses import replace
import asyncio
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import settings
from app.attributes import relevant_facts
from app.geocoding import mentioned_place
from app.models import RecommendRequest, TwoGisNearbyRequest
from app.recommend import rank
from app.time_intent import infer_start
from app.twogis import nearby


TZ = ZoneInfo("Asia/Almaty")
NOW = datetime(2026, 10, 19, 3, 0, tzinfo=TZ)


@pytest.mark.parametrize("query,hour,minute", [
    ("Хочу поесть возле Mega Silk Way в 9 утра", 9, 0),
    ("Куда вечером сходить поесть?", 19, 0),
    ("Поесть в 9 вечера", 21, 0),
    ("Ужин в 21:30", 21, 30),
])
def test_query_planned_start(query, hour, minute):
    start, _ = infer_start(query, NOW)
    assert (start.hour, start.minute, start.date()) == (hour, minute, NOW.date())


def test_time_after_place_is_not_part_of_its_name():
    assert mentioned_place("Хочу поесть возле Mega Silk Way в 9 утра") == "Mega Silk Way"
    assert mentioned_place("Хочу поесть возле Mega Silk Way вечером") == "Mega Silk Way"
    assert mentioned_place("Eat near Mega Silk Way at 9 am") == "Mega Silk Way"
    assert infer_start("Хочу погулять в течение часа", NOW) is None


def test_explicit_today_stays_today_and_implicit_past_time_rolls_forward():
    start, _ = infer_start("Поесть сегодня в 9 утра", NOW)
    assert start.date() == NOW.date()
    start, _ = infer_start("Поесть в 9 утра", NOW.replace(hour=12))
    assert start.date() > NOW.date()


def test_daytime_checks_listed_hours_and_keeps_missing_hours():
    def poi(identity, hours):
        return {"id": identity, "name": identity, "names": {"default": identity},
                "category": "cafe", "lat": 51.1, "lon": 71.41,
                "description": None, "tags": {}, "attribute_groups": [], "facts": [],
                "opening_hours": hours, "website": None, "phone": None,
                "source_url": "https://example.org/" + identity,
                "fetched_at": "2026-10-19T00:00:00+00:00"}

    places = [poi("open", "Mo 08:00-10:00"), poi("unknown", None),
              poi("closing", "Mo 08:00-09:20")]
    routes = {place["id"]: [(300, 300)] for place in places}
    request = RecommendRequest(lat=51.1, lon=71.41, query="Кофе в 9 утра",
                               starts_at=datetime(2026, 10, 19, 9, 0, tzinfo=TZ))
    recommendations, _, _ = rank(places, request, routes)
    assert [item.poi.id for item in recommendations] == ["open", "unknown"]
    assert recommendations[0].open_status == "open"
    assert recommendations[1].open_status == "unknown"


def test_2gis_search_does_not_hide_venues_without_listed_hours(monkeypatch):
    original_client = httpx.AsyncClient
    requested_times = []

    def handler(request):
        requested_times.append(request.url.params.get("work_time"))
        if "work_time" in request.url.params:
            items = [{"id": "open", "name": "Open restaurant",
                      "point": {"lat": 51.1, "lon": 71.41}}]
        else:
            items = [{"id": "unknown", "name": "Unknown restaurant",
                      "point": {"lat": 51.1, "lon": 71.41}},
                     {"id": "open", "name": "Open restaurant",
                      "point": {"lat": 51.1, "lon": 71.41}}]
        return httpx.Response(200, json={"meta": {"code": 200},
                                         "result": {"total": len(items), "items": items}})

    monkeypatch.setattr("app.twogis.httpx.AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    request = TwoGisNearbyRequest(query="Хочу поесть", lat=51.1, lon=71.41)
    config = replace(settings, twogis_api_key="test")
    result = asyncio.run(nearby(request, config,
                                open_at=datetime(2026, 10, 19, 9, tzinfo=TZ)))
    assert requested_times == ["mon,09:00", None]
    assert [poi.id for poi in result.recommendations] == ["open", "unknown"]


def test_fallback_explanation_prioritizes_meal_relevant_attributes():
    venue = {"attribute_groups": [{"name": "Info", "attributes": [
        {"name": "Детское меню", "tag": "food_kids_menu"},
        {"name": "Ланч от 4000 ₸", "tag": "food_lunch"},
        {"name": "Турецкая кухня", "tag": "food_cuisine_turkish"},
        {"name": "Завтрак", "tag": "food_breakfast"},
    ]}]}
    morning = [item["name"] for item in relevant_facts(venue, "поесть в 9 утра", 9)]
    evening = [item["name"] for item in relevant_facts(venue, "поесть вечером", 19)]
    assert morning[:2] == ["Завтрак", "Турецкая кухня"]
    assert "Ланч от 4000 ₸" not in morning
    assert evening[0] == "Турецкая кухня"
    assert "Завтрак" not in evening
