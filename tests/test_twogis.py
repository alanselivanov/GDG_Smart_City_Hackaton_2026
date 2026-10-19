import asyncio
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from app.config import settings
from app.main import create_app


class TwoGisNearbyTests(unittest.TestCase):
    def test_kazakh_answer_uses_same_catalog_and_labels_russian_facts(self):
        from app.models import TwoGisNearbyRequest
        from app.twogis import as_candidate, nearby

        def handler(request):
            self.assertEqual(request.url.params["locale"], "ru_KZ")
            return httpx.Response(200, json={"meta": {"code": 200}, "result": {
                "total": 1, "items": [{"id": "123", "name": "Монумент",
                    "point": {"lat": 51.09, "lon": 71.41},
                    "rubrics": [{"name": "Памятник"}],
                    "description": "Городской памятник"}],
            }})

        real_client = httpx.AsyncClient

        def fake_client(**kwargs):
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        config = replace(settings, twogis_api_key="test-key")
        request = TwoGisNearbyRequest(query="памятник", lat=51.09, lon=71.41, language="kk")
        with patch("app.twogis.httpx.AsyncClient", fake_client):
            response = asyncio.run(nearby(request, config))
        self.assertEqual(response.context_used["catalog_locale"], "ru_KZ")
        self.assertEqual(len(response.recommendations), 1)
        poi = response.recommendations[0]
        self.assertEqual(poi.attributes_language, "ru")
        candidate = as_candidate(poi, "landmark", "kk")
        self.assertEqual(candidate["tags"]["description:ru"], "Городской памятник")
        self.assertNotIn("description:kk", candidate["tags"])

    def test_one_page_ten_places_without_osm_data_or_extra_requests(self):
        requests = []

        def handler(request):
            requests.append(request)
            params = request.url.params
            self.assertEqual(request.url.path, "/3.0/items")
            self.assertEqual(params["q"], "парк")
            self.assertEqual(params["point"], "71.4073303,51.0890897")
            self.assertEqual(params["radius"], "3000")
            self.assertEqual(params["page"], "1")
            self.assertEqual(params["page_size"], "10")
            self.assertEqual(params["sort"], "distance")
            self.assertEqual(params["type"], "adm_div.place,attraction")
            self.assertEqual(params["rubric_id"], "168")
            self.assertEqual(params["region_id"], "68")
            self.assertEqual(params["locale"], "ru_KZ")
            self.assertIn("items.description", params["fields"])
            self.assertIn("items.reviews", params["fields"])
            self.assertIn("items.attribute_groups", params["fields"])
            return httpx.Response(200, json={"meta": {"code": 200}, "result": {
                "total": 30,
                "items": [{"id": str(i), "name": f"Park {i}",
                           "point": {"lat": 51.0891, "lon": 71.4074},
                           "description": "Зелёная зона" if i == 0 else None,
                           "reviews": {"general_rating": 4.5, "general_review_count": 12}}
                          for i in range(10)],
            }})

        real_client = httpx.AsyncClient

        def fake_client(**kwargs):
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        with TemporaryDirectory() as tmp:
            config = replace(settings, database_path=Path(tmp) / "empty.sqlite3",
                             auto_refresh=False, twogis_api_key="test-key")
            app = create_app(config)
            async def call_api():
                transport = httpx.ASGITransport(app=app)
                async with real_client(transport=transport, base_url="http://local") as client:
                    return await client.post("/v1/2gis/recommendations", json={
                        "query": "Я возле Mega Silk Way, хочу прогуляться",
                        "lat": 51.0890897, "lon": 71.4073303,
                    })
            with patch("app.twogis.httpx.AsyncClient", fake_client):
                response = asyncio.run(call_api())
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["source"], "2gis")
            self.assertEqual(len(data["recommendations"]), 10)
            self.assertEqual(data["total_found"], 30)
            self.assertEqual(data["recommendations"][0]["description"], "Зелёная зона")
            self.assertEqual(data["recommendations"][0]["rating"], 4.5)
            self.assertEqual(len(requests), 1)

    def test_intent_mapping_and_missing_key(self):
        from app.twogis import search_plan
        self.assertEqual(search_plan("кофе рядом"), ("кафе", 1500, "cafe"))
        self.assertEqual(search_plan("кафе с детским меню"), ("кафе", 1500, "cafe"))
        self.assertEqual(search_plan("с ребёнком"), ("детская площадка", 3000, "family"))
        self.assertEqual(search_plan("музей"), ("музей", 3000, "museum"))
        self.assertEqual(search_plan("музей с ребёнком"), ("музей", 3000, "museum"))
        self.assertEqual(search_plan("погулять"), ("парк", 3000, "park"))
        with TemporaryDirectory() as tmp:
            config = replace(settings, database_path=Path(tmp) / "empty.sqlite3",
                             auto_refresh=False, twogis_api_key="")
            async def call_api():
                transport = httpx.ASGITransport(app=create_app(config))
                async with httpx.AsyncClient(transport=transport, base_url="http://local") as client:
                    return await client.post("/v1/2gis/recommendations", json={
                        "query": "кофе рядом", "lat": 51.09, "lon": 71.4,
                    })
            response = asyncio.run(call_api())
            self.assertEqual(response.status_code, 503)
            self.assertIn("2GIS_API_KEY", response.json()["detail"])

    def test_dining_search_keeps_more_than_ten_nearby_cafes(self):
        from app.models import TwoGisNearbyRequest
        from app.twogis import nearby

        requested_pages = []

        def handler(request):
            self.assertEqual(request.url.params["q"], "кафе")
            self.assertEqual(request.url.params["page_size"], "10")
            page = int(request.url.params["page"])
            requested_pages.append(page)
            start = (page - 1) * 10
            return httpx.Response(200, json={"meta": {"code": 200}, "result": {
                "total": 15, "items": [{"id": str(i), "name": f"Cafe {i}",
                    "point": {"lat": 51.09, "lon": 71.41}} for i in range(start, min(start + 10, 15))],
            }})

        real_client = httpx.AsyncClient
        with patch("app.twogis.httpx.AsyncClient", side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs)):
            result = asyncio.run(nearby(TwoGisNearbyRequest(
                query="кафе", lat=51.09, lon=71.41),
                replace(settings, twogis_api_key="test-key")))
        self.assertEqual(len(result.recommendations), 15)
        self.assertEqual(result.context_used["page_size"], 10)
        self.assertEqual(requested_pages, [1, 2])

    def test_unnamed_playground_label_is_not_none(self):
        from app.models import TwoGisNearbyRequest
        from app.twogis import _poi
        request = TwoGisNearbyRequest(query="с ребёнком", lat=51.09, lon=71.4)
        item = {"id": "123", "name": None, "point": {"lat": 51.09, "lon": 71.4}}
        poi = _poi(item, request, 3000, "family")
        self.assertEqual(poi.name, "Детская площадка")

    def test_all_named_info_attributes_are_parsed_without_description(self):
        from app.models import TwoGisNearbyRequest
        from app.twogis import _poi, as_candidate

        request = TwoGisNearbyRequest(query="кафе", lat=51.101294, lon=71.41539)
        item = {"id": "70000001066682180", "name": "Coffee BOOM", "type": "branch",
                "point": {"lat": 51.101294, "lon": 71.41539}, "rubrics": [{"name": "Кафе"}],
                "attribute_groups": [
                    {"name": "Премия 2ГИС", "attributes": [
                        {"name": "Лучшая кофейня 2022", "tag": "awards_awards_thebestcoffeeshop", "id": 1}]},
                    {"name": "Ресторан / Кафе", "attributes": [
                        {"name": "Чек 7000 ₸", "tag": "food_service_avg_price"},
                        {"name": "Детское меню", "tag": "food_kids_menu"},
                        {"name": "Можно с ноутбуком", "tag": "food_service_cafe_working"}]},
                    {"name": "Напитки", "attributes": [{"name": "Кофе с собой", "tag": "coffee_takeaway"}]},
                ]}
        poi = _poi(item, request, 1500, "cafe")
        self.assertIsNone(poi.description)
        self.assertEqual(len(poi.attribute_groups), 3)
        self.assertEqual(sum(len(group.attributes) for group in poi.attribute_groups), 5)
        adapted = as_candidate(poi, "cafe", "ru")
        self.assertEqual(adapted["attribute_groups"][1]["attributes"][1]["name"], "Детское меню")
        self.assertEqual(adapted["attributes_language"], "ru")
        self.assertEqual(adapted["source_url"], "https://2gis.kz/astana/firm/70000001066682180")
        self.assertEqual(poi.source_url, adapted["source_url"])

    def test_same_name_park_prefers_area_card_with_rating(self):
        from app.models import TwoGisNearbyRequest
        from app.twogis import _poi, _prefer_park_places

        request = TwoGisNearbyRequest(query="погулять", lat=51.0890897, lon=71.4073303)
        attraction = _poi({"id": "70030076302829268", "name": "ЭКСПО-парк",
                           "type": "attraction", "point": {"lat": 51.095657, "lon": 71.418511},
                           "reviews": {"items": [{"tag": "2gis_reviews"}]}}, request, 3000, "park")
        place = _poi({"id": "70030076138264995", "name": "ЭКСПО-парк",
                      "type": "adm_div", "subtype": "place",
                      "point": {"lat": 51.093772, "lon": 71.417537},
                      "reviews": {"general_rating": 4.9, "general_review_count": 926,
                                  "general_review_count_with_stars": 16763}}, request, 3000, "park")
        self.assertIsNotNone(attraction)
        self.assertIsNotNone(place)
        chosen = _prefer_park_places([attraction, place])
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].id, "70030076138264995")
        self.assertEqual(chosen[0].rating, 4.9)
        self.assertEqual(chosen[0].review_count, 926)
        self.assertEqual(chosen[0].rating_count, 16763)

    def test_schedule_is_checked_only_when_week_is_complete(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.twogis import schedule_to_opening_hours
        from app.recommend import opening_status

        schedule = {day: {"working_hours": [{"from": "09:00", "to": "18:00"}]}
                    for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}
        hours = schedule_to_opening_hours(schedule)
        monday = datetime(2026, 10, 19, 10, 0, tzinfo=ZoneInfo("Asia/Almaty"))
        self.assertEqual(opening_status(hours, monday, 30), "open")
        self.assertEqual(opening_status(hours, monday.replace(hour=20), 30), "closed")
        del schedule["Sun"]
        self.assertIsNone(schedule_to_opening_hours(schedule))

    def test_price_detection_requires_explicit_tenge_budget(self):
        from app.attributes import average_check, price_ceiling
        self.assertEqual(price_ceiling("кафе до 5 000 ₸"), 5000)
        self.assertEqual(price_ceiling("cafe under 5000 KZT"), 5000)
        self.assertIsNone(price_ceiling("до 2 часов"))
        self.assertEqual(average_check({"attribute_groups": [{"attributes": [
            {"name": "Чек 7000 ₸", "tag": "food_service_avg_price"}]}]}), 7000)


if __name__ == "__main__":
    unittest.main()
