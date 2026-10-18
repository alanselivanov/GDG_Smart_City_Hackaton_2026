from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, settings
from app.db import Database
from app.embeddings import EmbeddingError, semantic_scores
from app.generation import enhance
from app.geocoding import LocationError, resolve_origin
from app.ingest import IngestError, refresh, refresh_airport_reference
from app.models import (Category, GroupRecommendRequest, Language, PoiOut, PrimaryRecommendRequest, RecommendRequest,
                        RecommendResponse, TwoGisNearbyRequest, TwoGisNearbyResponse)
from app.recommend import (ASTANA_TZ, candidate_pois, display_name, distance_m, effective_max_travel, generic_name,
                           infer_budget, infer_flight_minutes, is_before_flight, localized_description, rank)
from app.routing import RoutingError, airport_transfers, pedestrian_matrix
from app.twogis import TwoGisError, nearby as twogis_nearby


def create_app(config: Settings = settings) -> FastAPI:
    db = Database(config.database_path)
    refresh_lock = asyncio.Lock()
    embedding_lock = asyncio.Lock()
    state: dict[str, str | None] = {"last_refresh_error": None, "last_airport_refresh_error": None}

    async def do_refresh() -> int:
        if refresh_lock.locked():
            raise HTTPException(status_code=409, detail="POI refresh already in progress")
        async with refresh_lock:
            try:
                count = await refresh(db, config)
                state["last_refresh_error"] = None
                return count
            except IngestError as exc:
                state["last_refresh_error"] = str(exc)
                raise

    async def refresh_loop() -> None:
        while True:
            status = db.status()
            last = status["last_success_at"]
            airport_reference = db.route_reference("airport")
            airport_due = (not airport_reference or datetime.now(ASTANA_TZ) -
                           datetime.fromisoformat(airport_reference["fetched_at"]).astimezone(ASTANA_TZ)
                           >= timedelta(hours=config.poi_refresh_hours))
            if airport_due:
                try:
                    await refresh_airport_reference(db, config)
                    state["last_airport_refresh_error"] = None
                except IngestError as exc:
                    state["last_airport_refresh_error"] = str(exc)
            due = (not last or datetime.now(ASTANA_TZ) -
                   datetime.fromisoformat(last).astimezone(ASTANA_TZ)
                   >= timedelta(hours=config.poi_refresh_hours))
            if due:
                try:
                    await do_refresh()
                except (IngestError, HTTPException):
                    pass
            # Recheck hourly so a nearly stale cache is refreshed on time.
            await asyncio.sleep(3600)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init()
        task = asyncio.create_task(refresh_loop()) if config.auto_refresh else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Astana Walks API", version="1.0.0", lifespan=lifespan,
                  description="Nearby 2GIS recommendations with a local OpenStreetMap fallback.")
    origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "X-Admin-Token"])

    @app.get("/health")
    def health():
        status = db.status()
        return {"status": "ready" if status["poi_count"] else "awaiting_poi", **status,
                "last_refresh_error": state["last_refresh_error"],
                "airport_reference": db.route_reference("airport"),
                "last_airport_refresh_error": state["last_airport_refresh_error"]}

    @app.get("/v1/pois", response_model=list[PoiOut])
    def list_pois(lat: float = Query(ge=50.9, le=51.4), lon: float = Query(ge=71, le=71.9),
                  radius_m: int = Query(default=2000, ge=100, le=20000),
                  category: Category | None = None, language: Language = "ru",
                  limit: int = Query(default=30, ge=1, le=100)):
        found = []
        for poi in db.all_pois():
            if category and poi["category"] != category:
                continue
            distance = round(distance_m(lat, lon, poi["lat"], poi["lon"]))
            if distance <= radius_m:
                found.append((distance, poi))
        found.sort(key=lambda item: (item[0], item[1]["id"]))
        return [PoiOut(**{**poi, "name": display_name(poi, language),
                          "name_is_generic": generic_name(poi),
                          "description": localized_description(poi, language), "distance_m": d})
                for d, poi in found[:limit]]

    @app.get("/v1/pois/search", response_model=list[PoiOut])
    async def search_pois(q: str = Query(min_length=2, max_length=100), language: Language = "ru",
                    limit: int = Query(default=10, ge=1, le=30)):
        needle = q.casefold().strip()
        pois = db.all_pois()
        if not pois:
            raise HTTPException(status_code=503, detail="POI data unavailable")
        try:
            async with embedding_lock:
                scores = await semantic_scores(db, pois, needle, config)
        except EmbeddingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        found = sorted(pois, key=lambda poi: -(
            scores[poi["id"]] + (0.3 if any(name.casefold().startswith(needle) for name in poi["names"].values()) else 0)))
        return [PoiOut(**{**poi, "name": display_name(poi, language),
                          "name_is_generic": generic_name(poi),
                          "description": localized_description(poi, language)}) for poi in found[:limit]]

    async def recommend(request: RecommendRequest | GroupRecommendRequest) -> RecommendResponse:
        budget_was_explicit = "time_budget_minutes" in request.model_fields_set
        departure_was_explicit = "flight_departure_at" in request.model_fields_set
        inferred = infer_budget(request.query)
        flight_minutes = infer_flight_minutes(request.query)
        if "time_budget_minutes" not in request.model_fields_set:
            if inferred is not None:
                if not 20 <= inferred <= 360:
                    raise HTTPException(status_code=422, detail="Requested time must be between 20 and 360 minutes")
                request = request.model_copy(update={"time_budget_minutes": inferred})
        now = datetime.now(ASTANA_TZ)
        if request.starts_at and not now - timedelta(minutes=5) <= request.starts_at <= now + timedelta(days=7):
            raise HTTPException(status_code=422, detail="starts_at must be from now to 7 days ahead")
        start = request.starts_at or now
        flight_requested = request.flight_departure_at is not None or is_before_flight(request.query)
        departure_source = None
        if flight_requested:
            if request.flight_departure_at is None:
                if flight_minutes is None and not budget_was_explicit:
                    raise HTTPException(status_code=422, detail={
                        "ru": "Укажите время вылета с часовым поясом или сколько минут осталось до вылета.",
                        "en": "Provide flight_departure_at with a timezone or the time left before departure.",
                        "kk": "Ұшу уақытын белдеуімен немесе ұшуға дейін қалған минутты көрсетіңіз.",
                    }[request.language])
                departure = start + timedelta(minutes=flight_minutes if flight_minutes is not None
                                              else request.time_budget_minutes)
                departure_source = "relative_time_in_query" if flight_minutes is not None else "time_budget_minutes"
            else:
                departure = request.flight_departure_at
                departure_source = "flight_departure_at"
            if departure <= start or departure > now + timedelta(days=7):
                raise HTTPException(status_code=422, detail="flight_departure_at must be after starts_at and within 7 days")
            if departure_was_explicit and not budget_was_explicit and inferred is None:
                available = int((departure - start).total_seconds() // 60)
                if available < 20:
                    raise HTTPException(status_code=422, detail="Less than 20 minutes remain before flight departure")
                request = request.model_copy(update={"time_budget_minutes": min(360, available)})
            request = request.model_copy(update={"flight_departure_at": departure})
        pois = db.all_pois()
        if not pois:
            raise HTTPException(status_code=503, detail="POI data unavailable; run python -m app.ingest or wait for refresh")
        group = isinstance(request, GroupRecommendRequest)
        origin = None
        if not group:
            try:
                origin = await resolve_origin(request, pois, db, config)
            except LocationError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
            request = request.model_copy(update={"lat": origin["lat"], "lon": origin["lon"]})
        try:
            if request.query:
                async with embedding_lock:
                    scores = await semantic_scores(db, pois, request.query, config)
            else:
                scores = {}
        except EmbeddingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        candidates = candidate_pois(pois, request, scores, limit=40 if group else 60)
        participants = request.participants if group else [request]
        airport_reference = db.route_reference("airport") if flight_requested else None
        if flight_requested and not airport_reference:
            raise HTTPException(status_code=503, detail="Airport route reference unavailable; wait for OSM refresh")
        try:
            walking_task = pedestrian_matrix([(person.lat, person.lon) for person in participants], candidates, config)
            if flight_requested:
                routes, transfer_routes = await asyncio.gather(
                    walking_task,
                    airport_transfers(candidates, airport_reference["lat"], airport_reference["lon"],
                                      request.airport_transfer_mode, config),
                )
            else:
                routes = await walking_task
                transfer_routes = None
        except RoutingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        recommendations, notices, start = rank(candidates, request, routes, scores, transfer_routes)
        used_llm = await enhance(recommendations, request.language, config)
        context = {
            "query": request.query,
            "language": request.language,
            "time_budget_minutes": request.time_budget_minutes,
            "max_travel_minutes": effective_max_travel(request),
            "starts_at": start.isoformat(),
            "categories": request.categories,
            "exclude_categories": request.exclude_categories,
            "interests": [person.interests for person in request.participants] if group else request.interests,
            "participant_count": len(request.participants) if group else 1,
            "location_used": True,
            "origin": origin,
            "retrieval_method": "openai_embeddings_cosine_and_filters" if request.query else "geospatial_and_filters",
            "embedding_model": config.embedding_model if request.query else None,
            "distance_method": "valhalla_osm_pedestrian_matrix",
            "routing_provider": config.routing_url,
            "llm_text_policy": "server_verified_options_only",
        }
        if flight_requested:
            context["flight_plan"] = {
                "departure_at": request.flight_departure_at.astimezone(ASTANA_TZ).isoformat(),
                "departure_source": departure_source,
                "airport_arrival_buffer_minutes": request.airport_arrival_buffer_minutes,
                "airport_transfer_mode": request.airport_transfer_mode,
                "airport_route_reference": {
                    "lat": airport_reference["lat"], "lon": airport_reference["lon"],
                    "source_url": airport_reference["source_url"],
                    "fetched_at": airport_reference["fetched_at"],
                    "type": "road_access_point_not_verified_terminal_entrance",
                },
            }
        return RecommendResponse(recommendations=recommendations, language=request.language,
                                 context_used=context, generated_with="llm_verified" if used_llm else "grounded_templates",
                                 notices=notices)

    @app.post("/v1/recommendations", response_model=TwoGisNearbyResponse | RecommendResponse)
    async def individual_recommendations(request: PrimaryRecommendRequest):
        """Try one 2GIS page first, then the local OSM planner on empty/error.

        The response's source identifies its schema: 2GIS has flat POI cards;
        OSM has the existing planned recommendations. Nearby 2GIS lookup needs
        coordinates and a query; legacy named-origin requests use the OSM planner
        when those inputs are unavailable. A successful 2GIS response describes
        nearby places, not a walking/group/airport itinerary.
        """
        if request.lat is None:
            fallback_reason = "missing_coordinates"
        elif len(request.query) < 2:
            fallback_reason = "missing_search_query"
        else:
            try:
                result = await twogis_nearby(TwoGisNearbyRequest(
                    query=request.query, lat=request.lat, lon=request.lon, language=request.language,
                ), config)
            except TwoGisError:
                # Provider errors are handled here; do not expose URLs or keys.
                fallback_reason = "2gis_unavailable"
            else:
                if result.recommendations:
                    result.recommendations = result.recommendations[:request.limit]
                    result.context_used.update({
                        "provider": "2gis", "primary_provider": "2gis",
                        "fallback_used": False, "fallback_reason": None,
                    })
                    return result
                fallback_reason = "2gis_empty"

        # Preserve explicitly supplied fields so OSM still infers the time budget
        # from natural language. Its existing planner returns at most 3 options.
        osm_payload = request.model_dump(exclude_unset=True)
        osm_payload["limit"] = min(request.limit, 3)
        result = await recommend(RecommendRequest(**osm_payload))
        result.context_used.update({
            "provider": "osm", "primary_provider": "2gis",
            "fallback_used": True, "fallback_reason": fallback_reason,
        })
        return result

    @app.post("/v1/osm/recommendations", response_model=RecommendResponse)
    async def osm_recommendations(request: RecommendRequest):
        """Explicit OSM-only planner for source comparisons and route planning."""
        return await recommend(request)

    @app.post("/v1/group/recommendations", response_model=RecommendResponse)
    async def group_recommendations(request: GroupRecommendRequest):
        return await recommend(request)

    @app.post("/v1/2gis/recommendations", response_model=TwoGisNearbyResponse)
    async def twogis_recommendations(request: TwoGisNearbyRequest):
        try:
            return await twogis_nearby(request, config)
        except TwoGisError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/v1/admin/refresh")
    async def admin_refresh(x_admin_token: str | None = Header(default=None)):
        if not config.admin_token:
            raise HTTPException(status_code=503, detail="Admin refresh disabled; set ADMIN_TOKEN")
        if not x_admin_token or not hmac.compare_digest(x_admin_token, config.admin_token):
            raise HTTPException(status_code=401, detail="Invalid admin token")
        try:
            count = await do_refresh()
        except IngestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"imported": count, **db.status()}

    return app


app = create_app()
