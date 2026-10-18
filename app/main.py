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
from app.generation import enhance
from app.ingest import IngestError, refresh
from app.models import Category, GroupRecommendRequest, Language, PoiOut, RecommendRequest, RecommendResponse
from app.recommend import ASTANA_TZ, distance_m, infer_budget, localized_description, rank


def create_app(config: Settings = settings) -> FastAPI:
    db = Database(config.database_path)
    refresh_lock = asyncio.Lock()
    state: dict[str, str | None] = {"last_refresh_error": None}

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
            due = not last or datetime.now(ASTANA_TZ) - datetime.fromisoformat(last).astimezone(ASTANA_TZ) >= timedelta(hours=config.poi_refresh_hours)
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
                  description="Grounded city recommendations from real OpenStreetMap POI.")
    origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "X-Admin-Token"])

    @app.get("/health")
    def health():
        status = db.status()
        return {"status": "ready" if status["poi_count"] else "awaiting_poi", **status,
                "last_refresh_error": state["last_refresh_error"]}

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
        return [PoiOut(**{**poi, "name": poi["names"].get(language) or poi["names"].get("default", poi["name"]),
                          "description": localized_description(poi, language), "distance_m": d})
                for d, poi in found[:limit]]

    @app.get("/v1/pois/search", response_model=list[PoiOut])
    def search_pois(q: str = Query(min_length=2, max_length=100), language: Language = "ru",
                    limit: int = Query(default=10, ge=1, le=30)):
        needle = q.casefold().strip()
        found = [poi for poi in db.all_pois() if any(needle in name.casefold() for name in poi["names"].values())]
        found.sort(key=lambda poi: (not any(name.casefold().startswith(needle) for name in poi["names"].values()), poi["name"]))
        return [PoiOut(**{**poi, "name": poi["names"].get(language) or poi["names"].get("default", poi["name"]),
                          "description": localized_description(poi, language)}) for poi in found[:limit]]

    async def recommend(request: RecommendRequest | GroupRecommendRequest) -> RecommendResponse:
        if "time_budget_minutes" not in request.model_fields_set:
            inferred = infer_budget(request.query)
            if inferred is not None:
                request = request.model_copy(update={"time_budget_minutes": inferred})
        now = datetime.now(ASTANA_TZ)
        if request.starts_at and not now - timedelta(minutes=5) <= request.starts_at <= now + timedelta(days=7):
            raise HTTPException(status_code=422, detail="starts_at must be from now to 7 days ahead")
        pois = db.all_pois()
        if not pois:
            raise HTTPException(status_code=503, detail="POI data unavailable; run python -m app.ingest or wait for refresh")
        recommendations, notices, start = rank(pois, request)
        used_llm = await enhance(recommendations, request.language, config)
        group = isinstance(request, GroupRecommendRequest)
        context = {
            "query": request.query,
            "language": request.language,
            "time_budget_minutes": request.time_budget_minutes,
            "max_travel_minutes": request.max_travel_minutes or min(35, max(10, request.time_budget_minutes // 3)),
            "starts_at": start.isoformat(),
            "categories": request.categories,
            "exclude_categories": request.exclude_categories,
            "interests": [person.interests for person in request.participants] if group else request.interests,
            "participant_count": len(request.participants) if group else 1,
            "location_used": True,
            "distance_method": "great_circle_distance; walking_time_with_1.25_detour_factor",
        }
        return RecommendResponse(recommendations=recommendations, language=request.language,
                                 context_used=context, generated_with="llm" if used_llm else "grounded_templates",
                                 notices=notices)

    @app.post("/v1/recommendations", response_model=RecommendResponse)
    async def individual_recommendations(request: RecommendRequest):
        return await recommend(request)

    @app.post("/v1/group/recommendations", response_model=RecommendResponse)
    async def group_recommendations(request: GroupRecommendRequest):
        return await recommend(request)

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
