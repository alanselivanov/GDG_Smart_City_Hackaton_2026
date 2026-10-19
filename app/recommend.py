"""Grounded geospatial retrieval, group ranking, and conservative hours checks."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.attributes import (attribute_for_requirement, attribute_score, average_check,
                            distinctive_attribute, fact_label, price_ceiling, relevant_facts)
from app.models import GroupRecommendRequest, PoiFact, PoiOut, RecommendRequest, Recommendation
from app.search_tags import cuisine_confirmed, explicit_cuisines


ASTANA_TZ = ZoneInfo("Asia/Almaty")
DAY_INDEX = {day: i for i, day in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"))}
RULE = re.compile(r"^((?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?(?:,(?:Mo|Tu|We|Th|Fr|Sa|Su))*)\s+(\d{2}:\d{2})-(\d{2}:\d{2})$")

KEYWORDS = {
    "cafe": ("коф", "кафе", "coffee", "cafe", "кофе", "кафе"),
    "food": ("поесть", "ужин", "обед", "завтрак", "позавтрак", "breakfast", "restaurant", "eat", "dinner", "тамақ"),
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
WALK_TERMS = ("прогул", "гулять", "пешком", "walk", "walking", "серуен", "жаяу")
PROXIMITY_PATTERN = re.compile(r"(?iu)поближ|ближе|близк|недалеко|поблизости|жақын|closer|nearby|nearest|close by|near me")
STROLL_TERMS = ("прогул", "гулять", "walk", "серуен")
UNUSUAL_TERMS = ("необыч", "нестандарт", "unusual", "unique", "ерекше")
INTERACTIVE_TERMS = ("интерактив", "interactive", "интерактивті")
PLAYGROUND_TERMS = ("площадк", "playground", "ойын алаң")
SIGHTSEEING_TERMS = ("достопримеч", "турист", "sightseeing", "tourist", "көрнекті")
NIGHT_TERMS = ("ночью", "ночное", "ночной", "ночная", "поздно вечером", "after midnight",
               "at night", "night out", "түнде", "түнгі")
GENERIC_PLAYGROUND = {"ru": "Детская площадка", "en": "Playground", "kk": "Балалар алаңы"}
FEATURE_LABELS = {
    "ru": {"artwork": "арт-объект", "memorial": "мемориал", "monument": "памятник",
           "attraction": "достопримечательность", "theatre": "театр", "cinema": "кинотеатр",
           "library": "библиотека", "garden": "сад", "playground": "детская площадка"},
    "en": {"artwork": "artwork", "memorial": "memorial", "monument": "monument",
           "attraction": "attraction", "theatre": "theatre", "cinema": "cinema",
           "library": "library", "garden": "garden", "playground": "playground"},
    "kk": {"artwork": "өнер нысаны", "memorial": "мемориал", "monument": "ескерткіш",
           "attraction": "көрікті орын", "theatre": "театр", "cinema": "кинотеатр",
           "library": "кітапхана", "garden": "бақ", "playground": "балалар алаңы"},
}

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
    "ru": {"cafe": "Зайдите за напитком и отдохните.", "food": "Выберите блюдо и поешьте здесь.",
           "nightlife": "Посмотрите меню и проведите здесь часть вечера.", "culture": "Посмотрите текущую программу на сайте места перед визитом.",
           "museum": "Уточните актуальные экспозиции и посетите музей.",
           "landmark": "Осмотрите место снаружи и сделайте фото.", "viewpoint": "Оцените вид и сделайте фото.",
           "park": "Прогуляйтесь в парке.", "family": "Проведите время на площадке с детьми.",
           "activity": "Уточните условия посещения и попробуйте доступную активность.",
           "shopping": "Пройдитесь по торговым рядам."},
    "en": {"cafe": "Stop for a drink and a break.", "food": "Choose a meal and eat here.",
           "nightlife": "Check the menu and spend part of your evening here.", "culture": "Check the venue's current programme before visiting.",
           "museum": "Check current exhibitions and visit the museum.",
           "landmark": "See the site from outside and take a photo.", "viewpoint": "Enjoy the view and take a photo.",
           "park": "Take a walk in the park.", "family": "Spend some time at the playground with children.",
           "activity": "Check admission details and try an available activity.",
           "shopping": "Browse the shops."},
    "kk": {"cafe": "Сусын алып, демалыңыз.", "food": "Тағам таңдап, осы жерде тамақтаныңыз.",
           "nightlife": "Мәзірді қарап, кештің бір бөлігін осында өткізіңіз.",
           "culture": "Барар алдында мекеменің қазіргі бағдарламасын тексеріңіз.",
           "museum": "Қазіргі көрмелерді нақтылап, мұражайға барыңыз.",
           "landmark": "Орынды сыртынан көріп, суретке түсіріңіз.",
           "viewpoint": "Көріністі тамашалап, суретке түсіріңіз.",
           "park": "Саябақта серуендеңіз.",
           "family": "Балалармен ойын алаңында уақыт өткізіңіз.",
           "activity": "Кіру шарттарын нақтылап, қолжетімді белсенділікті байқап көріңіз.",
           "shopping": "Дүкендерді аралаңыз."},
}
NOTICES = {
    "ru": {"unknown_hours": "У части мест время работы не указано; неизвестно, открыты ли они сейчас. Проверьте перед визитом.",
           "walking": "Путь и время рассчитаны по пешеходной сети OSM; фактическое время зависит от темпа и условий на месте.",
           "quiet": "Уровень шума не подтверждён доступными данными.",
           "socket": "Наличие розеток не определено; уточните перед визитом.",
           "interactive": "Интерактивность ближайших музеев не подтверждена доступными данными.",
           "empty": "Подходящих подтверждённых мест не найдено. Увеличьте время или измените фильтры."},
    "en": {"unknown_hours": "Some places have no listed hours; whether they are open is unknown. Check before visiting.",
           "walking": "Distance and time use the OSM pedestrian network; actual time depends on pace and local conditions.",
           "quiet": "Noise level is not confirmed by the available data.",
           "socket": "Power outlet availability is unknown; check before visiting.",
           "interactive": "Interactive features at nearby museums are not confirmed by the available data.",
           "empty": "No verified matching places were found. Increase the time or change filters."},
    "kk": {"unknown_hours": "Кейбір орындардың жұмыс уақыты көрсетілмеген; қазір ашық екені белгісіз. Барар алдында тексеріңіз.",
           "walking": "Қашықтық пен уақыт OSM жаяу жүру желісі бойынша есептелді; нақты уақыт жүру қарқыны мен жағдайға байланысты.",
           "quiet": "Орынның тыныштығы қолда бар деректермен расталмаған.",
           "socket": "Розетканың бары анықталмаған; барар алдында нақтылаңыз.",
           "interactive": "Жақын мұражайлардың интерактивті мүмкіндіктері қолда бар деректермен расталмаған.",
           "empty": "Сәйкес расталған орын табылмады. Уақытты ұзартыңыз не сүзгілерді өзгертіңіз."},
}
FLIGHT_NOTICE = {
    "ru": "Для вылета учтены поездка до дорожного ориентира аэропорта и запас {buffer} мин до рейса. Это не вход в терминал; время движения оценочное, требования авиакомпании проверьте отдельно.",
    "en": "The flight plan includes travel to an airport road-access point and a {buffer}-minute preflight buffer. This is not a verified terminal entrance; travel time is estimated. Check your airline's rules.",
    "kk": "Ұшу жоспарына әуежай жанындағы жол нүктесіне бару және рейске дейінгі {buffer} минут қор қосылды. Бұл расталған терминал кіреберісі емес; жол уақыты болжамды. Әуе компаниясының талаптарын тексеріңіз.",
}
FLIGHT_EMPTY = {
    "ru": "С учётом дороги в аэропорт и запаса до рейса подходящих мест не найдено. Если время вылета или необходимый запас отличаются, укажите точное время рейса и проверьте требования авиакомпании.",
    "en": "No safe option fits the airport transfer and preflight buffer. If the departure time or required buffer differs, enter the exact flight time and check your airline's rules.",
    "kk": "Әуежайға жол мен ұшу алдындағы уақыт қорын ескергенде қауіпсіз нұсқа табылмады. Ұшу уақыты не қажетті қор өзгеше болса, рейстің нақты уақытын енгізіп, әуе компаниясының талаптарын тексеріңіз.",
}
FLIGHT_NO_TIME = {
    "ru": "До вылета {minutes} мин. Запас до рейса — {buffer} мин, плюс нужна дорога в аэропорт. На безопасную прогулку времени нет. Если время рейса или требуемый запас отличаются, укажите точное время вылета и нужный запас.",
    "en": "The flight departs in {minutes} minutes. The preflight buffer is {buffer} minutes, plus travel to the airport. There is no time for a safe outing. If the flight time or required buffer differs, enter the exact departure time and buffer.",
    "kk": "Ұшуға {minutes} минут қалды. Рейске дейінгі қор — {buffer} минут, оған әуежайға жол қосылады. Қауіпсіз серуенге уақыт жоқ. Рейс уақыты не қажетті қор өзгеше болса, нақты уақыт пен қорды енгізіңіз.",
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
    if any(phrase in lowered for phrase in ("детское меню", "детским меню", "kids menu", "балалар мәзір")):
        categories.discard("family")
        categories.add("cafe")
    return categories, any(term in lowered for term in SOCKET_TERMS), any(term in lowered for term in QUIET_TERMS)


def night_intent(query: str, start: datetime) -> bool:
    local = start.astimezone(ASTANA_TZ)
    return (local.hour >= 22 or local.hour < 6) or any(
        term in query.casefold() for term in NIGHT_TERMS)


def night_category_allowed(category: str, walking: bool) -> bool:
    return category in {"nightlife", "cafe", "food", "culture", "activity", "museum"} or (
        walking and category in {"park", "landmark", "viewpoint"}
    )


def requested_requirements(request: RecommendRequest | GroupRecommendRequest) -> set[str]:
    lowered = request.query.casefold()
    requirements = set(request.must_have)
    if any(term in lowered for term in SOCKET_TERMS) and not re.search(r"\b(?:без|without|no)\s+розет", lowered):
        requirements.add("sockets")
    if any(term in lowered for term in QUIET_TERMS):
        requirements.add("quiet")
    if any(term in lowered for term in INTERACTIVE_TERMS):
        # "Playground or interactive museum" offers two alternative activities.
        if not (any(term in lowered for term in PLAYGROUND_TERMS)
                and any(term in lowered for term in ("музе", "museum", "мұраж"))):
            requirements.add("interactive")
    return requirements


def localized_facts(poi: dict, language: str) -> list[PoiFact]:
    return [PoiFact(key=fact["fact_key"], kind=fact["kind"],
                    text=fact[f"text_{language}"], source_url=fact["source_url"],
                    verified_at=fact["verified_at"])
            for fact in poi.get("facts") or []]


def chosen_fact(poi: dict, request: RecommendRequest | GroupRecommendRequest) -> dict | None:
    facts = poi.get("facts") or []
    if not facts:
        return None
    interactive = "interactive" in requested_requirements(request)
    if interactive:
        return next((fact for fact in facts if fact["kind"] == "interactive"), facts[0])
    return next((fact for fact in facts if fact["kind"] == "distinctive"), facts[0])


def requirement_confirmed(poi: dict, requirement: str) -> bool:
    tags = poi["tags"]
    if requirement == "sockets" and tags.get("socket:access") in {"yes", "customers"}:
        return True
    if requirement == "quiet" and tags.get("quiet") == "yes":
        return True
    if requirement == "interactive" and (
        tags.get("interactive") in {"yes", "interactive"}
        or any(fact["kind"] == "interactive" for fact in poi.get("facts") or [])
    ):
        return True
    return attribute_for_requirement(poi, requirement) is not None


def has_distinctive_evidence(poi: dict, language: str) -> bool:
    if any(fact["kind"] == "distinctive" for fact in poi.get("facts") or []):
        return True
    attribute = distinctive_attribute(poi)
    return attribute is not None and fact_label(attribute, language) is not None


def interest_match(person, poi: dict) -> bool:
    interests = set(person.interests)
    category = poi["category"]
    return not interests or category in interests or ("culture" in interests and category == "museum")


def same_place(first: Recommendation, second: Recommendation) -> bool:
    if first.poi.category != second.poi.category or distance_m(
        first.poi.lat, first.poi.lon, second.poi.lat, second.poi.lon
    ) > 300:
        return False

    def words(name: str) -> set[str]:
        normalized = re.sub(r"(?iu)\bрк\b", "республики казахстан", name.casefold())
        return set(re.findall(r"(?iu)[^\W_]+", normalized))

    left, right = words(first.poi.name), words(second.poi.name)
    return bool(left and right) and len(left & right) / len(left | right) >= 0.6


def is_before_flight(query: str) -> bool:
    if re.search(r"(?iu)(?:перед\s+вылетом|до\s+вылета|before\s+(?:my\s+|the\s+)?flight|ұшуға\s+дейін)", query):
        return True
    lowered = query.casefold().replace("ё", "е")
    return infer_budget(query) is not None and any(
        word in lowered for word in ("вылет", "рейс", "самолет", "flight", "plane", "ұшу", "ұшақ")
    )


def _duration_mentions(query: str) -> list[tuple[int, int, int]]:
    text = query.casefold().replace("–", "-").replace("—", "-")
    mentions: list[tuple[int, int, int]] = []

    def add(start: int, end: int, minutes: int) -> None:
        if not any(start < old_end and end > old_start for old_start, old_end, _ in mentions):
            mentions.append((start, end, minutes))

    for match in re.finditer(
        r"(?iu)\b(\d{1,3})(?:\s*-\s*(\d{1,3}))?\s*(минут(?:ы)?|мин\b|minutes?\b|час(?:а|ов)?\b|hours?\b|сағат)\b",
        text,
    ):
        count = int(match.group(2) or match.group(1))
        unit = match.group(3)
        add(match.start(), match.end(), count if unit.startswith(("мин", "minute")) else count * 60)
    special = ((r"полтора\s+часа|час\s*-\s*полтора|one\s+and\s+a\s+half\s+hours?", 90),
               (r"полчаса|half\s+an?\s+hour", 30))
    for pattern, minutes in special:
        for match in re.finditer(rf"(?iu)\b(?:{pattern})\b", text):
            add(match.start(), match.end(), minutes)
    words = {"один": 60, "одного": 60, "пару": 120, "два": 120, "двух": 120,
             "три": 180, "четыре": 240, "one": 60, "two": 120,
             "бір": 60, "екі": 120}
    for word, minutes in words.items():
        for match in re.finditer(rf"(?iu)\b{word}\s+(?:час(?:а|ов)?|hours?|сағат)\b", text):
            add(match.start(), match.end(), minutes)
    for match in re.finditer(r"(?iu)\b(?:час(?:а)?|hour)\b", text):
        before = text[max(0, match.start() - 20):match.start()]
        after = text[match.end():match.end() + 25]
        if re.search(r"(?iu)(?:в\s+течение|через|на|за|около|примерно|меня|осталось|an?\s*|the\s*)\s*$", before) or \
                re.match(r"(?iu)\s*(?:перед\s+вылетом|до\s+вылета)", after):
            add(match.start(), match.end(), 60)
    mentions.sort(key=lambda item: item[0])
    return mentions


def infer_flight_minutes(query: str) -> int | None:
    text = query.casefold().replace("ё", "е")
    markers = list(re.finditer(r"(?iu)вылет|рейс|самолет|flight|plane|ұшу|ұшақ", text))
    mentions = _duration_mentions(query)
    if not markers or not mentions:
        return None
    options = []
    for start, end, minutes in mentions:
        separation = min(max(0, marker.start() - end, start - marker.end()) for marker in markers)
        if separation <= 35:
            options.append((separation, start, minutes))
    return min(options)[2] if options else None


def infer_budget(query: str) -> int | None:
    mentions = _duration_mentions(query)
    if not mentions:
        return None
    flight_minutes = infer_flight_minutes(query)
    if flight_minutes is not None and len(mentions) > 1:
        for _, _, minutes in mentions:
            if minutes != flight_minutes:
                return minutes
    return mentions[0][2]


def feature_kind(poi: dict) -> str | None:
    tags = poi["tags"]
    # A specific historic/artwork tag is more informative than tourism=attraction.
    if tags.get("tourism") == "artwork":
        return "artwork"
    for key in ("historic", "tourism", "amenity", "leisure"):
        value = tags.get(key)
        if value in {"artwork", "memorial", "monument", "attraction", "theatre",
                     "cinema", "library", "garden", "playground"}:
            return value
    return None


def effective_max_travel(request: RecommendRequest | GroupRecommendRequest) -> int:
    if request.max_travel_minutes is not None:
        return request.max_travel_minutes
    lowered = request.query.casefold()
    if any(term in lowered for term in STROLL_TERMS):
        # A long walk is the activity itself. Keep enough time for the place
        # while allowing a destination farther than a short outing would.
        return min(90, max(10, request.time_budget_minutes // 2))
    if any(term in lowered for term in UNUSUAL_TERMS) and any(term in lowered for term in WALK_TERMS):
        return min(45, max(10, request.time_budget_minutes // 2))
    return min(35, max(10, request.time_budget_minutes // 3))


def proximity_requested(query: str) -> bool:
    return PROXIMITY_PATTERN.search(query) is not None


def _name(poi: dict, language: str) -> str:
    name = poi["names"].get(language) or poi["names"].get("default") or poi["name"]
    if poi["name"] == "Детская площадка" and poi["names"].get("default") == "Детская площадка":
        source = "2GIS" if poi["id"].startswith("2gis/") else "OSM"
        return f"{GENERIC_PLAYGROUND[language]} ({source} #{poi['id'].split('/')[-1]})"
    return name


def generic_name(poi: dict) -> bool:
    return poi["name"] == "Детская площадка" and poi["names"].get("default") == "Детская площадка"


def display_name(poi: dict, language: str) -> str:
    return _name(poi, language)


def eligible_for_intent(poi: dict, request: RecommendRequest | GroupRecommendRequest) -> bool:
    lowered = request.query.casefold()
    category = poi["category"]
    cuisines = explicit_cuisines(request.query)
    if cuisines and not any(cuisine_confirmed(poi, tag) for tag in cuisines):
        return False
    if any(term in lowered for term in UNUSUAL_TERMS) and not has_distinctive_evidence(poi, request.language):
        return False
    if "interactive" in requested_requirements(request):
        if any(term in lowered for term in ("музе", "museum", "мұраж")) and category != "museum":
            return False
        if category not in {"museum", "activity", "family"}:
            return False
    if request.categories:
        return True
    if any(term in lowered for term in PLAYGROUND_TERMS):
        museum_requested = any(term in lowered for term in ("музе", "museum", "мұраж"))
        return category == "family" or (category == "museum" and museum_requested)
    if any(term in lowered for term in UNUSUAL_TERMS):
        allowed = {"museum", "viewpoint", "landmark", "park", "activity", "nightlife", "culture"}
        if _preferences(request.query)[0] & {"food", "cafe"}:
            allowed.update({"food", "cafe"})
        return category in allowed
    if any(term in lowered for term in SIGHTSEEING_TERMS):
        return category in {"landmark", "museum", "viewpoint", "park"}
    if any(term in lowered for term in STROLL_TERMS):
        return category in {"park", "landmark", "viewpoint"} or (
            category == "family" and any(term in lowered for term in ("ребён", "ребен", "child", "бала"))
        )
    return True


def localized_description(poi: dict, language: str) -> str | None:
    fact = next((fact for fact in poi.get("facts") or [] if fact["kind"] == "distinctive"), None)
    if fact:
        return fact[f"text_{language}"]
    return poi["tags"].get(f"description:{language}") or (poi["description"] if language == "ru" else None)


def _sourced_food_activity(poi: dict, query: str, language: str, hour: int) -> str | None:
    """A precise fallback action when free-form copy cannot be verified."""
    if language != "ru" or poi["category"] not in {"cafe", "food"}:
        return None
    if any(term in query.casefold() for term in SOCKET_TERMS) and not requirement_confirmed(poi, "sockets"):
        return "Уточните наличие розеток перед визитом и выберите блюдо или напиток на месте."
    for item in relevant_facts(poi, query, hour):
        label = item["name"].strip()
        lowered = label.casefold()
        tag = (item.get("tag") or "").casefold()
        if 6 <= hour < 12 and ("завтрак" in lowered or "breakfast" in tag):
            return "Посмотрите предложения на завтрак и уточните, доступны ли они к вашему приходу."
        if "кухня" in lowered and lowered.endswith("ая кухня"):
            cuisine = lowered[:-8] + "ой кухни"
            return f"Выберите блюдо {cuisine} по меню на месте."
        if ("menu" in tag and "kids" not in tag and "english" not in tag) or "шаверм" in lowered or "суши" in lowered or "рамен" in lowered:
            return f"Посмотрите предложение «{label}» и выберите вариант на месте."
        if "заказ столик" in lowered or "booking" in tag:
            return "Уточните бронирование столика и выберите блюдо по меню."
    return None


def _explain_and_act(poi: dict, request: RecommendRequest | GroupRecommendRequest,
                     distance: int, walk: int, visit: int, matches: list[bool]) -> tuple[str, str, list[str]]:
    language = request.language
    name = _name(poi, language)
    kind = feature_kind(poi)
    label = FEATURE_LABELS[language].get(kind) or CATEGORY_LABELS[language][poi["category"]]
    group = isinstance(request, GroupRecommendRequest)
    lowered = request.query.casefold()
    unusual = any(term in lowered for term in UNUSUAL_TERMS)
    _, wants_socket, _ = _preferences(request.query)
    if price_ceiling(request.query) is not None and average_check(poi) is None:
        missing_price = {
            "ru": "Средний чек в источнике не указан; соответствие бюджету не подтверждено.",
            "en": "No average check is listed; the budget is unverified.",
            "kk": "Орташа чек көрсетілмеген; бюджетке сәйкестігі расталмаған.",
        }[language]
    else:
        missing_price = None
    reviewed_fact = chosen_fact(poi, request)
    description = None if reviewed_fact else localized_description(poi, language)
    missing: list[str] = []
    if language == "ru":
        why = f"«{name}» — {label} по данным OSM; {distance} м и {walk} мин пешком от старта."
        if group and any(person.interests for person in request.participants):
            why += f" Соответствует интересам {sum(matches)} из {len(matches)} участников."
        elif not group and request.interests and poi["category"] in request.interests:
            why += " Совпадает с вашими интересами."
        if description:
            why += f" Описание OSM: {description[:180].rstrip('. ')}."
        elif not reviewed_fact:
            missing.append("Подробное описание места в OSM не указано.")
        if poi["tags"].get("outdoor_seating") == "yes":
            why += " В OSM отмечены места на улице."
        if unusual and not description and not reviewed_fact and not distinctive_attribute(poi):
            why += " Чем именно место необычно, в OSM не указано."
        if wants_socket:
            if requirement_confirmed(poi, "sockets"):
                why += " Наличие розеток подтверждено источником."
        if kind == "artwork":
            action = f"Осмотрите арт-объект «{name}»; на остановку заложено {visit} мин."
        elif kind in {"memorial", "monument"}:
            action = f"Осмотрите «{name}»; на остановку заложено {visit} мин."
        elif kind == "attraction":
            action = f"Осмотрите «{name}» по координатам OSM; на остановку заложено {visit} мин."
        elif poi["category"] == "park":
            action = f"Прогуляйтесь по «{name}»; на посещение заложено {visit} мин."
        elif poi["category"] == "family":
            action = f"Найдите площадку по координатам и ссылке OSM; на посещение заложено {visit} мин."
        elif poi["category"] == "museum":
            action = f"Проверьте часы и текущую экспозицию «{name}» перед посещением."
        elif kind in {"theatre", "cinema"}:
            action = f"Проверьте программу и наличие билетов у «{name}» перед визитом."
        else:
            action = ACTIVITIES[language][poi["category"]]
    elif language == "en":
        why = f"OSM lists {name} as a {label}; it is {distance} m and {walk} min on foot from the start."
        if group and any(person.interests for person in request.participants):
            why += f" Matches the interests of {sum(matches)} of {len(matches)} participants."
        elif not group and request.interests and poi["category"] in request.interests:
            why += " Matches your interests."
        if description:
            why += f" OSM description: {description[:180].rstrip('. ')}."
        elif not reviewed_fact:
            missing.append("OSM does not provide a detailed description.")
        if poi["tags"].get("outdoor_seating") == "yes":
            why += " OSM lists outdoor seating."
        if unusual and not description and not reviewed_fact and not distinctive_attribute(poi):
            why += " OSM does not explain what makes it unusual."
        if wants_socket:
            if requirement_confirmed(poi, "sockets"):
                why += " Power outlets are confirmed by the source."
        if kind == "artwork":
            action = f"Take a look at the artwork {name}; allow about {visit} min."
        elif kind in {"memorial", "monument"}:
            action = f"See {name}; allow about {visit} min."
        elif kind == "attraction":
            action = f"Find and see {name} using its OSM coordinates; allow about {visit} min."
        elif poi["category"] == "park":
            action = f"Walk around {name}; allow about {visit} min."
        elif poi["category"] == "family":
            action = f"Use the OSM link and coordinates to find this playground; allow about {visit} min."
        elif poi["category"] == "museum":
            action = f"Check opening hours and current exhibitions at {name} before visiting."
        elif kind in {"theatre", "cinema"}:
            action = f"Check the programme and tickets at {name} before visiting."
        else:
            action = ACTIVITIES[language][poi["category"]]
    else:
        why = f"OSM дерегінде «{name}» — {label}; бастапқы нүктеден жаяу {distance} м, {walk} мин."
        if group and any(person.interests for person in request.participants):
            why += f" {len(matches)} қатысушының {sum(matches)}-інің қызығушылығына сай."
        elif not group and request.interests and poi["category"] in request.interests:
            why += " Қызығушылығыңызға сай."
        if description:
            why += f" OSM сипаттамасы: {description[:180].rstrip('. ')}."
        elif not reviewed_fact:
            missing.append("OSM-де орынның толық сипаттамасы көрсетілмеген.")
        if poi["tags"].get("outdoor_seating") == "yes":
            why += " OSM-де ашық ауадағы орындар көрсетілген."
        if unusual and not description and not reviewed_fact and not distinctive_attribute(poi):
            why += " Бұл орынның несімен ерекше екені OSM-де көрсетілмеген."
        if wants_socket:
            if requirement_confirmed(poi, "sockets"):
                why += " Розетканың бары дереккөзде расталған."
        if kind == "artwork":
            action = f"«{name}» өнер нысанын көріңіз; шамамен {visit} минут бөліңіз."
        elif kind in {"memorial", "monument"}:
            action = f"«{name}» орнын көріңіз; шамамен {visit} минут бөліңіз."
        elif kind == "attraction":
            action = f"«{name}» орнын OSM координаттары арқылы тауып көріңіз; шамамен {visit} минут бөліңіз."
        elif poi["category"] == "park":
            action = f"«{name}» аумағында серуендеңіз; шамамен {visit} минут бөліңіз."
        elif poi["category"] == "family":
            action = f"Алаңды OSM сілтемесі мен координаттары арқылы табыңыз; шамамен {visit} минут бөліңіз."
        elif poi["category"] == "museum":
            action = f"«{name}» орнының жұмыс уақытын және қазіргі көрмесін алдын ала тексеріңіз."
        elif kind in {"theatre", "cinema"}:
            action = f"«{name}» бағдарламасы мен билеттерін алдын ала тексеріңіз."
        else:
            action = ACTIVITIES[language][poi["category"]]
    if poi["id"].startswith("2gis/"):
        why = why.replace("OSM", "2GIS")
        action = action.replace("OSM", "2GIS")
        missing = [item.replace("OSM", "2GIS") for item in missing]
        if not description and not reviewed_fact:
            missing = [item for item in missing if not any(word in item for word in
                       ("описание", "description", "сипаттамасы"))]
            has_attributes = bool(poi.get("attribute_groups"))
            missing.append({
                "ru": ("Подробного описания в 2GIS нет; рекомендация основана на атрибутах 2GIS."
                       if has_attributes else "Описание и атрибуты места в 2GIS не указаны."),
                "en": ("2GIS has no detailed description; this recommendation uses its listed attributes."
                       if has_attributes else "2GIS lists neither a description nor venue attributes."),
                "kk": ("2GIS-те толық сипаттама жоқ; ұсыныс 2GIS атрибуттарына негізделген."
                       if has_attributes else "2GIS-те сипаттама да, атрибуттар да көрсетілмеген."),
            }[language])
        local_hour = (request.starts_at or datetime.now(ASTANA_TZ)).astimezone(ASTANA_TZ).hour
        labels = [label for item in relevant_facts(poi, request.query, local_hour)
                  if (label := fact_label(item, language))][:3]
        if unusual and not reviewed_fact and (special := distinctive_attribute(poi)):
            special_label = fact_label(special, language)
            if special_label and special_label not in labels:
                labels.insert(0, special_label)
                labels = labels[:3]
        if labels:
            details = "; ".join(labels)
            why += {"ru": f" Атрибуты 2GIS: {details}.",
                    "en": f" 2GIS venue details: {details}.",
                    "kk": f" 2GIS нысан деректері: {details}."}[language]
    if reviewed_fact:
        why += " " + reviewed_fact[f"text_{language}"]
        action = reviewed_fact[f"action_{language}"]
    if poi["category"] == "cafe" and "food" in _preferences(request.query)[0]:
        action = {
            "ru": "Выберите блюдо и перекусите здесь.",
            "en": "Choose a dish and eat here.",
            "kk": "Тағам таңдап, осы жерде тамақтаныңыз.",
        }[language]
    if poi["id"].startswith("2gis/"):
        local_hour = (request.starts_at or datetime.now(ASTANA_TZ)).astimezone(ASTANA_TZ).hour
        action = _sourced_food_activity(poi, request.query, language, local_hour) or action
    for requirement in sorted(requested_requirements(request)):
        if requirement_confirmed(poi, requirement):
            continue
        note = {
            "sockets": {"ru": "Наличие розеток не определено.", "en": "Power outlets are not confirmed.",
                        "kk": "Розетканың бары анықталмаған."},
            "quiet": {"ru": "Тишина в этом месте не подтверждена.", "en": "Quiet conditions are not confirmed.",
                      "kk": "Бұл жердің тыныштығы расталмаған."},
            "interactive": {"ru": "Интерактивность не подтверждена.", "en": "Interactive features are not confirmed.",
                            "kk": "Интерактивтілік расталмаған."},
        }[requirement][language]
        if note not in missing:
            missing.append(note)
    if missing_price:
        missing.append(missing_price)
    return why, action, missing


def candidate_pois(pois: list[dict], request: RecommendRequest | GroupRecommendRequest,
                   semantic_scores: dict[str, float], limit: int = 40) -> list[dict]:
    participants = request.participants if isinstance(request, GroupRecommendRequest) else [request]
    max_travel = effective_max_travel(request)
    desired, _, _ = _preferences(request.query)
    lowered = request.query.casefold()
    walking = any(term in lowered for term in WALK_TERMS)
    unusual = any(term in lowered for term in UNUSUAL_TERMS)
    requirements = requested_requirements(request)
    night = night_intent(request.query, request.starts_at or datetime.now(ASTANA_TZ))
    max_price = price_ceiling(request.query)
    candidates = []
    for poi in pois:
        category = poi["category"]
        if request.categories and category not in request.categories:
            continue
        if category in request.exclude_categories:
            continue
        if max_price is not None and (listed := average_check(poi)) is not None and listed > max_price:
            continue
        if not eligible_for_intent(poi, request):
            continue
        if night and not night_category_allowed(category, walking):
            continue
        if walking and not request.categories and category == "shopping":
            continue
        direct = max(distance_m(person.lat, person.lon, poi["lat"], poi["lon"])
                     for person in participants)
        if walking and direct < 80:
            continue
        if direct > max_travel * 125:
            continue
        interests = sum(interest_match(person, poi) for person in participants) / len(participants)
        score = (12 * semantic_scores.get(poi["id"], 0) + 3 * (category in desired)
                 + interests + attribute_score(poi, request.query))
        if requirements:
            confirmed = sum(requirement_confirmed(poi, requirement) for requirement in requirements)
            score += 20 if confirmed == len(requirements) else 2 * confirmed
        kind = feature_kind(poi)
        if unusual:
            score += {"artwork": 3.5, "memorial": 1.5, "monument": 2.0,
                      "attraction": 1.0}.get(kind, 0)
            score += 2 if category == "museum" else 0
        if walking and category == "park":
            score += 2
        score -= direct / 1700
        candidates.append((score, direct, poi))
    candidates.sort(key=lambda row: (-row[0], row[1], row[2]["id"]))
    if proximity_requested(request.query):
        # Route the nearest plausible places too, even when sparse catalog
        # attributes would otherwise push them out of the semantic shortlist.
        nearest = sorted(candidates, key=lambda row: (row[1], -row[0], row[2]["id"]))[:min(20, limit // 3)]
        reserved_ids = {row[2]["id"] for row in nearest}
        ordered = nearest + [row for row in candidates if row[2]["id"] not in reserved_ids]
        return [poi for _, _, poi in ordered[:limit]]
    if not request.categories and any(term in lowered for term in STROLL_TERMS):
        # Keep a few good candidates of each walkable kind before routing.
        # Otherwise a dense park cluster can fill the whole routing shortlist.
        reserved = []
        per_kind = max(1, min(6, limit // 3))
        for category in ("park", "landmark", "viewpoint"):
            reserved.extend([row for row in candidates if row[2]["category"] == category][:per_kind])
        selected = {row[2]["id"] for row in reserved}
        reserved.extend(row for row in candidates if row[2]["id"] not in selected)
        return [poi for _, _, poi in reserved[:limit]]
    return [poi for _, _, poi in candidates[:limit]]


def rank(pois: list[dict], request: RecommendRequest | GroupRecommendRequest,
         routes: dict[str, list[tuple[int, int] | None]],
         semantic_scores: dict[str, float] | None = None,
         airport_routes: dict[str, tuple[int, int] | None] | None = None,
         selection_limit: int | None = None) -> tuple[list[Recommendation], list[str], datetime]:
    language = request.language
    start = (request.starts_at or datetime.now(ASTANA_TZ)).astimezone(ASTANA_TZ)
    max_travel = effective_max_travel(request)
    desired, wants_socket, wants_quiet = _preferences(request.query)
    lowered = request.query.casefold()
    walking = any(term in lowered for term in WALK_TERMS)
    stroll = any(term in lowered for term in STROLL_TERMS) and not request.categories
    short_stroll = stroll and request.time_budget_minutes <= 60
    unusual = any(term in lowered for term in UNUSUAL_TERMS)
    night = night_intent(request.query, start)
    requirements = requested_requirements(request)
    max_price = price_ceiling(request.query)
    near_flight = request.flight_departure_at is not None
    group = isinstance(request, GroupRecommendRequest)
    participants = request.participants if group else [request]
    scored: list[tuple[float, Recommendation, dict]] = []
    for poi in pois:
        category = poi["category"]
        if poi["tags"].get("tourism") == "hotel":
            continue
        if request.categories and category not in request.categories:
            continue
        if category in request.exclude_categories:
            continue
        if max_price is not None and (listed := average_check(poi)) is not None and listed > max_price:
            continue
        if not eligible_for_intent(poi, request):
            continue
        if night and not night_category_allowed(category, walking):
            continue
        if walking and not request.categories and category == "shopping":
            continue
        route_values = routes.get(poi["id"])
        if not route_values or len(route_values) != len(participants) or any(value is None for value in route_values):
            continue
        distances = [value[0] for value in route_values if value is not None]
        seconds = [value[1] for value in route_values if value is not None]
        walks = [math.ceil(value / 60) for value in seconds]
        longest = max(walks)
        if walking and max(distances) < 80:
            continue
        if longest > max_travel or longest + 15 > request.time_budget_minutes:
            continue
        airport_distance = None
        airport_minutes = None
        latest_leave = None
        available_visit = request.time_budget_minutes - longest
        if near_flight:
            transfer = (airport_routes or {}).get(poi["id"])
            if transfer is None:
                continue
            airport_distance, airport_seconds = transfer
            airport_minutes = math.ceil(airport_seconds / 60)
            latest_leave = request.flight_departure_at.astimezone(ASTANA_TZ) - timedelta(
                minutes=request.airport_arrival_buffer_minutes + airport_minutes
            )
            available_visit = min(available_visit, math.floor((latest_leave - start).total_seconds() / 60) - longest)
            if available_visit < 15:
                continue
        visit = min({"cafe": 35, "food": 50, "museum": 55, "park": 35,
                     "family": 30, "culture": 50}.get(category, 30),
                    available_visit)
        arrival = start + timedelta(minutes=longest)
        status = opening_status(poi["opening_hours"], arrival, visit)
        if status == "closed" or (status == "unknown" and poi["opening_hours"]):
            continue
        matches = [interest_match(person, poi) for person in participants]
        interest_score = sum(matches) / len(matches)
        # Query/category relevance and group fairness outweigh pure proximity.
        score = 4.0 * (category in desired) + 2.5 * interest_score
        if group:
            person_utility = [int(match) - walk / max_travel for match, walk in zip(matches, walks)]
            score += 30 if all(matches) else 10 if sum(matches) >= math.ceil(len(matches) / 2) else 0
            score += 12 * min(person_utility) + 6 * interest_score
        score += 2.5 - longest / 15
        if selection_limit and proximity_requested(request.query):
            # Build an AI pool that contains nearby eligible options; the model
            # still makes the final choice and order from that pool.
            score -= longest * 1.1
        if short_stroll:
            # A short outing should leave useful time at the place. The hard
            # travel and visit limits above still decide feasibility.
            score -= 5 * (longest / max_travel) ** 2
        if semantic_scores:
            score += 10 * semantic_scores.get(poi["id"], 0)
        score += attribute_score(poi, request.query)
        if poi.get("attribute_groups") and category in desired:
            # A venue with catalog details can support a useful, specific
            # explanation; keep it competitive with sparse nearby OSM cards.
            score += min(6.0, 1.5 * len(relevant_facts(poi, request.query, start.hour)))
        score += 0.7 if status == "open" else 0
        score += 3 if poi.get("facts") else 0.6 if poi["description"] else 0
        if wants_socket and requirement_confirmed(poi, "sockets"):
            score += 4
        if requirements:
            score += 25 if all(requirement_confirmed(poi, item) for item in requirements) else \
                2 * sum(requirement_confirmed(poi, item) for item in requirements)
        if unusual:
            score += 4 if poi.get("facts") else 2 if distinctive_attribute(poi) else 0
        if walking and category == "park":
            score += 2
        if generic_name(poi):
            score -= 0.5
        if airport_minutes is not None:
            score -= airport_minutes / 30
        if request.query and request.query.casefold() in _name(poi, language).casefold():
            score += 3
        why, action, missing = _explain_and_act(poi, request, round(max(distances)), longest, visit, matches)
        if status == "unknown":
            missing.append({"ru": "Время работы не указано; неизвестно, открыто ли место сейчас.",
                            "en": "No opening hours are listed; whether this place is open now is unknown.",
                            "kk": "Жұмыс уақыты көрсетілмеген; қазір ашық екені белгісіз."}[language])
        if latest_leave is not None:
            action += {
                "ru": f" В аэропорт отправляйтесь не позднее {latest_leave:%H:%M}.",
                "en": f" Leave for the airport by {latest_leave:%H:%M}.",
                "kk": f" Әуежайға {latest_leave:%H:%M} уақытынан кешікпей аттаныңыз.",
            }[language]
        name = _name(poi, language)
        evidence = localized_facts(poi, language)
        for requirement in requirements:
            attribute = attribute_for_requirement(poi, requirement)
            if attribute:
                evidence_text = {
                    "sockets": {"ru": "Розетки указаны в 2GIS.", "en": "Power outlets are listed in 2GIS.",
                                "kk": "Розеткалар 2GIS-те көрсетілген."},
                    "quiet": {"ru": "Тихая зона указана в 2GIS.", "en": "A quiet area is listed in 2GIS.",
                              "kk": "Тыныш аймақ 2GIS-те көрсетілген."},
                    "interactive": {"ru": "Интерактивные объекты указаны в 2GIS.",
                                    "en": "Interactive features are listed in 2GIS.",
                                    "kk": "Интерактивті нысандар 2GIS-те көрсетілген."},
                }[requirement][language]
                evidence.append(PoiFact(
                    key=f"2gis:{attribute.get('tag') or attribute.get('id') or requirement}",
                    kind=requirement, text=evidence_text, source_url=poi["source_url"],
                    verified_at=poi["fetched_at"],
                ))
            elif requirement == "sockets" and poi["tags"].get("socket:access") in {"yes", "customers"}:
                evidence.append(PoiFact(key="osm:socket:access", kind="sockets",
                                        text={"ru": "Розетки отмечены в OSM.",
                                              "en": "Power outlets are listed in OSM.",
                                              "kk": "OSM-де розеткалар көрсетілген."}[language],
                                        source_url=poi["source_url"], verified_at=poi["fetched_at"]))
        if unusual and poi["id"].startswith("2gis/") and (special := distinctive_attribute(poi)):
            label = fact_label(special, language)
            if label:
                evidence.append(PoiFact(key=f"2gis:{special.get('tag') or 'distinctive'}",
                                        kind="distinctive", text=label,
                                        source_url=poi["source_url"], verified_at=poi["fetched_at"]))
        rec = Recommendation(
            poi=PoiOut(id=poi["id"], name=name, category=category, lat=poi["lat"], lon=poi["lon"],
                       description=localized_description(poi, language), opening_hours=poi["opening_hours"],
                       website=poi["website"], phone=poi["phone"], source_url=poi["source_url"],
                       fetched_at=poi["fetched_at"], distance_m=round(max(distances)),
                       name_is_generic=generic_name(poi),
                       attribute_groups=poi.get("attribute_groups") or [],
                       attributes_language=poi.get("attributes_language"),
                       rating=poi.get("rating"), review_count=poi.get("review_count"),
                       facts=localized_facts(poi, language)),
            distance_m=round(max(distances)), walking_minutes=longest,
            walking_seconds=max(seconds), visit_minutes=visit,
            open_status=status,
            open_status_reason=(
                {"ru": "По расписанию источника", "en": "According to source hours", "kk": "Дереккөз кестесіне сәйкес"}[language]
                if status == "open" else
                {"ru": "Время работы не указано; открытость неизвестна", "en": "Hours not listed; open status unknown", "kk": "Жұмыс уақыты көрсетілмеген; ашық екені белгісіз"}[language]
            ),
            why=why, what_to_do=action, missing_information=missing, evidence=evidence,
            requirement_status={item: "confirmed" if requirement_confirmed(poi, item) else "unknown"
                                for item in sorted(requirements)},
            airport_transfer_minutes=airport_minutes,
            airport_transfer_distance_m=airport_distance,
            latest_leave_for_airport_at=latest_leave,
            group_meeting_at=arrival if group else None,
            group_ends_at=arrival + timedelta(minutes=visit) if group else None,
            participant_walking_minutes=walks if group else None,
            participant_walking_seconds=seconds if group else None,
            participant_interest_matches=matches if group else None,
        )
        scored.append((score, rec, poi))
    if desired == {"food"} and not request.categories:
        dining = [item for item in scored if item[2]["category"] in {"food", "cafe"}]
        if dining:
            scored = dining
    group_insufficient_coverage = False
    if group and any(person.interests for person in participants):
        majority = math.ceil(len(participants) / 2)
        had_candidates = bool(scored)
        scored = [item for item in scored if sum(item[1].participant_interest_matches or []) >= majority]
        group_insufficient_coverage = had_candidates and not scored
    if requirements and any(all(item[1].requirement_status.get(requirement) == "confirmed"
                                for requirement in requirements) for item in scored):
        scored = [item for item in scored if all(item[1].requirement_status.get(requirement) == "confirmed"
                                                  for requirement in requirements)]
    # Greedy diversification only when the query allows several kinds of places.
    diversify = unusual or walking or len(desired) != 1
    chosen: list[Recommendation] = []
    chosen_pois: list[dict] = []
    remaining = scored[:]
    while remaining and len(chosen) < (selection_limit or request.limit):
        eligible = []
        for score, rec, poi in remaining:
            if any(same_place(rec, prev) for prev in chosen):
                continue
            chosen_names = {prev.poi.name.casefold() for prev in chosen}
            if rec.poi.name.casefold() in chosen_names and any(
                other_rec.poi.name.casefold() not in chosen_names
                and not any(same_place(other_rec, prev) for prev in chosen)
                for _, other_rec, _ in remaining
            ):
                continue
            if generic_name(poi) and sum(generic_name(prev) for prev in chosen_pois) >= 2:
                continue
            if generic_name(poi) and any(generic_name(prev) and
                   distance_m(poi["lat"], poi["lon"], prev["lat"], prev["lon"]) < 120
                   for prev in chosen_pois):
                continue
            adjusted = score
            if diversify:
                category_penalty = 7 if short_stroll else 6 if stroll else 4.5 if unusual else 2.5
                adjusted -= category_penalty * sum(poi["category"] == prev["category"] for prev in chosen_pois)
                if unusual and feature_kind(poi):
                    adjusted -= 3 * sum(feature_kind(poi) == feature_kind(prev) for prev in chosen_pois)
                adjusted -= 1.5 * sum(distance_m(poi["lat"], poi["lon"], prev["lat"], prev["lon"]) < 250
                                      for prev in chosen_pois)
            eligible.append((adjusted, score, rec, poi))
        if not eligible:
            break
        _, _, best, best_poi = max(eligible, key=lambda item: (item[0], item[1], -item[2].distance_m))
        chosen.append(best)
        chosen_pois.append(best_poi)
        remaining = [item for item in remaining if item[1].poi.id != best.poi.id]
    notices = selection_notices(chosen, request, start, group_insufficient_coverage)
    return chosen, notices, start


def selection_notices(chosen: list[Recommendation], request: RecommendRequest | GroupRecommendRequest,
                      start: datetime, group_insufficient_coverage: bool = False) -> list[str]:
    """Recompute notices after the final AI or deterministic selection."""
    language = request.language
    lowered = request.query.casefold()
    _, wants_socket, wants_quiet = _preferences(request.query)
    requirements = requested_requirements(request)
    near_flight = request.flight_departure_at is not None
    notices = [NOTICES[language]["walking"]]
    if any(rec.open_status == "unknown" for rec in chosen):
        notices.append(NOTICES[language]["unknown_hours"])
    if wants_quiet and any(rec.requirement_status.get("quiet") == "unknown" for rec in chosen):
        notices.append(NOTICES[language]["quiet"])
    if wants_socket and any(rec.requirement_status.get("sockets") == "unknown" for rec in chosen):
        notices.append(NOTICES[language]["socket"])
    if any(term in lowered for term in INTERACTIVE_TERMS) and not any(rec.poi.category == "museum" for rec in chosen):
        notices.append(NOTICES[language]["interactive"])
    if near_flight:
        notices.append(FLIGHT_NOTICE[language].format(buffer=request.airport_arrival_buffer_minutes))
    if requirements and chosen and not any(all(rec.requirement_status.get(item) == "confirmed"
                                                for item in requirements) for rec in chosen):
        notices.append({
            "ru": "Мест с подтверждением всех условий не найдено. Показаны лучшие варианты; неизвестные условия отмечены у каждого места.",
            "en": "No place has every requested feature confirmed. These are the best alternatives; unknown features are marked for each place.",
            "kk": "Барлық шарттары расталған орын табылмады. Ең жақсы баламалар көрсетілді; белгісіз шарттар әр жерде көрсетілген.",
        }[language])
    if not chosen:
        if group_insufficient_coverage:
            notices.append({
                "ru": "Не найдено места, подходящего по интересам хотя бы большинству участников группы.",
                "en": "No place matches the interests of at least a majority of the group.",
                "kk": "Топ қатысушыларының кемінде көпшілігінің қызығушылығына сай орын табылмады.",
            }[language])
        else:
            if near_flight:
                minutes_until_flight = max(0, math.floor((request.flight_departure_at - start).total_seconds() / 60))
                message = (FLIGHT_NO_TIME[language].format(minutes=minutes_until_flight,
                                                            buffer=request.airport_arrival_buffer_minutes)
                           if minutes_until_flight <= request.airport_arrival_buffer_minutes
                           else FLIGHT_EMPTY[language])
                notices.append(message)
            else:
                notices.append(NOTICES[language]["empty"])
    return notices
