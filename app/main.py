from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from app.ai_selection import score_candidates
from app.config import Settings, settings
from app.db import Database
from app.embeddings import EmbeddingError, semantic_scores
from app.generation import enhance
from app.geocoding import LocationError, resolve_origin
from app.ingest import IngestError, refresh, refresh_airport_reference
from app.models import (Category, GroupRecommendRequest, Language, PoiOut, PrimaryRecommendRequest, RecommendRequest,
                        RecommendResponse, TwoGisNearbyRequest, TwoGisNearbyResponse)
from app.rate_limit import ApiLimiter
from app.recommend import (ASTANA_TZ, candidate_pois, display_name, distance_m, effective_max_travel, generic_name,
                           infer_budget, infer_flight_minutes, is_before_flight, localized_description,
                           localized_facts, night_intent, NIGHT_TERMS, STROLL_TERMS, rank,
                           selection_notices)
from app.routing import RoutingError, airport_transfers, estimated_pedestrian_matrix, pedestrian_matrix
from app.search_tags import SearchTags, explicit_cuisines, plan_search, search_queries
from app.twogis import TwoGisError, as_candidate, nearby as twogis_nearby
from app.time_intent import infer_start


def create_app(config: Settings = settings) -> FastAPI:
    db = Database(config.database_path)
    refresh_lock = asyncio.Lock()
    embedding_lock = asyncio.Lock()
    external_api_limit = ApiLimiter(config.api_requests_per_minute, config.api_requests_per_day)
    recommendation_slots = asyncio.Semaphore(max(1, config.max_concurrent_recommendations))
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
                  description="Planned recommendations from OpenStreetMap and 2GIS places.")
    origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "X-Admin-Token"])

    @app.get("/health")
    def health():
        status = db.status()
        last = status["last_success_at"]
        age_hours = (round((datetime.now(ASTANA_TZ) - datetime.fromisoformat(last).astimezone(ASTANA_TZ))
                           .total_seconds() / 3600, 1) if last else None)
        return {"status": "ready" if status["poi_count"] else "awaiting_poi", **status,
                "poi_age_hours": age_hours,
                "poi_stale": age_hours is None or age_hours > config.max_poi_age_hours,
                "external_api_budget": external_api_limit.status(),
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
                          "description": localized_description(poi, language),
                          "facts": localized_facts(poi, language), "distance_m": d})
                for d, poi in found[:limit]]

    @app.get("/v1/pois/search", response_model=list[PoiOut])
    async def search_pois(http_request: Request, q: str = Query(min_length=2, max_length=100), language: Language = "ru",
                    limit: int = Query(default=10, ge=1, le=30)):
        await external_api_limit.charge(http_request.client.host if http_request.client else "unknown")
        needle = q.casefold().strip()
        pois = db.all_pois()
        if not pois:
            raise HTTPException(status_code=503, detail="POI data unavailable; run python -m app.ingest or wait for refresh")
        try:
            async with embedding_lock:
                scores = await semantic_scores(db, pois, needle, config)
        except EmbeddingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        found = sorted(pois, key=lambda poi: -(
            scores[poi["id"]] + (0.3 if any(name.casefold().startswith(needle) for name in poi["names"].values()) else 0)))
        return [PoiOut(**{**poi, "name": display_name(poi, language),
                          "name_is_generic": generic_name(poi),
                          "description": localized_description(poi, language),
                          "facts": localized_facts(poi, language)}) for poi in found[:limit]]

    async def recommend(request: RecommendRequest | GroupRecommendRequest,
                        include_twogis: bool = False) -> RecommendResponse:
        if (not request.query and not request.categories and not request.must_have and
                not (isinstance(request, GroupRecommendRequest) and
                     any(person.interests for person in request.participants))):
            raise HTTPException(status_code=422, detail="Provide a query or explicit place preferences")
        budget_was_explicit = "time_budget_minutes" in request.model_fields_set
        departure_was_explicit = "flight_departure_at" in request.model_fields_set
        inferred = infer_budget(request.query)
        flight_minutes = infer_flight_minutes(request.query)
        # When an exact departure is supplied, a relative "two hours before my
        # flight" phrase describes the deadline, not an outing duration.
        if request.flight_departure_at is not None and inferred == flight_minutes:
            inferred = None
        if "time_budget_minutes" not in request.model_fields_set:
            if inferred is not None:
                if not 20 <= inferred <= 360:
                    raise HTTPException(status_code=422, detail="Requested time must be between 20 and 360 minutes")
                request = request.model_copy(update={"time_budget_minutes": inferred})
        now = datetime.now(ASTANA_TZ)
        start_was_explicit = request.starts_at is not None
        try:
            stated_start = infer_start(request.query, now)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if start_was_explicit and stated_start and any(char.isdigit() for char in stated_start[1]):
            difference = abs((request.starts_at.astimezone(ASTANA_TZ) - stated_start[0]).total_seconds())
            if difference > 5 * 60:
                raise HTTPException(status_code=422, detail={
                    "ru": "Время в запросе отличается от выбранного времени начала. Укажите одно время.",
                    "en": "The time in the query conflicts with the selected start time. Use one time.",
                    "kk": "Сұраудағы уақыт таңдалған басталу уақытына сәйкес келмейді. Бір уақытты көрсетіңіз.",
                }[request.language])
        inferred_start = None if start_was_explicit else stated_start
        if inferred_start:
            request = request.model_copy(update={"starts_at": inferred_start[0]})
        if request.starts_at and not now - timedelta(minutes=5) <= request.starts_at <= now + timedelta(days=7):
            raise HTTPException(status_code=422, detail="starts_at must be from now to 7 days ahead")
        start = request.starts_at or now
        if request.starts_at is None and 6 <= now.hour < 22 and any(
            term in request.query.casefold() for term in NIGHT_TERMS
        ):
            raise HTTPException(status_code=422, detail={
                "ru": "Для ночного сценария укажите starts_at с датой и часовым поясом.",
                "en": "Set starts_at with a date and timezone for a night request.",
                "kk": "Түнгі сұрау үшін күні мен уақыт белдеуі көрсетілген starts_at енгізіңіз.",
            }[request.language])
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
        group = isinstance(request, GroupRecommendRequest)
        origin = None
        if not group:
            try:
                origin = await resolve_origin(request, pois, db, config)
            except LocationError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
            request = request.model_copy(update={"lat": origin["lat"], "lon": origin["lon"]})
        twogis_count = 0
        twogis_reason = None
        search_tags = SearchTags((), "not_used")
        if include_twogis:
            if len(request.query) < 2:
                twogis_reason = "missing_search_query"
            elif not config.twogis_api_key:
                twogis_reason = "missing_api_key"
            else:
                # Resolve the origin first. Every provider and Valhalla receives
                # the same start, including when the device is elsewhere.
                search_tags = await plan_search(request.query, config)
                searches = search_queries(request.query, search_tags)
                lowered = request.query.casefold()
                if night_intent(request.query, start) and not any(
                    term in lowered for term in NIGHT_TERMS
                ):
                    searches[0] = "ночью " + request.query
                expanded_stroll = not request.categories and any(term in lowered for term in STROLL_TERMS)
                if expanded_stroll:
                    searches.extend(("памятник", "смотровая площадка"))
                if any(term in lowered for term in ("площадк", "playground", "ойын алаң")) and any(
                    term in lowered for term in ("музе", "museum", "мұраж")
                ):
                    searches.append("музей")
                if origin and any(term in (origin.get("name") or "").casefold() for term in ("экспо", "expo")) and any(
                    term in lowered for term in ("необыч", "unusual", "ерекше")
                ):
                    searches.append("Нур-Алем")
                search_lat = (sum(person.lat for person in request.participants) / len(request.participants)
                              if group else request.lat)
                search_lon = (sum(person.lon for person in request.participants) / len(request.participants)
                              if group else request.lon)
                errors = 0
                for search in searches:
                    try:
                        result = await twogis_nearby(TwoGisNearbyRequest(
                            query=search, lat=search_lat, lon=search_lon, language=request.language,
                        ), config, open_at=start)
                    except TwoGisError:
                        errors += 1
                        if expanded_stroll and search == searches[0]:
                            # Avoid two more slow provider calls after its main
                            # walk search fails; the OSM cache remains available.
                            break
                        continue
                    intent = result.context_used["intent"]
                    for card in result.recommendations:
                        candidate = as_candidate(card, intent, request.language)
                        if candidate and all(poi["id"] != candidate["id"] for poi in pois):
                            pois.append(candidate)
                            twogis_count += 1
                if not twogis_count:
                    twogis_reason = "2gis_unavailable" if errors == len(searches) or (
                        expanded_stroll and errors
                    ) else "2gis_empty"
        if not pois:
            raise HTTPException(status_code=503, detail="POI data unavailable; run python -m app.ingest or wait for refresh")
        embedding_fallback = False
        try:
            if request.query:
                async with embedding_lock:
                    scores = await semantic_scores(db, pois, request.query, config)
            else:
                scores = {}
        except EmbeddingError:
            # Semantic retrieval improves ranking, but a transient API failure
            # must not make the cached POIs and route planner unavailable.
            scores = {}
            embedding_fallback = True
        candidates = candidate_pois(pois, request, scores, limit=40 if group else 60)
        participants = request.participants if group else [request]
        airport_reference = db.route_reference("airport") if flight_requested else None
        if flight_requested and not airport_reference:
            raise HTTPException(status_code=503, detail="Airport route reference unavailable; wait for OSM refresh")
        routing_fallback = False
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
            if flight_requested:
                # A straight-line estimate is unsafe for a flight deadline.
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            routes = estimated_pedestrian_matrix(
                [(person.lat, person.lon) for person in participants], candidates)
            transfer_routes = None
            routing_fallback = True
        ai_enabled = bool(config.llm_api_key and request.query)
        pool, notices, start = rank(candidates, request, routes, scores, transfer_routes,
                                    selection_limit=12 if ai_enabled else None)
        selection = (await score_candidates(pool, request, start, config)
                     if ai_enabled and len(pool) > 1 else None)
        recommendations = selection.recommendations if selection else pool[:request.limit]
        if ai_enabled and pool:
            notices = selection_notices(recommendations, request, start)
        if embedding_fallback:
            notices.append({
                "ru": "Смысловой поиск временно недоступен. Места подобраны по доступным категориям, атрибутам и расстоянию.",
                "en": "Semantic search is temporarily unavailable. Places were selected using available categories, attributes, and distance.",
                "kk": "Мағыналық іздеу уақытша қолжетімсіз. Орындар қолда бар санаттар, атрибуттар және қашықтық бойынша таңдалды.",
            }[request.language])
        if routing_fallback:
            notices.append({
                "ru": "Маршрутизатор временно недоступен. Время и расстояние пешком приблизительные; проверьте маршрут на карте.",
                "en": "The route service is unavailable. Walking time and distance are estimates; check the route on a map.",
                "kk": "Маршрут қызметі уақытша қолжетімсіз. Жаяу жүру уақыты мен қашықтығы шамамен берілген; маршрутты картадан тексеріңіз.",
            }[request.language])
        catalog_last = db.status()["last_success_at"]
        catalog_age_hours = ((datetime.now(ASTANA_TZ) - datetime.fromisoformat(catalog_last).astimezone(ASTANA_TZ))
                             .total_seconds() / 3600 if catalog_last else None)
        catalog_stale = catalog_age_hours is None or catalog_age_hours > config.max_poi_age_hours
        if catalog_stale and any(not rec.poi.id.startswith("2gis/") for rec in recommendations):
            notices.append({
                "ru": "Каталог OSM не обновлялся более суток; часы и сведения о месте проверьте перед визитом.",
                "en": "The OSM catalog has not refreshed in over a day; check hours and place details before visiting.",
                "kk": "OSM каталогы бір тәуліктен аса жаңартылмады; барар алдында жұмыс уақытын және орын деректерін тексеріңіз.",
            }[request.language])
        if not recommendations and explicit_cuisines(request.query):
            notices.append({
                "ru": "Место с подтверждённой запрошенной кухней, подходящее по времени и расстоянию, не найдено.",
                "en": "No place with the requested cuisine confirmed fits the time and distance limits.",
                "kk": "Сұралған асханасы расталған және уақыт пен қашықтыққа сай орын табылмады.",
            }[request.language])
        await enhance(recommendations, request.language, config, request.query, start,
                      request.time_budget_minutes)
        if group and any(person.interests for person in request.participants):
            for rec in recommendations:
                matches = rec.participant_interest_matches or []
                if matches and not all(matches) and not any(
                    term in rec.why.casefold() for term in ("интересам", "interests", "қызығушылы")
                ):
                    rec.why += {
                        "ru": f" Место совпадает с интересами {sum(matches)} из {len(matches)} участников; для остальных это компромисс.",
                        "en": f" It matches {sum(matches)} of {len(matches)} participants' interests; it is a compromise for the others.",
                        "kk": f" Бұл орын {len(matches)} қатысушының {sum(matches)} қызығушылығына сай; басқалары үшін бұл ымыралы нұсқа.",
                    }[request.language]
        generated_count = sum(rec.text_source == "llm_verified" for rec in recommendations)
        context = {
            "query": request.query,
            "language": request.language,
            "time_budget_minutes": request.time_budget_minutes,
            "max_travel_minutes": effective_max_travel(request),
            "starts_at": start.isoformat(),
            "starts_at_source": ("query" if inferred_start else "starts_at" if start_was_explicit
                                 else "current_time"),
            "categories": request.categories,
            "exclude_categories": request.exclude_categories,
            "interests": [person.interests for person in request.participants] if group else request.interests,
            "participant_count": len(request.participants) if group else 1,
            "location_used": True,
            "origin": origin,
            "retrieval_method": ("openai_embeddings_cosine_and_filters" if request.query and not embedding_fallback
                                 else "geospatial_and_filters"),
            "embedding_model": config.embedding_model if request.query and not embedding_fallback else None,
            "embedding_fallback_used": embedding_fallback,
            "poi_catalog_age_hours": round(catalog_age_hours, 1) if catalog_age_hours is not None else None,
            "poi_catalog_stale": catalog_stale,
            "routing_method": "geodesic_estimate" if routing_fallback else "osm_road_network",
            "routing_fallback_used": routing_fallback,
            "distance_method": ("geodesic_estimate_with_detour_factor" if routing_fallback
                                else "valhalla_osm_pedestrian_matrix"),
            "routing_provider": None if routing_fallback else config.routing_url,
            "llm_text_policy": "generated_from_catalog_facts_then_verified",
            "llm_generated_count": generated_count,
            "selection_method": ("ai_scored" if selection else
                                 "single_candidate" if len(pool) == 1 else
                                 "rules_fallback" if pool else "no_candidates"),
            "selection_candidate_count": len(pool),
            "selection_priorities": selection.priorities if selection else [],
            "selection_scores": selection.selected_scores if selection else {},
        }
        if inferred_start:
            context["time_interpretation"] = {"phrase": inferred_start[1],
                                              "local_time": inferred_start[0].isoformat()}
        if include_twogis:
            context.update({
                "search_tag_method": search_tags.method,
                "search_tags": list(search_tags.tags),
                "provider_search_queries": searches if search_tags.method != "not_used" else [],
                "providers": [provider for provider, used in (("osm", len(pois) > twogis_count),
                                                               ("2gis", twogis_count > 0)) if used],
                "2gis_candidate_count": twogis_count,
                "fallback_used": twogis_count == 0,
                "fallback_reason": twogis_reason,
            })
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
        sources = ({"2gis" if item.poi.id.startswith("2gis/") else "osm" for item in recommendations}
                   or {"2gis" if poi["id"].startswith("2gis/") else "osm" for poi in candidates})
        license_urls = {
            "osm": "https://www.openstreetmap.org/copyright",
            "2gis": "https://law.2gis.ru/offer-license-agreement-webapi",
        }
        context["source_license_urls"] = {provider: license_urls[provider] for provider in sources}
        source = ("2GIS and © OpenStreetMap contributors (ODbL), via Overpass API" if len(sources) == 2
                  else "2GIS" if sources == {"2gis"} else
                  "© OpenStreetMap contributors (ODbL), via Overpass API")
        return RecommendResponse(recommendations=recommendations, language=request.language,
                                 context_used=context, source=source,
                                 source_license_url=("https://www.openstreetmap.org/copyright" if sources != {"2gis"}
                                                     else license_urls["2gis"]),
                                 generated_with=("mixed" if 0 < generated_count < len(recommendations) else
                                                 "llm_verified" if generated_count else "grounded_templates"),
                                 notices=notices)

    async def limited_recommend(request: RecommendRequest | GroupRecommendRequest,
                                http_request: Request, include_twogis: bool) -> RecommendResponse:
        await external_api_limit.charge(http_request.client.host if http_request.client else "unknown")
        try:
            await asyncio.wait_for(recommendation_slots.acquire(), timeout=5)
        except asyncio.TimeoutError as exc:
            raise HTTPException(429, "Recommendation service is busy; retry shortly",
                                headers={"Retry-After": "5"}) from exc
        try:
            return await recommend(request, include_twogis)
        finally:
            recommendation_slots.release()

    @app.post("/v1/recommendations", response_model=RecommendResponse)
    async def individual_recommendations(request: PrimaryRecommendRequest, http_request: Request):
        return await limited_recommend(request, http_request, include_twogis=True)

    @app.post("/v1/osm/recommendations", response_model=RecommendResponse)
    async def osm_recommendations(request: RecommendRequest, http_request: Request):
        """Explicit OSM-only planner for source comparisons and route planning."""
        return await limited_recommend(request, http_request, include_twogis=False)

    @app.post("/v1/group/recommendations", response_model=RecommendResponse)
    async def group_recommendations(request: GroupRecommendRequest, http_request: Request):
        return await limited_recommend(request, http_request, include_twogis=True)

    @app.post("/v1/2gis/recommendations", response_model=TwoGisNearbyResponse)
    async def twogis_recommendations(request: TwoGisNearbyRequest, http_request: Request):
        await external_api_limit.charge(http_request.client.host if http_request.client else "unknown")
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
