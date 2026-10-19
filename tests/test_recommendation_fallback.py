"""The primary endpoint always plans routes, time and constraints for both sources."""
import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.db import Database
from app.ingest import normalize_element
from app.main import create_app
from app.recommend import distance_m


class RecommendationPipelineTests(unittest.TestCase):
    def call(self, provider_reply, *, path="/v1/recommendations", payload=None,
             with_osm=True, key="test-key", airport=False):
        payload = dict(payload or {"query": "кофе рядом на 30 минут", "lat": 51.09, "lon": 71.4})
        if "starts_at" not in payload:
            daytime = datetime.now(ZoneInfo("Asia/Almaty")) + timedelta(days=1)
            payload["starts_at"] = daytime.replace(hour=13, minute=0, second=0, microsecond=0).isoformat()
        provider_points = []
        routed_origins = []
        routed_ids = []
        scored_ids = []
        real_client = httpx.AsyncClient

        def provider(request):
            provider_points.append((request.url.params["q"], request.url.params["point"]))
            if isinstance(provider_reply, Exception):
                raise provider_reply
            if callable(provider_reply):
                return provider_reply(request)
            return provider_reply

        async def scores(db, pois, query, config):
            scored_ids.extend(poi["id"] for poi in pois)
            return {poi["id"]: (0.9 if poi["id"].startswith("2gis/") else 0.2) for poi in pois}

        async def routes(origins, pois, config):
            routed_origins.extend(origins)
            routed_ids.extend(poi["id"] for poi in pois)
            return {poi["id"]: [(max(100, round(distance_m(lat, lon, poi["lat"], poi["lon"]))), 300)
                                for lat, lon in origins] for poi in pois}

        async def transfers(pois, lat, lon, mode, config):
            return {poi["id"]: (7000, 600) for poi in pois}

        with TemporaryDirectory() as tmp:
            config = replace(settings, database_path=Path(tmp) / "pois.sqlite3",
                             auto_refresh=False, llm_api_key="", twogis_api_key=key)
            db = Database(config.database_path)
            db.init()
            if with_osm:
                raw = [{"type": "node", "id": 1, "lat": 51.0902, "lon": 71.4002,
                        "tags": {"name": "OSM cafe", "amenity": "cafe", "opening_hours": "24/7"}},
                       {"type": "node", "id": 2, "lat": 51.089, "lon": 71.407,
                        "tags": {"name": "Mega Silk Way", "shop": "mall"}}]
                db.upsert_pois([normalize_element(item) for item in raw])
            if airport:
                db.save_route_reference("airport", {"lat": 51.027, "lon": 71.460,
                                                    "source_url": "https://www.openstreetmap.org/node/123"})

            async def request_endpoint():
                async with real_client(transport=httpx.ASGITransport(app=create_app(config)),
                                       base_url="http://local") as client:
                    return await client.post(path, json=payload)

            with (patch("app.twogis.httpx.AsyncClient",
                        side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(provider), **kwargs)),
                  patch("app.main.semantic_scores", scores),
                  patch("app.main.pedestrian_matrix", routes),
                  patch("app.main.airport_transfers", transfers),
                  patch("app.main.enhance", AsyncMock(return_value=False))):
                response = asyncio.run(request_endpoint())
        return response, provider_points, routed_origins, routed_ids, scored_ids

    @staticmethod
    def reply(items):
        weekly = {day: {"working_hours": [{"from": "00:00", "to": "24:00"}]}
                  for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}
        items = [{**item, "schedule": item.get("schedule", weekly)} for item in items]
        return httpx.Response(200, json={"meta": {"code": 200},
                                         "result": {"total": len(items), "items": items}})

    def test_2gis_only_uses_full_planner_contract(self):
        items = [{"id": "123", "name": "2GIS cafe", "point": {"lat": 51.091, "lon": 71.401},
                  "description": "Кафе", "rubrics": [{"name": "Кафе"}]}]
        response, points, origins, routed, scored = self.call(self.reply(items), with_osm=False)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["context_used"]["time_budget_minutes"], 30)
        self.assertEqual(body["context_used"]["providers"], ["2gis"])
        self.assertEqual(body["source"], "2GIS")
        self.assertEqual(points, [("кафе", "71.4,51.09")] * 2)
        self.assertEqual(origins, [(51.09, 71.4)])
        self.assertIn("2gis/123", scored)
        self.assertIn("2gis/123", routed)
        item = body["recommendations"][0]
        self.assertEqual(item["poi"]["id"], "2gis/123")
        self.assertEqual(item["poi"]["category"], "cafe")
        self.assertEqual(item["walking_minutes"], 5)
        self.assertLessEqual(item["walking_minutes"] + item["visit_minutes"], 30)
        self.assertEqual(item["open_status"], "open")
        self.assertIn("2GIS", item["why"])
        self.assertTrue(item["what_to_do"])

    def test_query_time_is_used_without_an_explicit_start(self):
        items = [{"id": "breakfast", "name": "Breakfast cafe",
                  "point": {"lat": 51.091, "lon": 71.401},
                  "rubrics": [{"name": "Кафе"}]}]
        response, _, _, _, _ = self.call(self.reply(items), with_osm=True, payload={
            "query": "Кофе возле Mega Silk Way в 9 утра", "lat": 51.09, "lon": 71.4,
            "starts_at": None,
        })
        self.assertEqual(response.status_code, 200, response.text)
        context = response.json()["context_used"]
        self.assertEqual(datetime.fromisoformat(context["starts_at"]).hour, 9)
        self.assertEqual(context["starts_at_source"], "query")
        self.assertEqual(context["origin"]["name"], "Mega Silk Way")

    def test_conflicting_explicit_start_and_query_time_is_rejected(self):
        response, _, _, _, _ = self.call(self.reply([]), payload={
            "query": "Кофе возле Mega Silk Way в 9 утра", "lat": 51.09, "lon": 71.4,
        })
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Время в запросе отличается", response.json()["detail"])

    def test_named_origin_precedes_2gis_and_routing(self):
        items = [{"id": "park", "name": "EXPO park", "point": {"lat": 51.091, "lon": 71.408},
                  "rubrics": [{"name": "Парки"}]}]
        response, points, origins, _, _ = self.call(self.reply(items), payload={
            "query": "Я возле Mega Silk Way, хочу погулять 30–60 минут",
            "lat": 51.20, "lon": 71.55,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["context_used"]["origin"]["name"], "Mega Silk Way")
        self.assertEqual(response.json()["context_used"]["time_budget_minutes"], 60)
        self.assertEqual(points, [("парк", "71.407,51.089"),
                                  ("памятник", "71.407,51.089"),
                                  ("смотровая площадка", "71.407,51.089")])
        self.assertEqual(origins, [(51.089, 71.407)])

    def test_mixed_sources_share_retrieval_and_routing(self):
        items = [{"id": "123", "name": "2GIS cafe", "point": {"lat": 51.091, "lon": 71.401}}]
        response, _, _, routed, scored = self.call(self.reply(items))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["context_used"]["providers"], ["osm", "2gis"])
        self.assertIn("node/1", scored)
        self.assertIn("2gis/123", scored)
        self.assertIn("node/1", routed)
        self.assertIn("2gis/123", routed)

    def test_quiet_and_socket_are_not_claimed_without_evidence(self):
        items = [{"id": "123", "name": "2GIS cafe", "point": {"lat": 51.091, "lon": 71.401}}]
        response, _, _, _, _ = self.call(self.reply(items), with_osm=False, payload={
            "query": "Тихое кофе с розеткой", "lat": 51.09, "lon": 71.4,
        })
        self.assertEqual(response.status_code, 200, response.text)
        missing = " ".join(response.json()["recommendations"][0]["missing_information"])
        self.assertIn("Тишина", missing)
        self.assertIn("розеток", missing)

    def test_info_attributes_change_ranking_and_ground_explanation(self):
        items = [
            {"id": "plain", "name": "Plain cafe", "point": {"lat": 51.091, "lon": 71.401},
             "rubrics": [{"name": "Кафе"}]},
            {"id": "kids", "name": "Coffee BOOM", "point": {"lat": 51.092, "lon": 71.402},
             "rubrics": [{"name": "Кафе"}], "reviews": {"general_rating": 4.7,
                                                      "general_review_count": 25},
             "attribute_groups": [
                 {"name": "Ресторан / Кафе", "attributes": [
                     {"name": "Детское меню", "tag": "food_kids_menu"},
                     {"name": "Можно с ноутбуком", "tag": "food_service_cafe_working"},
                     {"name": "Чек 7000 ₸", "tag": "food_service_avg_price"}]},
                 {"name": "Напитки", "attributes": [
                     {"name": "Кофе с собой", "tag": "coffee_takeaway"}]},
             ]},
        ]
        response, points, _, _, _ = self.call(self.reply(items), with_osm=False, payload={
            "query": "Ищу кафе с детским меню и розеткой", "lat": 51.09, "lon": 71.4,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(points[0][0], "кафе")
        first = response.json()["recommendations"][0]
        self.assertEqual(first["poi"]["id"], "2gis/kids")
        self.assertEqual(len(first["poi"]["attribute_groups"]), 2)
        self.assertEqual(first["poi"]["rating"], 4.7)
        self.assertIn("Детское меню", first["why"])
        self.assertIn("розеток", " ".join(first["missing_information"]))

    def test_empty_poi_search_returns_service_unavailable(self):
        with TemporaryDirectory() as tmp:
            config = replace(settings, database_path=Path(tmp) / "empty.sqlite3", auto_refresh=False)
            Database(config.database_path).init()
            async def search():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(config)),
                                             base_url="http://local") as client:
                    return await client.get("/v1/pois/search", params={"q": "museum"})
            response = asyncio.run(search())
        self.assertEqual(response.status_code, 503)
        self.assertIn("POI data unavailable", response.json()["detail"])

    def test_english_explanation_translates_only_known_attribute_tags(self):
        items = [{"id": "123", "name": "Coffee BOOM", "point": {"lat": 51.091, "lon": 71.401},
                  "rubrics": [{"name": "Кафе"}], "attribute_groups": [
                      {"name": "Ресторан / Кафе", "attributes": [
                          {"name": "Детское меню", "tag": "food_kids_menu"},
                          {"name": "Можно с ноутбуком", "tag": "food_service_cafe_working"},
                          {"name": "Непроверенная услуга", "tag": "unknown_service"}]},
                  ]}]
        response, _, _, _, _ = self.call(self.reply(items), with_osm=False, payload={
            "query": "cafe with kids menu and laptop", "language": "en",
            "lat": 51.09, "lon": 71.4,
        })
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["recommendations"][0]
        self.assertEqual(item["poi"]["attributes_language"], "ru")
        self.assertIn("Children's menu", item["why"])
        self.assertIn("Laptop-friendly", item["why"])
        self.assertNotIn("Непроверенная услуга", item["why"])
        self.assertEqual(item["poi"]["attribute_groups"][0]["attributes"][2]["name"],
                         "Непроверенная услуга")

    def test_known_average_check_above_explicit_budget_is_excluded(self):
        def cafe(identity, check):
            return {"id": identity, "name": f"Cafe {identity}",
                    "point": {"lat": 51.091, "lon": 71.401},
                    "rubrics": [{"name": "Кафе"}], "attribute_groups": [
                        {"name": "Ресторан / Кафе", "attributes": [
                            {"name": f"Чек {check} ₸", "tag": "food_service_avg_price"}]}]}
        response, _, _, routed, _ = self.call(self.reply([cafe("high", 7000), cafe("fit", 3000)]),
                                                with_osm=False, payload={
            "query": "кафе до 5000 ₸", "lat": 51.09, "lon": 71.4,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["poi"]["id"] for item in response.json()["recommendations"]],
                         ["2gis/fit"])
        self.assertEqual(routed, ["2gis/fit"])

    def test_closed_2gis_place_is_filtered(self):
        schedule = {day: {"working_hours": [{"from": "09:00", "to": "10:00"}]}
                    for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}
        items = [{"id": "123", "name": "2GIS cafe", "point": {"lat": 51.091, "lon": 71.401},
                  "schedule": schedule}]
        tomorrow = datetime.now(ZoneInfo("Asia/Almaty")) + timedelta(days=1)
        start = tomorrow.replace(hour=20, minute=0, second=0, microsecond=0)
        response, _, _, routed, _ = self.call(self.reply(items), with_osm=False, payload={
            "query": "Кофе", "lat": 51.09, "lon": 71.4, "starts_at": start.isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("2gis/123", routed)
        self.assertEqual(response.json()["recommendations"], [])

    def test_flight_constraints_apply_to_2gis_candidate(self):
        items = [{"id": "123", "name": "2GIS cafe", "point": {"lat": 51.091, "lon": 71.401}}]
        daytime = (datetime.now(ZoneInfo("Asia/Almaty")) + timedelta(days=1)).replace(
            hour=13, minute=0, second=0, microsecond=0)
        departure = daytime + timedelta(hours=3)
        response, _, _, routed, _ = self.call(self.reply(items), with_osm=False, airport=True,
                                                payload={"query": "Кофе перед вылетом", "lat": 51.09,
                                                         "lon": 71.4, "starts_at": daytime.isoformat(),
                                                         "flight_departure_at": departure.isoformat(),
                                                         "airport_arrival_buffer_minutes": 90})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("2gis/123", routed)
        item = response.json()["recommendations"][0]
        self.assertEqual(item["airport_transfer_minutes"], 10)
        self.assertTrue(item["latest_leave_for_airport_at"])

    def test_family_museum_alternative_is_searched(self):
        def provider(request):
            if request.url.params["q"] == "музей":
                return self.reply([{"id": "museum", "name": "Интерактивный музей",
                                    "point": {"lat": 51.091, "lon": 71.401},
                                    "description": "Интерактивные экспонаты для детей"}])
            return self.reply([{"id": "play", "name": "Детская площадка",
                                "point": {"lat": 51.091, "lon": 71.402}}])
        response, points, _, routed, _ = self.call(provider, with_osm=False, payload={
            "query": "С ребёнком: площадка или интерактивный музей", "lat": 51.09, "lon": 71.4,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([query for query, _ in points], ["детская площадка", "детская площадка", "музей", "музей"])
        self.assertEqual(set(routed), {"2gis/play", "2gis/museum"})
        self.assertIn("museum", {item["poi"]["id"].split("/")[-1]
                                 for item in response.json()["recommendations"]})

    def test_2gis_failure_keeps_osm_planning(self):
        response, points, _, routed, _ = self.call(httpx.ReadTimeout("timeout"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(points), 1)
        self.assertEqual(response.json()["context_used"]["fallback_reason"], "2gis_unavailable")
        self.assertIn("node/1", routed)
        self.assertEqual(response.json()["recommendations"][0]["poi"]["id"], "node/1")

    def test_explicit_cuisine_search_only_routes_confirmed_places(self):
        items = [
            {"id": "generic", "name": "Generic restaurant", "point": {"lat": 51.0901, "lon": 71.4001},
             "rubrics": [{"name": "Рестораны"}]},
            {"id": "korean", "name": "Korean House", "point": {"lat": 51.091, "lon": 71.401},
             "rubrics": [{"name": "Рестораны"}], "attribute_groups": [
                 {"name": "Ресторан / Кафе", "attributes": [
                     {"name": "Корейская кухня", "tag": "food_service_food_korean"}]}]},
        ]
        response, searches, _, routed, _ = self.call(self.reply(items), with_osm=False,
            payload={"query": "Я хочу поесть корейскую кухню", "lat": 51.09, "lon": 71.4})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([query for query, _ in searches], ["корейская кухня"] * 2)
        self.assertEqual(routed, ["2gis/korean"])
        self.assertEqual([item["poi"]["name"] for item in response.json()["recommendations"]],
                         ["Korean House"])

    def test_explicit_osm_endpoint_does_not_call_2gis(self):
        response, points, _, _, _ = self.call(None, path="/v1/osm/recommendations")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(points, [])

    def test_primary_limit_stays_planned_response_limit(self):
        response, _, _, _, _ = self.call(self.reply([]), payload={
            "query": "кофе", "lat": 51.09, "lon": 71.4, "limit": 10,
        })
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
