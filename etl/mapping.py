import re

URL_TEMPLATES = {
    "article": "/articles/{url}/",
    "course": "/courses/{url}/",
    "document": "/documents/{url}/",
    "webinar": "/webinars/{url}/",
    "podcast": "/podcasts/{url}/",
    "glossary": "/vocabulary/{url}/",
    "calculator": "/calculators/{url}/",
}

ENTITY_TYPE_KINDS = {
    "8ede4179-0faf-407d-a4fc-1d94f9a63089": "article",
    "da1ad865-8605-4ab1-9f6c-4489a26fbc35": "document",
    "8b440b1a-00c3-423a-9bae-3376475eb203": "course",
    "ece4acf3-5dd3-47b9-9f08-99c0d6203cc7": "webinar",
    "142c23e2-bf71-4a73-b12e-6b1b5e4d47cc": "podcast",
}

PUBLISHED_STATUS = "61f12dbc-3cd4-4c14-b64b-1709548b904e"

FORMATS = {
    "article": "article",
    "course": "course",
    "document": "template",
    "webinar": "video",
    "podcast": "audio",
    "glossary": "term",
    "calculator": "calculator",
}

START_MARKERS = {"старт бизнеса", "первые шаги", "регистрация бизнеса", "формы бизнеса", "без опыта"}
GROWTH_MARKERS = {"стратегия и бизнес-модели", "с опытом", "лидерство", "управление командой", "франчайзинг"}


def build_url(kind: str, slug: str | None, base: str) -> str | None:
    if not slug:
        return None
    return base.rstrip("/") + URL_TEMPLATES[kind].format(url=slug.strip("/"))


def infer_stages(topics: list[str]) -> list[str]:
    lowered = {t.strip().lower() for t in topics}
    stages = []
    if lowered & START_MARKERS:
        stages.append("start")
    if lowered & GROWTH_MARKERS:
        stages.append("growth")
    return stages or ["any"]


def parse_duration_minutes(value: str | None) -> int | None:
    if not value:
        return None
    text = value.lower().replace(",", ".")
    minutes = 0.0
    found = False
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:час|ч\b)", text)
    if hours:
        minutes += float(hours.group(1)) * 60
        found = True
    mins = re.search(r"(\d+)\s*мин", text)
    if mins:
        minutes += int(mins.group(1))
        found = True
    return int(minutes) if found else None


def is_paid(kind: str, row: dict, course_has_tariff: bool = False) -> bool:
    if kind == "course":
        return row.get("Cost") is not None or course_has_tariff
    if kind == "podcast":
        return row.get("Cost") is not None or bool(row.get("IsClosed"))
    if kind == "article":
        return bool(row.get("IsClosed"))
    return False


def can_index_text(paid: bool) -> bool:
    return not paid
