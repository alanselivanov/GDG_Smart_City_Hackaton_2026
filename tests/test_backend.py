import asyncio
import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import httpx
import pytest

from app.config import settings
from app.db import Database
from app.ingest import IngestError, normalize_element, parse_overpass
from app.main import create_app
from app.models import RecommendRequest
from app.recommend import infer_budget, opening_status, rank
from app.generation import enhance
from app.embeddings import ensure_index, semantic_scores, EmbeddingError
from app.routing import pedestrian_matrix, RoutingError
from app.recommend import distance_m
from app.geocoding import LocationError, mentioned_place


@pytest.fixture(autouse=True)
def mock_external_retrieval(monkeypatch):
    async def fake_scores(db, pois, query, config):
        return {poi["id"]: (0.8 if poi["category"] == "cafe" else 0.1) for poi in pois}

    async def fake_routes(origins, targets, config):
        return {poi["id"]: [(round(distance_m(lat, lon, poi["lat"], poi["lon"]) * 1.2),
                               round(distance_m(lat, lon, poi["lat"], poi["lon"]) * 1.2 / 1.3))
                              for lat, lon in origins] for poi in targets}

    monkeypatch.setattr("app.main.semantic_scores", fake_scores)
    monkeypatch.setattr("app.main.pedestrian_matrix", fake_routes)


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
    pois = db.all_pois()
    routes = {poi["id"]: [(100, 90)] for poi in pois}
    recommendations, _, _ = rank(pois, request, routes)
    original_client = httpx.AsyncClient

    def handler(http_request: httpx.Request):
        payload = json.loads(http_request.content)
        facts = payload["messages"][1]["content"]
        assert "private coffee request" not in facts
        assert '"lat"' not in facts and '"lon"' not in facts
        answer = {"items": [{"id": recommendations[0].poi.id,
                             "why_id": "route_category", "action_id": "category_activity"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    monkeypatch.setattr("app.generation.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    config = replace(settings, llm_api_key="test", llm_base_url="https://llm.example/v1")
    assert asyncio.run(enhance(recommendations, "en", config)) is True
    assert recommendations[0].what_to_do == "Stop for a drink and a break."


def test_embedding_index_reuses_unchanged_vectors(tmp_path, monkeypatch):
    _, db = prepared_client(tmp_path)
    original_client = httpx.AsyncClient
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload["input"])
        vectors = []
        for index, item in enumerate(payload["input"]):
            vectors.append({"index": index, "embedding": [1.0, 0.0] if "cafe" in item.lower() else [0.0, 1.0]})
        return httpx.Response(200, json={"data": vectors})

    monkeypatch.setattr("app.embeddings.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    config = replace(settings, llm_api_key="test", embedding_dimensions=2, embedding_model="test-embed")
    pois = db.all_pois()
    assert asyncio.run(ensure_index(db, pois, config)) == 3
    assert asyncio.run(ensure_index(db, pois, config)) == 0
    scores = asyncio.run(semantic_scores(db, pois, "cafe", config))
    assert scores["node/1"] > scores["node/2"]
    assert len(calls) == 2  # one corpus batch, one query


def test_pedestrian_matrix_uses_network_distance_and_unreachable(monkeypatch):
    original_client = httpx.AsyncClient
    def handler(request):
        body = json.loads(request.content)
        assert body["costing"] == "pedestrian"
        return httpx.Response(200, json={"sources_to_targets": [[
            {"time": 679, "distance": 0.94}, {"time": None, "distance": None}]]})
    monkeypatch.setattr("app.routing.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    target = [{"id": "one", "lat": 51.13, "lon": 71.43},
              {"id": "two", "lat": 51.14, "lon": 71.44}]
    routes = asyncio.run(pedestrian_matrix([(51.12, 71.42)], target))
    assert routes == {"one": [(940, 679)], "two": [None]}


def test_group_routing_is_batched_below_public_matrix_limit(monkeypatch):
    original_client = httpx.AsyncClient
    batches = []
    def handler(request):
        body = json.loads(request.content)
        batches.append(len(body["targets"]))
        assert len(body["sources"]) * len(body["targets"]) <= 90
        rows = [[{"time": 60, "distance": 0.1} for _ in body["targets"]]
                for _ in body["sources"]]
        return httpx.Response(200, json={"sources_to_targets": rows})
    monkeypatch.setattr("app.routing.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    targets = [{"id": str(i), "lat": 51.13, "lon": 71.43} for i in range(40)]
    result = asyncio.run(pedestrian_matrix([(51.12, 71.42)] * 3, targets))
    assert batches == [30, 10]
    assert len(result) == 40 and all(len(value) == 3 for value in result.values())


def test_routing_outage_returns_503_without_straight_line_fallback(tmp_path, monkeypatch):
    client, _ = prepared_client(tmp_path)
    async def unavailable(origins, targets, config):
        raise RoutingError("routing unavailable")
    monkeypatch.setattr("app.main.pedestrian_matrix", unavailable)
    with client:
        response = client.post("/v1/recommendations", json={"lat": 51.09, "lon": 71.4,
                                                             "query": "coffee"})
    assert response.status_code == 503


def test_llm_cannot_publish_unverified_claim(tmp_path, monkeypatch):
    _, db = prepared_client(tmp_path)
    pois = db.all_pois()
    recommendations, _, _ = rank(pois, RecommendRequest(lat=51.09, lon=71.40, language="en"),
                                  {poi["id"]: [(100, 90)] for poi in pois})
    before = [(rec.why, rec.what_to_do) for rec in recommendations]
    answer = {"items": [{"id": rec.poi.id, "why_id": "route_category",
                         "action_id": "category_activity", "why": "Free concert tonight"}
                        for rec in recommendations]}
    original_client = httpx.AsyncClient
    monkeypatch.setattr("app.generation.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(
                            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})),
                            **kwargs))
    config = replace(settings, llm_api_key="test")
    assert asyncio.run(enhance(recommendations, "en", config)) is False
    assert [(rec.why, rec.what_to_do) for rec in recommendations] == before


def test_named_place_overrides_device_location_and_is_cached(tmp_path, monkeypatch):
    client, db = prepared_client(tmp_path)
    assert mentioned_place("Я у здания Экспо 2017, хочу гулять") == "Экспо 2017"
    assert mentioned_place("Я сейчас возле Mega Silk Way, хочу гулять") == "Mega Silk Way"
    assert mentioned_place("Я возле Mega Silk Way и хочу гулять") == "Mega Silk Way"
    assert mentioned_place("Еду с ребёнком — где рядом есть площадки?") is None
    original_client = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(str(request.url))
        assert request.url.params["q"] == "Экспо 2017"
        return httpx.Response(200, json=[{"display_name": "ЭКСПО-2017, Астана, Казахстан",
                                          "lat": "51.0920974", "lon": "71.4146255",
                                          "osm_type": "way", "osm_id": 123}])
    monkeypatch.setattr("app.geocoding.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    payload = {"query": "Я у здания Экспо 2017, хочу гулять", "lat": 51.20, "lon": 71.55}
    with client:
        first = client.post("/v1/recommendations", json=payload)
        second = client.post("/v1/recommendations", json={"query": payload["query"]})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(calls) == 1
    assert first.json()["context_used"]["origin"]["lat"] == 51.0920974
    assert second.json()["context_used"]["origin"]["source"] == "cached_osm_geocoder"


def test_location_requires_context_and_resolves_local_name(tmp_path):
    client, _ = prepared_client(tmp_path)
    with client:
        local = client.post("/v1/recommendations", json={"query": "Я сейчас возле Cafe One, хочу кофе"})
        follow_up = client.post("/v1/recommendations", json={"query": "я сейчас там, хочу кофе",
                                                           "reference_place": "Cafe One"})
        missing = client.post("/v1/recommendations", json={"query": "я сейчас там, хочу кофе"})
        device = client.post("/v1/recommendations", json={"query": "хочу кофе", "lat": 51.09, "lon": 71.4})
        absent = client.post("/v1/recommendations", json={"query": "хочу кофе"})
    assert local.status_code == 200 and local.json()["context_used"]["origin"]["source"] == "local_osm"
    assert follow_up.status_code == 200 and follow_up.json()["context_used"]["origin"]["resolved_from"] == "reference_place"
    assert missing.status_code == 422
    assert device.status_code == 200 and device.json()["context_used"]["origin"]["source"] == "device_location"
    assert absent.status_code == 422


def test_unknown_explicit_place_does_not_use_device_coordinates(tmp_path, monkeypatch):
    client, _ = prepared_client(tmp_path)
    async def not_found(name, language, db, config):
        raise LocationError("place not found", 404)
    monkeypatch.setattr("app.geocoding._external_place", not_found)
    with client:
        response = client.post("/v1/recommendations", json={
            "query": "Я возле Несуществующего здания, хочу гулять",
            "lat": 51.09, "lon": 71.40,
        })
    assert response.status_code == 404
