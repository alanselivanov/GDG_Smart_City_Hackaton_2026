"""Provider dispatch tests; all external services are mocked."""
import asyncio
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx

from app.config import settings
from app.db import Database
from app.ingest import normalize_element
from app.main import create_app


class RecommendationFallbackTests(unittest.TestCase):
    def call(self, provider_reply, *, path="/v1/recommendations", payload=None, key="test-key",
             with_osm=True):
        payload = payload or {"query": "кофе рядом на 30 минут", "lat": 51.09, "lon": 71.4}
        events = []
        real_client = httpx.AsyncClient
        original_all_pois = Database.all_pois

        def provider(request):
            events.append("2gis")
            self.assertEqual(request.url.path, "/3.0/items")
            self.assertEqual(request.url.params["page"], "1")
            self.assertEqual(request.url.params["page_size"], "10")
            if isinstance(provider_reply, Exception):
                raise provider_reply
            return provider_reply

        def read_osm(db):
            events.append("osm")
            return original_all_pois(db)

        with TemporaryDirectory() as tmp:
            config = replace(settings, database_path=Path(tmp) / "pois.sqlite3",
                             auto_refresh=False, llm_api_key="", twogis_api_key=key)
            db = Database(config.database_path)
            db.init()
            if with_osm:
                db.upsert_pois([normalize_element({
                    "type": "node", "id": 1, "lat": 51.0901, "lon": 71.4001,
                    "tags": {"name": "OSM cafe", "amenity": "cafe", "opening_hours": "24/7"},
                })])

            async def call_endpoint():
                async with real_client(transport=httpx.ASGITransport(app=create_app(config)),
                                       base_url="http://local") as client:
                    return await client.post(path, json=payload)

            with (patch("app.twogis.httpx.AsyncClient",
                        side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(provider), **kwargs)),
                  patch.object(Database, "all_pois", read_osm),
                  patch("app.main.semantic_scores", AsyncMock(return_value={"node/1": 0.8})) as scores,
                  patch("app.main.pedestrian_matrix", AsyncMock(return_value={"node/1": [(20, 15)]})) as routes,
                  patch("app.main.enhance", AsyncMock(return_value=False))):
                response = asyncio.run(call_endpoint())
            return response, events, scores.await_count, routes.await_count

    def test_success_without_description_does_not_read_osm_or_route(self):
        reply = httpx.Response(200, json={"meta": {"code": 200}, "result": {
            "total": 30,
            "items": [{"id": str(i), "name": f"2GIS cafe {i}",
                       "point": {"lat": 51.0901, "lon": 71.4001}} for i in range(10)],
        }})
        response, events, scores, routes = self.call(reply, with_osm=False)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["source"], "2gis")
        self.assertEqual(len(body["recommendations"]), 10)
        self.assertIsNone(body["recommendations"][0]["description"])
        self.assertFalse(body["context_used"]["fallback_used"])
        self.assertEqual(events, ["2gis"])
        self.assertEqual((scores, routes), (0, 0))

        response, events, _, _ = self.call(reply, payload={
            "query": "кофе рядом", "lat": 51.09, "lon": 71.4, "limit": 1,
        })
        self.assertEqual(len(response.json()["recommendations"]), 1)
        self.assertEqual(events, ["2gis"])

    def test_empty_or_unusable_results_fall_back_to_local_osm(self):
        replies = [
            httpx.Response(200, json={"meta": {"code": 404}}),
            httpx.Response(200, json={"meta": {"code": 200}, "result": {"total": 0, "items": []}}),
            httpx.Response(200, json={"meta": {"code": 200}, "result": {
                "total": 1, "items": [{"id": "bad", "name": "No coordinates"}],
            }}),
        ]
        for reply in replies:
            with self.subTest(reply=reply.json()):
                response, events, _, _ = self.call(reply)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["context_used"]["provider"], "osm")
                self.assertEqual(body["context_used"]["fallback_reason"], "2gis_empty")
                self.assertEqual(body["context_used"]["time_budget_minutes"], 30)
                self.assertEqual(body["recommendations"][0]["poi"]["id"], "node/1")
                self.assertEqual(events, ["2gis", "osm"])

    def test_errors_timeout_and_invalid_responses_fall_back(self):
        replies = [httpx.Response(code) for code in (401, 403, 429, 500, 503)] + [
            httpx.ReadTimeout("test timeout"), httpx.ConnectError("test connection failure"),
            httpx.Response(200, text="not JSON"),
            httpx.Response(200, json={"meta": {"code": 200}, "result": {}}),
        ]
        for reply in replies:
            with self.subTest(reply=reply):
                response, events, _, _ = self.call(reply)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()["context_used"]["fallback_used"])
                self.assertEqual(response.json()["context_used"]["fallback_reason"], "2gis_unavailable")
                self.assertEqual(events, ["2gis", "osm"])

    def test_missing_key_uses_local_osm(self):
        response, events, _, _ = self.call(None, key="")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["context_used"]["provider"], "osm")
        self.assertEqual(events, ["osm"])

    def test_both_providers_empty_reports_unavailable(self):
        reply = httpx.Response(200, json={"meta": {"code": 404}})
        response, events, _, _ = self.call(reply, with_osm=False)
        self.assertEqual(response.status_code, 503)
        self.assertIn("POI data unavailable", response.json()["detail"])
        self.assertEqual(events, ["2gis", "osm"])

    def test_explicit_osm_comparison_does_not_call_2gis(self):
        response, events, _, _ = self.call(None, path="/v1/osm/recommendations")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotEqual(response.json()["source"], "2gis")
        self.assertEqual(events, ["osm"])


if __name__ == "__main__":
    unittest.main()
