"""Compare separate live 2GIS and OSM recommendations for hackathon examples.

From the repository root: python -m scripts.compare_poi_sources --scenario walk
Use --scenario all for three queries (three 2GIS Places API calls).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace

import httpx

from app.config import settings
from app.db import Database
from app.main import create_app


SCENARIOS = {
    "walk": {
        "query": "Я сейчас возле Mega Silk Way, хочу прогуляться 30–60 минут — что посоветуете?",
        "lat": 51.0890897, "lon": 71.4073303, "language": "ru",
    },
    "coffee": {
        "query": "Хочу тихое место с кофе и розеткой недалеко от меня.",
        "lat": 51.0890897, "lon": 71.4073303, "language": "ru",
    },
    "child": {
        "query": "Еду с ребёнком — где рядом есть детские площадки или музей с интерактивами?",
        "lat": 51.0890897, "lon": 71.4073303, "language": "ru",
    },
}


def show(label: str, response) -> None:
    print(f"\n{label}: HTTP {response.status_code}")
    data = response.json()
    if response.status_code != 200:
        print("  Ошибка:", data.get("detail", "неизвестная ошибка"))
        return
    if label == "2GIS":
        context = data["context_used"]
        print(f"  Поиск: {context['search_query']!r}; радиус {context['radius_m']} м; "
              f"страница {context['page']}, размер {context['page_size']}")
        for number, poi in enumerate(data["recommendations"], 1):
            print(f"  {number}. {poi['name']} (2GIS ID {poi['id']}, ~{poi['distance_m']} м)")
            if poi["object_type"]:
                subtype = f"/{poi['object_subtype']}" if poi["object_subtype"] else ""
                print(f"     Тип: {poi['object_type']}{subtype}")
            if poi["rubrics"]:
                print(f"     Рубрики: {', '.join(poi['rubrics'])}")
            print(f"     Описание: {poi['description'] or 'не указано'}")
            print(f"     Рейтинг: {poi['rating'] if poi['rating'] is not None else 'не указан'}; "
                  f"отзывов: {poi['review_count'] if poi['review_count'] is not None else 'не указано'}; "
                  f"оценок: {poi['rating_count'] if poi['rating_count'] is not None else 'не указано'}")
    else:
        for number, recommendation in enumerate(data["recommendations"], 1):
            poi = recommendation["poi"]
            print(f"  {number}. {poi['name']} ({poi['id']}, "
                  f"{recommendation['distance_m']} м пешком)")
            print(f"     Описание: {poi['description'] or 'не указано'}")
            print(f"     Почему: {recommendation['why']}")
    if not data["recommendations"]:
        print("  POI не найдены")
    else:
        described = sum(bool(item["description"] if label == "2GIS" else item["poi"]["description"])
                        for item in data["recommendations"])
        print(f"  С описанием: {described}/{len(data['recommendations'])}")


async def compare(selected: dict) -> None:
    config = replace(settings, auto_refresh=False)
    Database(config.database_path).init()
    app = create_app(config)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://local", timeout=120) as client:
        for name, payload in selected.items():
            print(f"\n=== {name}: {payload['query']} ===")
            print(f"Координаты пользователя: {payload['lat']}, {payload['lon']}")
            show("2GIS", await client.post("/v1/2gis/recommendations", json=payload))
            show("OSM", await client.post("/v1/osm/recommendations", json={**payload, "limit": 3}))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="walk")
    args = parser.parse_args()
    selected = SCENARIOS if args.scenario == "all" else {args.scenario: SCENARIOS[args.scenario]}
    asyncio.run(compare(selected))


if __name__ == "__main__":
    main()
