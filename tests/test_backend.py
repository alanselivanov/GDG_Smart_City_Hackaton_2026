import asyncio
import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import httpx

from app.config import settings
from app.db import Database
from app.ingest import IngestError, normalize_element, parse_overpass
from app.main import create_app
from app.models import RecommendRequest
from app.recommend import infer_budget, opening_status, rank
from app.generation import enhance


def element(identifier: int, name: str, amenity: str, lat: float, lon: float, **tags):
    return {"type": "node", "id": identifier, "lat": lat, "lon": lon,
            "tags": {"name": name, "amenity": amenity, **tags}}


def prepared_client(tmp_path):
    config = replace(settings, database_path=tmp_path / "pois.sqlite3", auto_refresh=False,
                     admin_token="a" * 32, llm_api_key="")
    db = Database(config.database_path)
    db.init()
    data = [
        element(1, "Cafe One", "cafe", 51.09, 71.40, opening_hours="24/7", **{"name:kk": "Бірінші кафе"}),
        element(2, "Museum Two", "museum", 51.091, 71.405, opening_hours="24/7"),
        element(3, "Cafe Far", "cafe", 51.20, 71.55, opening_hours="24/7"),
    ]
    data[1]["tags"].pop("amenity")
    data[1]["tags"]["tourism"] = "museum"
    db.upsert_pois(parse_overpass({"elements": data}))
    return TestClient(create_app(config)), db


def test_overpass_normalization_and_incomplete_response():
    poi = normalize_element({"type": "way", "id": 42, "center": {"lat": 51.1, "lon": 71.4},
                             "tags": {"leisure": "playground"}})
    assert poi["source_url"] == "https://www.openstreetmap.org/way/42"
    assert poi["category"] == "family"
    assert "Playground" in poi["names_json"]
    try:
        parse_overpass({"elements": [], "remark": "timeout"})
    except IngestError:
        pass
    else:
        assert False, "incomplete Overpass data must not replace the cache"


def test_cache_replaces_old_snapshot(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.init()
    first = normalize_element(element(1, "First", "cafe", 51.1, 71.4))
    second = normalize_element(element(2, "Second", "cafe", 51.1, 71.41))
    db.upsert_pois([first, second])
    db.upsert_pois([second])
    assert [item["id"] for item in db.all_pois()] == ["node/2"]


def test_hours_are_conservative():
    tz = ZoneInfo("Asia/Almaty")
    monday_night = datetime(2026, 10, 19, 23, 30, tzinfo=tz)
    tuesday_morning = datetime(2026, 10, 20, 1, 0, tzinfo=tz)
    assert opening_status("Mo 22:00-02:00", monday_night, 30) == "open"
    assert opening_status("Mo 22:00-02:00", tuesday_morning, 30) == "open"
    assert opening_status("Mo 22:00-02:00", tuesday_morning, 90) == "closed"
    assert opening_status("Mo-Fr 09:00-18:00; PH off", monday_night, 30) == "unknown"
    assert opening_status(None, monday_night, 30) == "unknown"


def test_individual_api_localization_and_grounding(tmp_path):
    client, _ = prepared_client(tmp_path)
    with client:
        response = client.post("/v1/recommendations", json={
            "lat": 51.09, "lon": 71.40, "query": "Кофе на 30 минут", "language": "kk"
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["context_used"]["time_budget_minutes"] == 30
        assert body["generated_with"] == "grounded_templates"
        assert body["recommendations"][0]["poi"]["name"] == "Бірінші кафе"
        assert body["recommendations"][0]["poi"]["source_url"].startswith("https://www.openstreetmap.org/")
        assert body["recommendations"][0]["poi"]["category"] == "cafe"
        assert "кафе" in body["recommendations"][0]["why"]


def test_group_plan_validation_and_admin_security(tmp_path):
    client, _ = prepared_client(tmp_path)
    with client:
        request = {"language": "en", "query": "coffee", "time_budget_minutes": 60,
                   "participants": [{"lat": 51.09, "lon": 71.40, "interests": ["cafe"]},
                                    {"lat": 51.091, "lon": 71.401, "interests": ["cafe"]},
                                    {"lat": 51.092, "lon": 71.402, "interests": ["museum"]}]}
        response = client.post("/v1/group/recommendations", json=request)
        assert response.status_code == 200, response.text
        item = response.json()["recommendations"][0]
        assert item["group_meeting_at"] and item["group_ends_at"]
        assert len(item["participant_walking_minutes"]) == 3
        assert sum(item["participant_interest_matches"]) == 2
        assert "Matches the interests of 2 of 3" in item["why"]
        request["participants"] = request["participants"][:2]
        assert client.post("/v1/group/recommendations", json=request).status_code == 422
        request["participants"] = request["participants"] + [
            {"lat": 51.09, "lon": 71.40}, {"lat": 51.09, "lon": 71.40},
            {"lat": 51.09, "lon": 71.40}]
        assert client.post("/v1/group/recommendations", json=request).status_code == 200
        request["participants"].append({"lat": 51.09, "lon": 71.40})
        assert client.post("/v1/group/recommendations", json=request).status_code == 422
        assert client.post("/v1/admin/refresh").status_code == 401
        assert client.get("/v1/pois", params={"lat": 0, "lon": 0}).status_code == 422


def test_budget_inference():
    assert infer_budget("Прогулка 30–60 минут") == 60
    assert infer_budget("2 часа перед вылетом") == 120
    assert infer_budget("coffee near me") is None


def test_llm_receives_only_retrieved_facts_and_validates_ids(tmp_path, monkeypatch):
    _, db = prepared_client(tmp_path)
    request = RecommendRequest(lat=51.09, lon=71.40, query="private coffee request", language="en", limit=1)
    recommendations, _, _ = rank(db.all_pois(), request)
    original_client = httpx.AsyncClient

    def handler(http_request: httpx.Request):
        payload = json.loads(http_request.content)
        facts = payload["messages"][1]["content"]
        assert "private coffee request" not in facts
        assert '"lat"' not in facts and '"lon"' not in facts
        answer = {"items": [{"id": recommendations[0].poi.id,
                             "why": "This nearby cafe fits your coffee interest.",
                             "what_to_do": "Stop for a drink."}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    monkeypatch.setattr("app.generation.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    config = replace(settings, llm_api_key="test", llm_base_url="https://llm.example/v1")
    assert asyncio.run(enhance(recommendations, "en", config)) is True
    assert recommendations[0].what_to_do == "Stop for a drink."
