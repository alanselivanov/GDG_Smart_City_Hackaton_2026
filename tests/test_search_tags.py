import asyncio
import json
from dataclasses import replace
from unittest.mock import patch

import httpx

from app.config import settings
from app.search_tags import cuisine_confirmed, plan_search, search_queries
from app.twogis import search_plan


def test_ai_tags_drive_a_specific_catalog_search():
    sent = []
    real_client = httpx.AsyncClient

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps({"tags": ["food", "cuisine:korean"]})}}]})

    with patch("app.search_tags.httpx.AsyncClient",
               side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)):
        tags = asyncio.run(plan_search("Я хочу поесть корейскую кухню",
                                       replace(settings, llm_api_key="test-key")))

    assert tags.method == "ai_tags"
    assert search_queries("Я хочу поесть корейскую кухню", tags) == ["корейская кухня"]
    assert search_plan("корейская кухня") == ("корейская кухня", 3000, "food")
    assert sent[0]["messages"][1]["content"] == "Я хочу поесть корейскую кухню"


def test_missing_model_tag_cannot_discard_explicit_cuisine():
    real_client = httpx.AsyncClient

    def handler(_request):
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps({"tags": ["food", "cuisine:italian"]})}}]})

    with patch("app.search_tags.httpx.AsyncClient",
               side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)):
        tags = asyncio.run(plan_search("Хочу корейскую кухню",
                                       replace(settings, llm_api_key="test-key")))
    assert "cuisine:korean" in tags.tags
    assert "cuisine:italian" not in tags.tags


def test_cuisine_needs_a_catalog_fact():
    place = {"tags": {}, "attribute_groups": [{"name": "Ресторан / Кафе", "attributes": [
        {"name": "Корейская кухня", "tag": "food_service_food_korean"}]}]}
    assert cuisine_confirmed(place, "cuisine:korean")
    assert not cuisine_confirmed({"tags": {}, "attribute_groups": [], "name": "Korean House"},
                                 "cuisine:korean")
