"""Pedestrian travel times and distances from the Valhalla OSM road graph."""
from __future__ import annotations

import asyncio
import math

import httpx

from app.config import Settings, settings


class RoutingError(Exception):
    pass


async def pedestrian_matrix(origins: list[tuple[float, float]], targets: list[dict],
                            config: Settings = settings) -> dict[str, list[tuple[int, int] | None]]:
    if not targets:
        return {}
    if not origins:
        raise RoutingError("At least one origin is required")
    result = {}
    batch_size = max(1, 90 // len(origins))
    for start in range(0, len(targets), batch_size):
        result.update(await _pedestrian_matrix_batch(origins, targets[start:start + batch_size], config))
    return result


async def _pedestrian_matrix_batch(origins: list[tuple[float, float]], targets: list[dict],
                                   config: Settings) -> dict[str, list[tuple[int, int] | None]]:
    payload = {"sources": [{"lat": lat, "lon": lon} for lat, lon in origins],
               "targets": [{"lat": poi["lat"], "lon": poi["lon"]} for poi in targets],
               "costing": "pedestrian", "units": "kilometers"}
    try:
        async with httpx.AsyncClient(timeout=config.routing_timeout_seconds) as client:
            for attempt in range(2):
                response = await client.post(config.routing_url.rstrip("/") + "/sources_to_targets", json=payload)
                if response.status_code in {502, 503, 504} and attempt == 0:
                    await asyncio.sleep(1)
                    continue
                response.raise_for_status()
                data = response.json()
                break
            if data.get("units") not in (None, "kilometers"):
                raise RoutingError("Routing service returned unexpected distance units")
            rows = data["sources_to_targets"]
        if len(rows) != len(origins) or any(len(row) != len(targets) for row in rows):
            raise RoutingError("Routing service returned an incomplete matrix")
        result = {}
        for j, poi in enumerate(targets):
            values = []
            for i, row in enumerate(rows):
                cell = row[j]
                if cell is None or cell.get("time") is None or cell.get("distance") is None:
                    values.append(None)
                    continue
                if cell.get("from_index", i) != i or cell.get("to_index", j) != j:
                    raise RoutingError("Routing service returned misordered results")
                seconds, kilometers = cell["time"], cell["distance"]
                if not all(isinstance(x, (float, int)) and math.isfinite(x) and x >= 0
                           for x in (seconds, kilometers)):
                    raise RoutingError("Routing service returned an invalid route")
                values.append((round(kilometers * 1000), round(seconds)))
            result[poi["id"]] = values
        return result
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RoutingError(f"Pedestrian routing failed: {type(exc).__name__}") from exc
