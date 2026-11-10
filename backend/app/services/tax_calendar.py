import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import yaml

from app.config import get_settings

REGIME_LABELS = {
    "usn_income": "УСН «доходы»",
    "usn_income_expense": "УСН «доходы минус расходы»",
    "patent": "Патент",
    "npd": "НПД (самозанятый)",
    "ausn": "АУСН",
    "osn": "ОСН",
}

LEGAL_FORM_LABELS = {"ip": "ИП", "ooo": "ООО", "selfemployed": "Самозанятый"}


@dataclass(frozen=True)
class TaxEvent:
    id: str
    title: str
    regimes: tuple[str, ...]
    legal_forms: tuple[str, ...]
    rule: dict
    lead_days: int
    topic: str


@lru_cache
def _load(path: str) -> tuple[list[TaxEvent], bool, str]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    events = [
        TaxEvent(
            id=e["id"],
            title=e["title"],
            regimes=tuple(e["regimes"]),
            legal_forms=tuple(e["legal_forms"]),
            rule=e["rule"],
            lead_days=e.get("lead_days", 3),
            topic=e.get("topic", ""),
        )
        for e in raw["events"]
    ]
    return events, bool(raw.get("weekend_shift", True)), raw.get("year_note", "")


def all_events(path: str | None = None) -> list[TaxEvent]:
    return _load(path or get_settings().tax_calendar_path)[0]


def disclaimer(path: str | None = None) -> str:
    return _load(path or get_settings().tax_calendar_path)[2]


def get_event(event_id: str, path: str | None = None) -> TaxEvent | None:
    return next((e for e in all_events(path) if e.id == event_id), None)


def events_for(regime: str | None, legal_form: str | None, path: str | None = None) -> list[TaxEvent]:
    result = []
    for event in all_events(path):
        if regime and regime not in event.regimes:
            continue
        if legal_form and legal_form not in event.legal_forms:
            continue
        result.append(event)
    return result


def _shift_weekend(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _safe_date(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def due_dates(event: TaxEvent, year: int, weekend_shift: bool = True) -> list[date]:
    rule = event.rule
    if rule["type"] == "fixed":
        dates = [_safe_date(year, m, d) for m, d in rule["dates"]]
    elif rule["type"] == "monthly":
        dates = [_safe_date(year, m, rule["day"]) for m in range(1, 13)]
    else:
        return []
    if weekend_shift:
        dates = [_shift_weekend(d) for d in dates]
    return sorted(dates)


def next_due(event: TaxEvent, today: date, path: str | None = None) -> date | None:
    shift = _load(path or get_settings().tax_calendar_path)[1]
    for year in (today.year, today.year + 1):
        for d in due_dates(event, year, shift):
            if d >= today:
                return d
    return None
