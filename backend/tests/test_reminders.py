from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.services import tax_calendar as tc
from app.services.links import hash_tg_id, with_utm
from app.services.reminders import detect_type, manage_command, parse_lead_and_time, tax_next_run

PATH = str(Path(__file__).resolve().parents[2] / "data" / "tax_calendar.yaml")
TZ = "Europe/Moscow"


def at(y, m, d, h=12):
    return datetime(y, m, d, h, 0, tzinfo=ZoneInfo(TZ))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Напомни заплатить налог", "tax"),
        ("напоминай платить взносы", "tax"),
        ("Напоминай каждый вторник продолжить курс", "learning"),
        ("напомни позвонить поставщику", "custom"),
    ],
)
def test_detect_type(text, expected):
    assert detect_type(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Сделай раз в две недели", "change"),
        ("измени на каждый день", "change"),
        ("Отключи напоминание", "disable"),
        ("отключи все напоминания", "disable_all"),
        ("отключи", "disable"),
        ("как платить налоги", None),
    ],
)
def test_manage_command(text, expected):
    assert manage_command(text) == expected


def test_parse_lead_and_time():
    assert parse_lead_and_time("за 5 дней в 9:30") == (5, "09:30")
    assert parse_lead_and_time("в день срока") == (0, None)
    assert parse_lead_and_time("привет") == (None, None)


def test_tax_next_run_before_deadline():
    event = tc.get_event("usn_advance", PATH)
    run_at, due = tax_next_run(event, at(2026, 4, 20), TZ, "10:00", None, PATH)
    assert due == date(2026, 4, 28)
    assert run_at == datetime(2026, 4, 25, 10, 0, tzinfo=ZoneInfo(TZ))


def test_tax_next_run_skips_to_next_deadline_when_lead_passed():
    event = tc.get_event("usn_advance", PATH)
    run_at, due = tax_next_run(event, at(2026, 4, 27), TZ, "10:00", None, PATH)
    assert due.month == 7
    assert run_at > at(2026, 4, 27)


def test_tax_next_run_manual_is_none():
    event = tc.get_event("patent_payment", PATH)
    assert tax_next_run(event, at(2026, 1, 1), TZ, "10:00", None, PATH) is None


def test_utm_links():
    link = with_utm("https://x.ru/courses/a?x=1", "tax", "mat-1", hash_tg_id(5, "s"))
    assert "utm_source=tg_bot" in link and "utm_content=tax" in link and "utm_campaign=mat-1" in link
    assert "x=1" in link
    assert with_utm(None, "rec", None, "h") is None


def test_hash_is_stable_and_salted():
    assert hash_tg_id(5, "a") == hash_tg_id(5, "a")
    assert hash_tg_id(5, "a") != hash_tg_id(5, "b")
