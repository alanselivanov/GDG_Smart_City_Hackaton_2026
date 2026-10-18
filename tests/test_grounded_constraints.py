from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import GroupRecommendRequest, RecommendRequest, TwoGisPoi
from app.recommend import candidate_pois, night_intent, rank
from app.twogis import as_candidate, search_plan
from app.attributes import attribute_for_requirement
from app.db import Database
from app.ingest import normalize_element
from app.geocoding import _local_place, mentioned_place


TZ = ZoneInfo("Asia/Almaty")
DAY = datetime(2026, 10, 19, 13, 0, tzinfo=TZ)


def poi(identity, name, category, *, hours="24/7", tags=None, attributes=None, facts=None):
    return {
        "id": identity, "name": name, "names": {"default": name}, "category": category,
        "lat": 51.10, "lon": 71.41, "description": None, "tags": tags or {},
        "attribute_groups": attributes or [], "facts": facts or [],
        "opening_hours": hours, "website": None, "phone": None,
        "source_url": f"https://www.openstreetmap.org/node/{identity}",
        "fetched_at": "2026-10-19T00:00:00+00:00",
    }


def routes(places, walks=None):
    walks = walks or {}
    return {place["id"]: [(400, walks.get(place["id"], 300))] for place in places}


def test_socket_requirement_prefers_proof_and_falls_back_to_three():
    places = [poi(str(i), f"Cafe {i}", "cafe") for i in range(4)]
    request = RecommendRequest(lat=51.1, lon=71.41, query="Кафе с розеткой", starts_at=DAY)
    recommendations, notices, _ = rank(places, request, routes(places))
    assert len(recommendations) == 3
    assert all(rec.requirement_status == {"sockets": "unknown"} for rec in recommendations)
    assert all("Наличие розеток не определено." in rec.missing_information for rec in recommendations)
    assert any("Мест с подтверждением всех условий не найдено" in notice for notice in notices)

    confirmed = poi("5", "Cafe with socket", "cafe", tags={"socket:access": "customers"})
    places.append(confirmed)
    recommendations, _, _ = rank(places, request, routes(places, {"5": 1200}))
    assert [rec.poi.id for rec in recommendations] == ["5"]
    assert recommendations[0].requirement_status == {"sockets": "confirmed"}
    assert any(item.key == "osm:socket:access" for item in recommendations[0].evidence)


def test_recommendation_list_uses_distinct_venue_names_when_available():
    places = [poi("1", "Cafe A", "cafe"), poi("2", "Cafe A", "cafe"),
              poi("3", "Cafe B", "cafe"), poi("4", "Cafe C", "cafe")]
    request = RecommendRequest(lat=51.1, lon=71.41, query="Кафе с розеткой", starts_at=DAY)
    recommendations, _, _ = rank(places, request, routes(places))
    assert len(recommendations) == 3
    assert len({rec.poi.name for rec in recommendations}) == 3


def test_negative_socket_catalog_attribute_is_not_proof():
    place = poi("1", "Cafe", "cafe", attributes=[{
        "name": "Facilities", "attributes": [{"name": "No power outlets", "tag": "no_power_outlet"}],
    }])
    assert attribute_for_requirement(place, "sockets") is None


def test_time_phrase_is_not_location_and_inflected_museum_name_is_local():
    assert mentioned_place("Хочу посидеть в кафе с розеткой около часа, пешком") is None
    assert mentioned_place("Я с ребёнком возле Национального музея, хотим музей на час") == \
        "Национального музея"
    museum = poi("museum", "Национальный музей Республики Казахстан", "museum")
    request = RecommendRequest(lat=51.1, lon=71.41)
    assert _local_place("Национального музея", [museum], request)["name"] == museum["name"]


def test_colloquial_mega_name_uses_catalog_coordinates_and_food_search():
    mall = poi("mall", "Mega Silk Way", "shopping")
    request = RecommendRequest(query="Хочу поесть сейчас где то возле меги силквей")
    assert _local_place("меги силквей", [mall], request)["name"] == "Mega Silk Way"
    assert search_plan("ночью Хочу поесть сейчас где то возле меги силквей") == (
        "ресторан", 3000, "food"
    )


def test_plain_food_request_prefers_dining_venues_over_nightclubs():
    places = [poi("meal", "Restaurant", "food", hours="24/7"),
              poi("coffee", "Cafe", "cafe", hours="24/7"),
              poi("karaoke", "Karaoke bar", "nightlife", hours="24/7")]
    request = RecommendRequest(lat=51.1, lon=71.41, query="Хочу поесть сейчас", starts_at=DAY)
    recommendations, _, _ = rank(places, request, routes(places))
    assert [rec.poi.category for rec in recommendations] == ["food", "cafe"]
    assert recommendations[0].what_to_do == "Выберите блюдо и поешьте здесь."
    assert recommendations[1].what_to_do == "Выберите блюдо и перекусите здесь."


def test_night_checks_listed_hours_and_keeps_unknown_venues():
    attribute = [{"name": "Awards", "attributes": [{"name": "Best bar", "tag": "awards_best_bar"}]}]
    confirmed = poi("open", "Open bar", "nightlife", hours="Mo 22:00-02:00", attributes=attribute)
    unknown = poi("unknown", "Unknown bar", "nightlife", hours=None, attributes=attribute)
    closing = poi("closing", "Closing bar", "nightlife", hours="Mo 22:00-23:20", attributes=attribute)
    landmark = poi("monument", "Monument", "landmark", hours="24/7", facts=[{
        "fact_key": "architecture", "kind": "distinctive", "text_ru": "Особая архитектура.",
        "text_en": "Distinctive architecture.", "text_kk": "Ерекше сәулет.",
        "action_ru": "Осмотрите снаружи.", "action_en": "View the exterior.",
        "action_kk": "Сыртын көріңіз.", "source_url": "https://example.org/fact",
        "verified_at": "2026-10-19",
    }])
    places = [confirmed, unknown, closing, landmark]
    request = RecommendRequest(lat=51.1, lon=71.41, query="Необычное ночью",
                               starts_at=datetime(2026, 10, 19, 23, 0, tzinfo=TZ))
    candidates = candidate_pois(places, request, {})
    assert landmark not in candidates
    recommendations, _, _ = rank(places, request, routes(places))
    assert {rec.poi.id for rec in recommendations} == {"open", "unknown"}
    assert recommendations[0].open_status == "open"
    assert next(rec for rec in recommendations if rec.poi.id == "unknown").open_status == "unknown"


def test_night_stroll_allows_parks_and_discloses_missing_hours():
    places = [poi("unknown-park", "Open space", "park", hours=None, tags={"leisure": "park"}),
              poi("open-park", "All-night park", "park", hours="24/7", tags={"leisure": "park"}),
              poi("closed-park", "Daytime park", "park", hours="Mo 08:00-20:00", tags={"leisure": "park"})]
    request = RecommendRequest(lat=51.09, lon=71.40, query="Где погулять 2 часа?",
                               starts_at=datetime(2026, 10, 19, 3, 0, tzinfo=TZ))
    assert {place["id"] for place in candidate_pois(places, request, {})} == {place["id"] for place in places}
    recommendations, notices, _ = rank(places, request, routes(places))
    assert {rec.poi.id for rec in recommendations} == {"unknown-park", "open-park"}
    unknown = next(rec for rec in recommendations if rec.poi.id == "unknown-park")
    assert unknown.open_status == "unknown"
    assert "неизвестно, открыто ли место сейчас" in unknown.missing_information[-1]
    assert any("неизвестно, открыты ли они сейчас" in notice for notice in notices)


def test_night_is_inferred_from_local_time_without_keyword():
    assert night_intent("Кафе рядом", datetime(2026, 10, 19, 23, 0, tzinfo=TZ))
    assert night_intent("Кафе рядом", datetime(2026, 10, 20, 2, 0, tzinfo=TZ))
    assert not night_intent("Кафе рядом", DAY)


def test_group_prioritizes_shared_interest_and_rejects_one_person_option():
    museum = poi("museum", "Museum", "museum", hours="24/7")
    culture = poi("culture", "Theatre", "culture", hours="24/7")
    places = [museum, culture]
    participants = [{"lat": 51.1, "lon": 71.41, "interests": interest}
                    for interest in (["museum"], ["culture"], ["museum"])]
    request = GroupRecommendRequest(participants=participants, starts_at=DAY)
    paths = {"museum": [(1500, 1200)] * 3, "culture": [(200, 120)] * 3}
    recommendations, _, _ = rank(places, request, paths)
    assert [rec.poi.id for rec in recommendations] == ["museum"]
    assert recommendations[0].participant_interest_matches == [True, True, True]

    disjoint = GroupRecommendRequest(participants=[
        {"lat": 51.1, "lon": 71.41, "interests": [interest]}
        for interest in ("museum", "park", "food")], starts_at=DAY)
    recommendations, _, _ = rank(places, disjoint, paths)
    assert recommendations == []


def test_same_museum_from_two_providers_is_not_shown_twice():
    first = poi("osm", "Национальный музей Республики Казахстан", "museum", hours="24/7")
    second = poi("2gis/123", "Национальный музей РК", "museum", hours="24/7")
    places = [first, second]
    request = RecommendRequest(lat=51.1, lon=71.41, query="музей", starts_at=DAY)
    recommendations, _, _ = rank(places, request, routes(places))
    assert len(recommendations) == 1


def test_nightlife_2gis_search_and_category_are_not_inferred_from_barber():
    assert search_plan("что-то необычное ночью") == ("бар", 3000, "nightlife")
    bar = TwoGisPoi(id="1", name="Night Bar", lat=51.1, lon=71.41,
                    distance_m=0, rubrics=["Бары"])
    barber = TwoGisPoi(id="2", name="Барбершоп", lat=51.1, lon=71.41,
                       distance_m=0, rubrics=["Парикмахерские"])
    assert as_candidate(bar, "nightlife", "ru")["category"] == "nightlife"
    assert as_candidate(barber, "nightlife", "ru") == {}


def test_expo_sphere_identity_uses_live_catalog_coordinates():
    card = TwoGisPoi(id="9570784863354303", name="проспект Мангилик Ел, 55/1",
                     lat=51.085, lon=71.39, distance_m=200,
                     rubrics=["Памятники и скульптуры"])
    candidate = as_candidate(card, "other", "ru")
    assert candidate["name"] == "Нур-Алем"
    assert candidate["lat"] == card.lat and candidate["lon"] == card.lon
    assert candidate["facts"][0]["source_url"] == "https://www.expo2017astana.com/en/page_id-40.html"
    assert as_candidate(card.model_copy(update={"id": "another-building"}), "other", "ru") == {}


def test_attraction_facts_follow_the_daily_osm_snapshot(tmp_path):
    db = Database(tmp_path / "places.sqlite3")
    db.init()
    arch = normalize_element({"type": "way", "id": 549307755,
                              "center": {"lat": 51.1043034, "lon": 71.4300836},
                              "tags": {"name": "Триумфальная арка Мангилик Ел",
                                       "tourism": "attraction"}})
    db.upsert_pois([arch])
    fact = db.all_pois()[0]["facts"][0]
    assert fact["source_url"].startswith("https://visitastana.kz/")
    assert fact["verified_at"] == "2026-10-19"
    changed = dict(arch, lat=51.105)
    db.upsert_pois([changed])
    assert db.all_pois()[0]["lat"] == 51.105
    assert db.all_pois()[0]["facts"][0]["fact_key"] == fact["fact_key"]
