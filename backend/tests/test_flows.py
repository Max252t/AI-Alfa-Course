from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services import tax_calendar as tc
from app.services.flows import (
    NO,
    YES,
    build_tax_items,
    make_title,
    sched_from_dict,
    sched_to_dict,
)
from app.services.schedule import Schedule

get_settings().tax_calendar_path = str(Path(__file__).resolve().parents[2] / "data" / "tax_calendar.yaml")
TZ = "Europe/Moscow"


def test_make_title_learning():
    assert make_title("напоминай каждый вторник", "learning", "Курс по УСН") == "Продолжить обучение: Курс по УСН"
    assert make_title("напоминай каждый вторник", "learning", None) == "Продолжить обучение"


def test_make_title_custom_strips_schedule():
    assert make_title("Напомни позвонить поставщику завтра в 15:00", "custom", None) == "Позвонить поставщику"
    assert make_title("напомни", "custom", None) == "Напоминание"


def test_schedule_roundtrip():
    s = Schedule(freq="weekly", weekdays=[1], interval=2, send_time="09:00")
    back = sched_from_dict(sched_to_dict(s))
    assert (back.freq, back.weekdays, back.interval, back.send_time) == ("weekly", [1], 2, "09:00")


def test_schedule_roundtrip_with_run_at():
    s = Schedule(run_at=datetime(2026, 5, 1, 15, 0, tzinfo=ZoneInfo(TZ)))
    assert sched_from_dict(sched_to_dict(s)).run_at == s.run_at


def test_yes_no_patterns():
    assert YES.match("Да")
    assert YES.match("всё верно!")
    assert NO.match("нет")
    assert not YES.match("да но поменяй время")


def test_build_tax_items_uses_event_lead_and_override():
    events = tc.events_for("usn_income", "ip")
    default = build_tax_items(events, {"lead_days": None, "send_time": "10:00"}, TZ)
    assert {i["tax_event_id"] for i in default} == {e.id for e in events}
    advance = next(i for i in default if i["tax_event_id"] == "usn_advance")
    assert advance["lead_days"] == 3
    custom = build_tax_items(events, {"lead_days": 7, "send_time": "09:00"}, TZ)
    assert all(i["lead_days"] == 7 and i["send_time"] == "09:00" for i in custom)


def test_build_tax_items_manual_patent_has_run_at():
    events = tc.events_for("patent", None)
    items = build_tax_items(events, {"lead_days": None, "send_time": "10:00", "patent_date": "2026-06-15T00:00:00"}, TZ)
    patent = next(i for i in items if i["tax_event_id"] == "patent_payment")
    assert patent["run_at"].startswith("2026-06-10T10:00")
