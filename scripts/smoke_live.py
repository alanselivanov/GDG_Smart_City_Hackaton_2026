"""Small real-provider smoke check. Requires configured .env and an OSM snapshot."""
from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


def main() -> None:
    with TestClient(create_app(replace(settings, auto_refresh=False))) as client:
        for path, payload in (
            ("/v1/recommendations", {"lat": 51.128, "lon": 71.43,
                                      "query": "кофе рядом", "language": "ru", "limit": 2}),
            ("/v1/group/recommendations", {"query": "museum or culture", "language": "en",
                                           "participants": [
                                               {"lat": 51.128, "lon": 71.43, "interests": ["museum"]},
                                               {"lat": 51.129, "lon": 71.431, "interests": ["culture"]},
                                               {"lat": 51.13, "lon": 71.432, "interests": ["museum"]}]}),
        ):
            response = client.post(path, json=payload)
            print(path, "HTTP", response.status_code)
            if response.status_code != 200:
                print("error", response.json().get("detail", "unknown"))
                continue
            body = response.json()
            if body["source"] == "2gis":
                print("source", "2gis", "fallback", body["context_used"]["fallback_used"])
                print("places", [(item["id"], item["name"], item["distance_m"])
                                 for item in body["recommendations"]])
                continue
            print("retrieval", body["context_used"]["retrieval_method"],
                  "routing", body["context_used"]["distance_method"],
                  "generation", body["generated_with"])
            print("places", [(item["poi"]["id"], item["walking_seconds"], item["distance_m"])
                             for item in body["recommendations"]])


if __name__ == "__main__":
    main()
