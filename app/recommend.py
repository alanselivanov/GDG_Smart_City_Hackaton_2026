"""Grounded geospatial retrieval, group ranking, and conservative hours checks."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import GroupRecommendRequest, PoiOut, RecommendRequest, Recommendation


ASTANA_TZ = ZoneInfo("Asia/Almaty")
DAY_INDEX = {day: i for i, day in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"))}
RULE = re.compile(r"^((?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?(?:,(?:Mo|Tu|We|Th|Fr|Sa|Su))*)\s+(\d{2}:\d{2})-(\d{2}:\d{2})$")

KEYWORDS = {
    "cafe": ("коф", "кафе", "coffee", "cafe", "кофе", "кафе"),
    "food": ("поесть", "ужин", "обед", "restaurant", "eat", "dinner", "тамақ"),
    "museum": ("музе", "museum", "мұражай", "экспозиц"),
    "park": ("парк", "прогул", "гулять", "walk", "nature", "саябақ", "серуен"),
    "family": ("ребён", "ребен", "деть", "детск", "child", "kids", "балалар", "бала"),
    "nightlife": ("ноч", "вечер", "night", "late", "түн", "кеш"),
    "culture": ("театр", "кино", "искусств", "art", "theatre", "cinema", "өнер"),
    "viewpoint": ("вид", "панорам", "view", "photo", "фото", "көрініс"),
    "shopping": ("магаз", "шоп", "mall", "shop", "сауда"),
    "activity": ("актив", "спорт", "activity", "sport", "ойын"),
    "landmark": ("достопримеч", "турист", "unusual", "необыч", "sight", "көрнекті"),
}
SOCKET_TERMS = ("розет", "socket", "power outlet", "қуат")
QUIET_TERMS = ("тихо", "тихое", "спокой", "quiet", "calm", "тыныш")
FLIGHT_TERMS = ("вылет", "аэропорт", "flight", "airport", "ұшу", "әуежай")

CATEGORY_LABELS = {
    "ru": {"cafe": "кафе", "food": "место для еды", "nightlife": "вечернее заведение",
           "culture": "культурное место", "museum": "музей", "landmark": "городская достопримечательность",
           "viewpoint": "смотровая точка", "park": "парк", "family": "детская площадка",
           "activity": "место для активности", "shopping": "магазин"},
    "en": {"cafe": "cafe", "food": "place to eat", "nightlife": "evening venue",
           "culture": "cultural venue", "museum": "museum", "landmark": "city landmark",
           "viewpoint": "viewpoint", "park": "park", "family": "playground",
           "activity": "activity venue", "shopping": "shop"},
    "kk": {"cafe": "кафе", "food": "тамақтанатын орын", "nightlife": "кешкі орын",
           "culture": "мәдени орын", "museum": "мұражай", "landmark": "қаланың көрікті орны",
           "viewpoint": "көрініс алаңы", "park": "саябақ", "family": "балалар алаңы",
           "activity": "белсенді демалыс орны", "shopping": "дүкен"},
}
ACTIVITIES = {
    "ru": {"cafe": "Зайдите за напитком и отдохните.", "food": "Выберите блюдо и сделайте остановку на обед или ужин.",
           "nightlife": "Посмотрите меню и проведите здесь часть вечера.", "culture": "Посмотрите текущую программу на сайте места перед визитом.",
           "museum": "Осмотрите основную экспозицию; наличие интерактивов уточните заранее.",
           "landmark": "Осмотрите место снаружи и сделайте фото.", "viewpoint": "Оцените вид и сделайте фото.",
           "park": "Пройдитесь по дорожкам парка.", "family": "Проведите время на площадке с детьми.",
           "activity": "Уточните условия посещения и попробуйте доступную активность.",
           "shopping": "Пройдитесь по торговым рядам."},
    "en": {"cafe": "Stop for a drink and a break.", "food": "Choose a meal and take a lunch or dinner break.",
           "nightlife": "Check the menu and spend part of your evening here.", "culture": "Check the venue's current programme before visiting.",
           "museum": "Explore the main exhibits; check interactive options in advance.",
           "landmark": "See the site from outside and take a photo.", "viewpoint": "Enjoy the view and take a photo.",
           "park": "Walk along the park paths.", "family": "Spend some time at the playground with children.",
           "activity": "Check admission details and try an available activity.",
           "shopping": "Browse the shops."},
    "kk": {"cafe": "Сусын алып, демалыңыз.", "food": "Тағам таңдап, түскі не кешкі асқа тоқтаңыз.",
           "nightlife": "Мәзірді қарап, кештің бір бөлігін осында өткізіңіз.",
           "culture": "Барар алдында мекеменің қазіргі бағдарламасын тексеріңіз.",
           "museum": "Негізгі экспозицияны көріңіз; интерактивті бөлімдерді алдын ала нақтылаңыз.",
           "landmark": "Орынды сыртынан көріп, суретке түсіріңіз.",
           "viewpoint": "Көріністі тамашалап, суретке түсіріңіз.",
           "park": "Саябақ жолдарымен серуендеңіз.",
           "family": "Балалармен ойын алаңында уақыт өткізіңіз.",
           "activity": "Кіру шарттарын нақтылап, қолжетімді белсенділікті байқап көріңіз.",
           "shopping": "Дүкендерді аралаңыз."},
}
NOTICES = {
    "ru": {"unknown_hours": "Часы работы части мест неизвестны или имеют сложный формат; проверьте перед визитом.",
           "walking": "Расстояние указано по прямой; время пешком оценено с поправкой на обходы и может отличаться от реального маршрута.",
           "quiet": "Уровень шума не подтверждён данными OSM.",
           "socket": "Наличие розеток часто не указано в OSM; уточните перед визитом.",
           "empty": "Подходящих подтверждённых мест не найдено. Увеличьте время или измените фильтры."},
    "en": {"unknown_hours": "Some hours are missing or complex; check before visiting.",
           "walking": "Distance is straight-line; walking time includes a detour allowance and may differ from the actual route.",
           "quiet": "Noise level is not verified by OSM data.",
           "socket": "Power outlet data is often missing in OSM; check before visiting.",
           "empty": "No verified matching places were found. Increase the time or change filters."},
    "kk": {"unknown_hours": "Кейбір жұмыс уақыты белгісіз не күрделі; барар алдында тексеріңіз.",
           "walking": "Қашықтық түзу сызықпен өлшенді; жүру уақыты айналма жолды ескереді, нақты жол өзгеше болуы мүмкін.",
           "quiet": "Орынның тыныштығы OSM деректерімен расталмаған.",
           "socket": "OSM-де розетка туралы дерек жиі жоқ; барар алдында нақтылаңыз.",
           "empty": "Сәйкес расталған орын табылмады. Уақытты ұзартыңыз не сүзгілерді өзгертіңіз."},
}
FLIGHT_NOTICE = {
    "ru": "Перед вылетом оставьте запас времени на дорогу, регистрацию и досмотр.",
    "en": "Before your flight, leave time for travel, check-in and security.",
    "kk": "Ұшар алдында жолға, тіркеуге және тексеруге уақыт қалдырыңыз.",
}


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = rlat2 - rlat1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def walking_minutes(distance: float) -> int:
    return max(1, math.ceil(distance * 1.25 / 75))


def _minute(value: str) -> int | None:
    hour, minute = map(int, value.split(":"))
    if hour > 24 or minute > 59 or (hour == 24 and minute != 0):
        return None
    return hour * 60 + minute


def opening_status(hours: str | None, when: datetime, visit_minutes: int) -> str:
    if not hours:
        return "unknown"
    if hours.strip() == "24/7":
        return "open"
    intervals = []
    for part in hours.split(";"):
        match = RULE.fullmatch(part.strip())
        if not match:
            return "unknown"
        days_text, start_text, end_text = match.groups()
        start, end = _minute(start_text), _minute(end_text)
        if start is None or end is None or start == end:
            return "unknown"
        days: set[int] = set()
        for group in days_text.split(","):
            if "-" in group:
                left, right = (DAY_INDEX[x] for x in group.split("-"))
                days.update((left + i) % 7 for i in range((right - left) % 7 + 1))
            else:
                days.add(DAY_INDEX[group])
        intervals.append((days, start, end))
    local = when.astimezone(ASTANA_TZ)
    finish = local + timedelta(minutes=visit_minutes)
    for offset in (0, -1):
        base = local.date() + timedelta(days=offset)
        for days, start, end in intervals:
            if base.weekday() not in days:
                continue
            opening = datetime.combine(base, datetime.min.time(), ASTANA_TZ) + timedelta(minutes=start)
            closing = datetime.combine(base, datetime.min.time(), ASTANA_TZ) + timedelta(minutes=end)
            if end <= start:
                closing += timedelta(days=1)
            if opening <= local and finish <= closing:
                return "open"
    return "closed"


def _preferences(query: str) -> tuple[set[str], bool, bool]:
    lowered = query.casefold()
    categories = {category for category, terms in KEYWORDS.items() if any(term in lowered for term in terms)}
    return categories, any(term in lowered for term in SOCKET_TERMS), any(term in lowered for term in QUIET_TERMS)


def infer_budget(query: str) -> int | None:
    text = query.casefold().replace("–", "-").replace("—", "-")
    match = re.search(r"(\d{1,3})(?:\s*-\s*(\d{1,3}))?\s*(минут|мин\b|minutes?\b)", text)
    if match:
        return max(20, min(360, int(match.group(2) or match.group(1))))
    match = re.search(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*(час|часа|часов|hours?\b)", text)
    if match:
        return max(20, min(360, 60 * int(match.group(2) or match.group(1))))
    return None


def _name(poi: dict, language: str) -> str:
    return poi["names"].get(language) or poi["names"].get("default") or poi["name"]


def localized_description(poi: dict, language: str) -> str | None:
    return poi["tags"].get(f"description:{language}") or (poi["description"] if language == "ru" else None)


def rank(pois: list[dict], request: RecommendRequest | GroupRecommendRequest) -> tuple[list[Recommendation], list[str], datetime]:
    language = request.language
    start = (request.starts_at or datetime.now(ASTANA_TZ)).astimezone(ASTANA_TZ)
    max_travel = request.max_travel_minutes or min(35, max(10, request.time_budget_minutes // 3))
    desired, wants_socket, wants_quiet = _preferences(request.query)
    near_flight = any(term in request.query.casefold() for term in FLIGHT_TERMS)
    acceptable = set(desired)
    if "park" in desired:
        acceptable.update({"landmark", "viewpoint"})
    if "family" in desired:
        acceptable.update({"park", "museum", "culture"})
    if "landmark" in desired:
        acceptable.update({"museum", "culture", "viewpoint"})
    if "nightlife" in desired:
        acceptable.update({"food", "cafe"})
    if near_flight:
        acceptable.update({"cafe", "food"})
    group = isinstance(request, GroupRecommendRequest)
    participants = request.participants if group else [request]
    scored: list[tuple[float, Recommendation]] = []
    for poi in pois:
        category = poi["category"]
        if poi["tags"].get("tourism") == "hotel":
            continue
        if request.categories and category not in request.categories:
            continue
        if category in request.exclude_categories:
            continue
        if acceptable and category not in acceptable:
            continue
        distances = [distance_m(person.lat, person.lon, poi["lat"], poi["lon"]) for person in participants]
        walks = [walking_minutes(d) for d in distances]
        longest = max(walks)
        if longest > max_travel or longest + 15 > request.time_budget_minutes:
            continue
        visit = min({"cafe": 35, "food": 50, "museum": 55, "park": 35,
                     "family": 30, "culture": 50}.get(category, 30),
                    request.time_budget_minutes - longest)
        arrival = start + timedelta(minutes=longest)
        status = opening_status(poi["opening_hours"], arrival, visit)
        if status == "closed":
            continue
        matches = [not person.interests or category in person.interests for person in participants]
        interest_score = sum(matches) / len(matches)
        # Query/category relevance and group fairness outweigh pure proximity.
        score = 4.0 * (category in desired) + 2.5 * interest_score
        if group:
            score += 1.5 * min(matches)
        score += max(0.0, 2.5 - longest / 15)
        score += 0.7 if status == "open" else 0
        score += 0.2 if poi["description"] else 0
        if wants_socket and poi["tags"].get("socket:access") in {"yes", "customers"}:
            score += 3
        if request.query and request.query.casefold() in _name(poi, language).casefold():
            score += 3
        label = CATEGORY_LABELS[language][category]
        if language == "ru":
            why = f"Это {label} примерно в {round(max(distances))} м от места старта" + (" группы." if group else ".")
            if group and any(person.interests for person in participants):
                why += f" Соответствует интересам {sum(matches)} из {len(matches)} участников."
            elif not group and request.interests and category in request.interests:
                why += " Совпадает с вашими интересами."
            if poi["tags"].get("socket:access") in {"yes", "customers"}:
                why += " Розетки указаны в OSM."
        elif language == "kk":
            why = f"Бұл {label}; бастапқы орыннан шамамен {round(max(distances))} м" + (" (топ үшін)." if group else ".")
            if group and any(person.interests for person in participants):
                why += f" {len(matches)} қатысушының {sum(matches)}-інің қызығушылығына сай."
            elif not group and request.interests and category in request.interests:
                why += " Қызығушылығыңызға сай."
            if poi["tags"].get("socket:access") in {"yes", "customers"}:
                why += " Розетка OSM деректерінде көрсетілген."
        else:
            why = f"This {label} is about {round(max(distances))} m from the starting point" + (" for the group." if group else ".")
            if group and any(person.interests for person in participants):
                why += f" Matches the interests of {sum(matches)} of {len(matches)} participants."
            elif not group and request.interests and category in request.interests:
                why += " Matches your interests."
            if poi["tags"].get("socket:access") in {"yes", "customers"}:
                why += " OSM lists power outlets."
        name = _name(poi, language)
        rec = Recommendation(
            poi=PoiOut(id=poi["id"], name=name, category=category, lat=poi["lat"], lon=poi["lon"],
                       description=localized_description(poi, language), opening_hours=poi["opening_hours"],
                       website=poi["website"], phone=poi["phone"], source_url=poi["source_url"],
                       fetched_at=poi["fetched_at"], distance_m=round(max(distances))),
            distance_m=round(max(distances)), walking_minutes=longest, visit_minutes=visit,
            open_status=status,
            open_status_reason=(
                {"ru": "По расписанию OSM", "en": "According to OSM hours", "kk": "OSM кестесіне сәйкес"}[language]
                if status == "open" else
                {"ru": "Часы работы не подтверждены", "en": "Hours unverified", "kk": "Жұмыс уақыты расталмаған"}[language]
            ),
            why=why, what_to_do=ACTIVITIES[language][category],
            group_meeting_at=arrival if group else None,
            group_ends_at=arrival + timedelta(minutes=visit) if group else None,
            participant_walking_minutes=walks if group else None,
            participant_interest_matches=matches if group else None,
        )
        scored.append((score, rec))
    scored.sort(key=lambda pair: (-pair[0], pair[1].distance_m, pair[1].poi.id))
    # Avoid duplicate OSM node/way mapping of the same venue.
    chosen: list[Recommendation] = []
    for _, rec in scored:
        duplicate = any(rec.poi.name.casefold() == prev.poi.name.casefold() and
                        distance_m(rec.poi.lat, rec.poi.lon, prev.poi.lat, prev.poi.lon) < 80
                        for prev in chosen)
        if not duplicate:
            chosen.append(rec)
        if len(chosen) == request.limit:
            break
    notices = [NOTICES[language]["walking"]]
    if any(rec.open_status == "unknown" for rec in chosen):
        notices.append(NOTICES[language]["unknown_hours"])
    if wants_quiet:
        notices.append(NOTICES[language]["quiet"])
    if wants_socket:
        notices.append(NOTICES[language]["socket"])
    if near_flight:
        notices.append(FLIGHT_NOTICE[language])
    if not chosen:
        notices.append(NOTICES[language]["empty"])
    return chosen, notices, start
