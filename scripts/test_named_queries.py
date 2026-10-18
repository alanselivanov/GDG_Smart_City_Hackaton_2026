"""Run natural-language location examples against a local HTTP server."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx


CASES = [
    {"query": "Я у здании Экспо 2017, хочу что-то необычное на 1–2 часа, пешком.", "language": "ru"},
    {"query": "Я сейчас возле Mega Silk Way, хочу прогуляться 30–60 минут — что посоветуете?", "language": "ru"},
    {"query": "Еду с ребёнком — где рядом есть детские площадки или музей с интерактивами?",
     "language": "ru", "lat": 51.0890897, "lon": 71.4073303},
    {"query": "Я сейчас там, хочу поесть в течение часа.", "language": "ru",
     "reference_place": "Mega Silk Way"},
    {"query": "Я турист, у меня 2 часа перед вылетом. Хочу посмотреть что-то рядом пешком.",
     "language": "ru", "lat": 51.0920974, "lon": 71.4146255},
    {"query": "Я турист, у меня 4 часа перед вылетом. Хочу посмотреть достопримечательности пешком.",
     "language": "ru", "lat": 51.0920974, "lon": 71.4146255},
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    output = Path("data/named_query_results")
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["AUTO_REFRESH"] = "false"
    with (output / "server.log").open("wb") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18766"],
            env=environment, stdout=log, stderr=log,
        )
        try:
            with httpx.Client(timeout=120, trust_env=False) as client:
                for _ in range(80):
                    if server.poll() is not None:
                        raise RuntimeError("Backend failed to start; see server.log")
                    try:
                        if client.get("http://127.0.0.1:18766/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.25)
                else:
                    raise RuntimeError("Backend startup timed out")
                for number, request in enumerate(CASES, 1):
                    response = client.post("http://127.0.0.1:18766/v1/recommendations", json=request)
                    (output / f"request-{number}.json").write_text(
                        json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    (output / f"response-{number}.json").write_bytes(response.content)
                    print(f"\nЗАПРОС {number}: {request['query']}")
                    print(f"HTTP {response.status_code}")
                    body = response.json()
                    if response.status_code != 200:
                        print(f"Ошибка: {body.get('detail')}")
                        continue
                    context = body["context_used"]
                    if body["source"] == "2gis":
                        print("Источник: 2GIS; расстояния по прямой")
                        for poi in body["recommendations"]:
                            print(f"  Место: {poi['name']} (ID {poi['id']}, ~{poi['distance_m']} м)")
                            print(f"  Описание: {poi['description'] or 'не указано'}")
                        continue
                    origin = context["origin"]
                    print(f"Начало: {origin['name'] or 'геолокация устройства'} ({origin['lat']}, {origin['lon']})")
                    print(f"Источник точки: {origin['source']}")
                    print(f"Бюджет времени: {context['time_budget_minutes']} мин")
                    print(f"Текст: {body['generated_with']}")
                    if context.get("flight_plan"):
                        plan = context["flight_plan"]
                        print(f"Вылет: {plan['departure_at']}; запас: {plan['airport_arrival_buffer_minutes']} мин")
                        print(f"Точка аэропорта: {plan['airport_route_reference']['source_url']}")
                    for item in body["recommendations"]:
                        poi = item["poi"]
                        print(f"  Место: {poi['name']}")
                        print(f"  Пешком: {item['distance_m']} м, {item['walking_minutes']} мин ({item['walking_seconds']} с)")
                        print(f"  Время на месте: {item['visit_minutes']} мин")
                        print(f"  Почему: {item['why']}")
                        print(f"  Что делать: {item['what_to_do']}")
                        print(f"  Часы: {item['open_status_reason']}")
                        for missing in item["missing_information"]:
                            print(f"  Не указано: {missing}")
                        if item["airport_transfer_minutes"] is not None:
                            print(f"  До аэропорта: {item['airport_transfer_distance_m']} м, "
                                  f"{item['airport_transfer_minutes']} мин; "
                                  f"выйти до {item['latest_leave_for_airport_at']}")
                        print(f"  OSM: {poi['source_url']}")
                    if not body["recommendations"]:
                        print("Рекомендаций нет")
                    for notice in body["notices"]:
                        print(f"Примечание: {notice}")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    main()
