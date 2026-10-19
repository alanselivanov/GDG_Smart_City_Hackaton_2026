"""Pedestrian travel times and distances from the Valhalla OSM road graph."""
from __future__ import annotations

import asyncio
import math

import httpx

from app.config import Settings, settings
from app.recommend import distance_m


class RoutingError(Exception):
    pass


def estimated_pedestrian_matrix(origins: list[tuple[float, float]], targets: list[dict]
                                ) -> dict[str, list[tuple[int, int]]]:
    """Conservative, explicitly labelled backup when the road router is down.

    This must never be used for the airport deadline calculation.
    """
    result = {}
    for poi in targets:
        values = []
        for lat, lon in origins:
            metres = max(1, math.ceil(distance_m(lat, lon, poi["lat"], poi["lon"]) * 1.45))
            seconds = math.ceil(metres / 1.15)
            values.append((metres, seconds))
        result[poi["id"]] = values
    return result


async def pedestrian_matrix(origins: list[tuple[float, float]], targets: list[dict],
                            config: Settings = settings) -> dict[str, list[tuple[int, int] | None]]:
    if not targets:
        return {}
    if not origins:
        raise RoutingError("At least one origin is required")
    result = {}
    batch_size = max(1, 90 // len(origins))
    for start in range(0, len(targets), batch_size):
        result.update(await _matrix_batch(origins, targets[start:start + batch_size], config, "pedestrian"))
    return result


async def airport_transfers(pois: list[dict], lat: float, lon: float, mode: str,
                            config: Settings = settings) -> dict[str, tuple[int, int] | None]:
    """Network distance and time from each POI to a sourced airport road-access point."""
    if not pois:
        return {}
    if mode not in {"auto", "pedestrian"}:
        raise RoutingError("Unsupported airport transfer mode")
    result: dict[str, tuple[int, int] | None] = {}
    for start in range(0, len(pois), 90):
        batch = pois[start:start + 90]
        routes = await _matrix_batch(
            [(poi["lat"], poi["lon"]) for poi in batch],
            [{"id": "airport", "lat": lat, "lon": lon}], config, mode,
        )
        result.update({poi["id"]: routes["airport"][index] for index, poi in enumerate(batch)})
    return result


async def _matrix_batch(origins: list[tuple[float, float]], targets: list[dict],
                        config: Settings, costing: str) -> dict[str, list[tuple[int, int] | None]]:
    payload = {"sources": [{"lat": lat, "lon": lon} for lat, lon in origins],
               "targets": [{"lat": poi["lat"], "lon": poi["lon"]} for poi in targets],
               "costing": costing, "units": "kilometers"}
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
        raise RoutingError(f"Routing failed: {type(exc).__name__}") from exc
