"""Request-scoped 2GIS Info facts used for grounded venue matching."""
from __future__ import annotations

import re


# Query cues and 2GIS catalog tags are kept separate: laptop-friendly does not
# imply sockets, and free Wi-Fi does not imply a quiet workspace.
FACETS = (
    (("завтрак", "позавтрак", "breakfast", "таңғы ас"), ("food_breakfast",)),
    (("детское меню", "детским меню", "kids menu", "балалар мәзір"), ("food_kids_menu",)),
    (("ребён", "ребен", "деть", "child", "kids", "бала"), ("food_kids_menu",)),
    (("ноутбук", "поработ", "работать", "laptop", "work"), ("cafe_working",)),
    (("навынос", "с собой", "takeaway", "takeout", "алып кет"), ("food_takeaway",)),
    (("английском", "english menu", "english-language menu"), ("food_english_menu",)),
    (("wi-fi", "wifi", "вайфай", "интернет"), ("freewifi",)),
    (("доставка", "delivery", "жеткізу"), ("delivery",)),
    (("чек", "цена", "стоимость", "price", "budget", "бюджет"), ("avg_price",)),
)

STOP_WORDS = {"хочу", "возле", "рядом", "можно", "чтобы", "место", "кафе", "ресторан",
              "where", "near", "with", "have", "place", "some", "посовет", "открыт",
              "меню", "menu"}


def facts(poi: dict) -> list[dict]:
    result = []
    for group in poi.get("attribute_groups") or []:
        for attribute in group.get("attributes") or []:
            if isinstance(attribute, dict) and isinstance(attribute.get("name"), str):
                result.append(attribute)
    return result


def relevant_facts(poi: dict, query: str) -> list[dict]:
    """Return named facts ordered by explicit request match, then usefulness."""
    query_lower = query.casefold()
    words = {word[:5] for word in re.findall(r"[^\W\d_]{4,}", query_lower)
             if word not in STOP_WORDS}
    ranked = []
    for position, attribute in enumerate(facts(poi)):
        tag = (attribute.get("tag") or "").casefold()
        name = attribute["name"]
        label = name.casefold()
        facet_match = any(any(cue in query_lower for cue in cues)
                          and any(part in tag for part in tags) for cues, tags in FACETS)
        word_match = bool(words & {word[:5] for word in re.findall(r"[^\W\d_]{4,}", label)})
        priority = (3 if facet_match else 1.5 if word_match else 0)
        if "awards_" in tag:
            priority += 0.8
        elif "avg_price" in tag or "cafe_working" in tag or "food_kids_menu" in tag:
            priority += 0.5
        ranked.append((priority, -position, attribute))
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [attribute for _, _, attribute in ranked]


def attribute_score(poi: dict, query: str) -> float:
    """Boost only attributes that actually answer the query."""
    query_lower = query.casefold()
    tags = {(attribute.get("tag") or "").casefold() for attribute in facts(poi)}
    score = sum(3.0 for cues, fragments in FACETS
                if any(cue in query_lower for cue in cues)
                and any(any(fragment in tag for fragment in fragments) for tag in tags))
    names = {attribute["name"].casefold() for attribute in facts(poi)}
    query_words = {word[:5] for word in re.findall(r"[^\W\d_]{4,}", query_lower)
                   if word not in STOP_WORDS}
    for name in names:
        if query_words & {word[:5] for word in re.findall(r"[^\W\d_]{4,}", name)}:
            score += 0.8
    return min(score, 6.0)


def fact_label(attribute: dict, language: str) -> str | None:
    """Translate only unambiguous 2GIS tags; preserve the raw catalog label in API."""
    if language != "en":
        return attribute["name"]
    tag = (attribute.get("tag") or "").casefold()
    if "avg_price" in tag:
        amount = re.search(r"\d[\d\s]*", attribute["name"])
        return f"Average check: {amount.group().strip()} ₸" if amount else None
    labels = (
        ("food_kids_menu", "Children's menu"),
        ("cafe_working", "Laptop-friendly"),
        ("food_breakfast", "Breakfast"),
        ("food_takeaway", "Takeaway"),
        ("food_english_menu", "English menu"),
        ("freewifi", "Free Wi-Fi"),
        ("delivery", "Delivery"),
        ("awards_awards_thebestcoffeeshop", "Best coffee shop award"),
    )
    return next((label for fragment, label in labels if fragment in tag), None)


def price_ceiling(query: str) -> int | None:
    """Read an explicit maximum in tenge, without mistaking a time for a price."""
    match = re.search(
        r"(?iu)(?:до|не дороже|under|up to|max(?:imum)?|бюджет(?: до)?|budget(?: under)?)"
        r"\s*(\d(?:[\d\s\u00a0]{2,7})?)\s*(?:₸|тг|тенге|теңге|kzt)",
        query,
    )
    if not match:
        return None
    amount = int(re.sub(r"\s", "", match.group(1)))
    return amount if 500 <= amount <= 1_000_000 else None


def average_check(poi: dict) -> int | None:
    for attribute in facts(poi):
        if "avg_price" not in (attribute.get("tag") or "").casefold():
            continue
        match = re.search(r"\d(?:[\d\s\u00a0]{2,7})?", attribute["name"])
        if match:
            return int(re.sub(r"\s", "", match.group()))
    return None
