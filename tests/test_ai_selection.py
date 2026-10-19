"""The model chooses among eligible POIs; invalid output cannot add a place."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx

from app.ai_selection import AISelection, score_candidates
from app.config import settings
from app.db import Database
from app.embeddings import EmbeddingError
from app.generation import _local_guard, _place_context
from app.ingest import normalize_element
from app.main import create_app
from app.models import GroupRecommendRequest, PoiFact, PoiOut, RecommendRequest, Recommendation
from app.recommend import candidate_pois, eligible_for_intent


def _rec(identity: str, name: str, walk: int) -> Recommendation:
    return Recommendation(
        poi=PoiOut(id=identity, name=name, category="food", lat=51.1, lon=71.4,
                   description=None, opening_hours="24/7", website=None, phone=None,
                   source_url=f"https://example.test/{identity}", fetched_at="2026-10-19T00:00:00+00:00"),
        distance_m=walk * 75, walking_minutes=walk, walking_seconds=walk * 60,
        visit_minutes=45, open_status="open", open_status_reason="Known hours",
        why="Known restaurant", what_to_do="Choose a meal.",
    )


def test_ai_scores_all_supplied_places_and_proximity_is_first():
    near, far = _rec("osm/near", "Near", 2), _rec("osm/far", "Far", 10)
    request = RecommendRequest(query="Хочу поесть поближе", lat=51.1, lon=71.4)
    captured = []
    real_client = httpx.AsyncClient

    def handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        captured.append(body)
        decision = {"priorities": ["walking_time", "request_fit", "confirmed_open"],
                    "scores": {"osm/far": 45, "osm/near": 95},
                    "selected_ids": ["osm/near", "osm/far"]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(decision)}}]})

    config = replace(settings, llm_api_key="test-key", auto_refresh=False)
    with patch("app.ai_selection.httpx.AsyncClient",
               side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)):
        decision = asyncio.run(score_candidates([far, near], request,
            datetime(2026, 10, 19, 13, tzinfo=ZoneInfo("Asia/Almaty")), config))
    assert decision is not None
    assert [rec.poi.id for rec in decision.recommendations] == ["osm/near", "osm/far"]
    assert decision.priorities[0] == "walking_time"
    sent = json.loads(captured[0]["messages"][1]["content"])
    assert {item["id"] for item in sent["candidates"]} == {"osm/near", "osm/far"}
    assert all("lat" not in item and "lon" not in item for item in sent["candidates"])
    schema = captured[0]["response_format"]["json_schema"]["schema"]["properties"]["scores"]
    assert set(schema["required"]) == {"osm/near", "osm/far"}
    assert schema["additionalProperties"] is False


def test_ai_rejects_invented_place_and_ignoring_proximity():
    near, far = _rec("osm/near", "Near", 2), _rec("osm/far", "Far", 10)
    request = RecommendRequest(query="Хочу поесть поближе", lat=51.1, lon=71.4)
    real_client = httpx.AsyncClient
    replies = [
        {"priorities": ["walking_time"], "scores": {"osm/near": 95, "made-up": 80},
         "selected_ids": ["osm/near", "made-up"]},
        {"priorities": ["rating", "walking_time"], "scores": {"osm/near": 40, "osm/far": 90},
         "selected_ids": ["osm/far", "osm/near"]},
        {"priorities": ["walking_time"], "scores": {"osm/near": 40, "osm/far": 90},
         "selected_ids": ["osm/near", "osm/far"]},
    ]
    config = replace(settings, llm_api_key="test-key", auto_refresh=False)
    for reply in replies:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(reply)}}]})

        with patch("app.ai_selection.httpx.AsyncClient",
                   side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)):
            decision = asyncio.run(score_candidates([near, far], request,
                datetime(2026, 10, 19, 13, tzinfo=ZoneInfo("Asia/Almaty")), config))
        assert decision is None


def test_nearby_place_survives_semantic_shortlist():
    request = RecommendRequest(query="Хочу поесть поближе", lat=51.09, lon=71.4)
    pois = [{"id": "near", "category": "food", "lat": 51.0901, "lon": 71.4001,
             "tags": {}, "attribute_groups": [], "names": {"default": "Near"}}]
    pois.extend({"id": f"far-{index}", "category": "food", "lat": 51.105,
                 "lon": 71.41 + index * 0.0001, "tags": {}, "attribute_groups": [],
                 "names": {"default": f"Far {index}"}} for index in range(20))
    scores = {poi["id"]: 0.9 for poi in pois}
    scores["near"] = 0.0
    shortlist = candidate_pois(pois, request, scores, limit=6)
    assert shortlist[0]["id"] == "near"


def test_group_scoring_sees_each_members_walk_and_interests():
    first, second = _rec("osm/first", "First", 4), _rec("osm/second", "Second", 6)
    first.participant_walking_minutes = [3, 4, 5]
    first.participant_interest_matches = [True, False, True]
    second.participant_walking_minutes = [2, 6, 7]
    second.participant_interest_matches = [True, True, True]
    request = GroupRecommendRequest(query="Где поесть группе", participants=[
        {"lat": 51.09, "lon": 71.4, "interests": ["food"]},
        {"lat": 51.10, "lon": 71.4, "interests": ["cafe"]},
        {"lat": 51.11, "lon": 71.4, "interests": ["food"]},
    ])
    sent = []
    real_client = httpx.AsyncClient

    def handler(http_request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(http_request.content))
        result = {"priorities": ["group_fairness", "request_fit"],
                  "scores": {"osm/first": 70, "osm/second": 85},
                  "selected_ids": ["osm/second", "osm/first"]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(result)}}]})

    with patch("app.ai_selection.httpx.AsyncClient",
               side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)):
        decision = asyncio.run(score_candidates([first, second], request,
            datetime(2026, 10, 19, 13, tzinfo=ZoneInfo("Asia/Almaty")),
            replace(settings, llm_api_key="test-key")))
    assert decision is not None
    assert decision.recommendations[0].poi.id == "osm/second"
    payload = json.loads(sent[0]["messages"][1]["content"])
    assert payload["group_interests"] == [["food"], ["cafe"], ["food"]]
    assert payload["candidates"][1]["participant_walk_minutes"] == [2, 6, 7]


def test_generated_why_must_explain_proximity_when_requested():
    rec = _rec("osm/near", "Near", 2)
    rec.poi.facts = [PoiFact(key="cuisine", kind="distinctive", text="Турецкая кухня",
                             source_url="https://example.test/fact", verified_at="2026-10-19")]
    place = _place_context(rec, "Хочу поесть поближе", datetime(2026, 10, 19, 13,
                            tzinfo=ZoneInfo("Asia/Almaty")))
    item = {"why": "Здесь указана турецкая кухня.", "what_to_do": "Выберите турецкую кухню.",
            "used_fact_ids": ["e0"]}
    assert _local_guard(item, rec, place) is False
    item["why"] = "До места 2 мин пешком."
    assert _local_guard(item, rec, place) is False
    item["why"] = "До места 2 мин пешком; здесь указана турецкая кухня."
    assert _local_guard(item, rec, place) is True


def test_unusual_food_request_keeps_sourced_restaurants_available_to_ai():
    request = RecommendRequest(query="Хочу необычно поесть", lat=51.09, lon=71.4)
    poi = {"id": "2gis/restaurant", "category": "food", "lat": 51.091, "lon": 71.401,
           "tags": {}, "attribute_groups": [{"name": "Особенности", "attributes": [
               {"name": "Панорамный ресторан", "tag": "panoramic_restaurant"}]}],
           "names": {"default": "Restaurant"}}
    assert eligible_for_intent(poi, request) is True
    assert eligible_for_intent({**poi, "attribute_groups": []}, request) is False


def test_endpoint_uses_ai_choice_instead_of_previous_order():
    with TemporaryDirectory() as tmp:
        config = replace(settings, database_path=Path(tmp) / "poi.sqlite3", auto_refresh=False,
                         llm_api_key="test-key", twogis_api_key="")
        db = Database(config.database_path)
        db.init()
        db.upsert_pois([normalize_element({"type": "node", "id": i,
            "lat": 51.09 + i * 0.001, "lon": 71.4 + i * 0.001,
            "tags": {"name": name, "amenity": "restaurant", "opening_hours": "24/7"}})
            for i, name in ((1, "First restaurant"), (2, "Second restaurant"))])
        seen = []

        async def fake_scores(_db, pois, _query, _config):
            return {poi["id"]: 0.5 for poi in pois}

        async def fake_routes(_origins, pois, _config):
            return {poi["id"]: [(350, 300)] for poi in pois}

        async def choose(pool, _request, _start, _config):
            seen.extend(rec.poi.id for rec in pool)
            reversed_pool = list(reversed(pool))
            return AISelection(reversed_pool, ["request_fit"],
                               {rec.poi.id: 90 - index for index, rec in enumerate(reversed_pool)}, len(pool))

        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(config)),
                                         base_url="http://test") as client:
                return await client.post("/v1/recommendations", json={
                    "query": "Хочу поесть", "lat": 51.09, "lon": 71.4})

        with patch("app.main.semantic_scores", fake_scores), patch("app.main.pedestrian_matrix", fake_routes), \
                patch("app.main.score_candidates", choose), patch("app.main.enhance", AsyncMock(return_value=False)):
            response = asyncio.run(call())
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(seen) == 2
        assert [item["poi"]["id"] for item in body["recommendations"]] == list(reversed(seen))
        assert body["context_used"]["selection_method"] == "ai_scored"

        with patch("app.main.semantic_scores", fake_scores), patch("app.main.pedestrian_matrix", fake_routes), \
                patch("app.main.score_candidates", AsyncMock(return_value=None)), \
                patch("app.main.enhance", AsyncMock(return_value=False)):
            fallback = asyncio.run(call())
        assert fallback.status_code == 200, fallback.text
        assert fallback.json()["context_used"]["selection_method"] == "rules_fallback"
        assert fallback.json()["recommendations"]


def test_embedding_timeout_keeps_recommendations_available():
    with TemporaryDirectory() as tmp:
        config = replace(settings, database_path=Path(tmp) / "poi.sqlite3", auto_refresh=False,
                         llm_api_key="test-key", twogis_api_key="")
        db = Database(config.database_path)
        db.init()
        db.upsert_pois([normalize_element({"type": "node", "id": i,
            "lat": 51.09 + i * 0.001, "lon": 71.4 + i * 0.001,
            "tags": {"name": name, "amenity": "restaurant", "opening_hours": "24/7"}})
            for i, name in ((1, "First restaurant"), (2, "Second restaurant"))])

        async def fake_routes(_origins, pois, _config):
            return {poi["id"]: [(350, 300)] for poi in pois}

        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(config)),
                                         base_url="http://test") as client:
                return await client.post("/v1/recommendations", json={
                    "query": "Хочу поесть поближе", "lat": 51.09, "lon": 71.4})

        with patch("app.main.semantic_scores", AsyncMock(
                side_effect=EmbeddingError("Embedding API failed: ReadTimeout"))), \
                patch("app.main.pedestrian_matrix", fake_routes), \
                patch("app.main.score_candidates", AsyncMock(return_value=None)) as ai_score, \
                patch("app.main.enhance", AsyncMock(return_value=False)):
            response = asyncio.run(call())

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recommendations"]
        assert body["context_used"]["embedding_fallback_used"] is True
        assert body["context_used"]["retrieval_method"] == "geospatial_and_filters"
        assert body["context_used"]["selection_method"] == "rules_fallback"
        assert any("Смысловой поиск временно недоступен" in note for note in body["notices"])
        assert "ReadTimeout" not in response.text
        ai_score.assert_awaited_once()
