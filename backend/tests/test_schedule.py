from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.schedule import Schedule, apply_quiet_hours, next_occurrence, parse_schedule

TZ = "Europe/Moscow"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=ZoneInfo(TZ))


def test_weekly_monday_9():
    s = parse_schedule("Напоминай каждый понедельник в 9", NOW, TZ)
    assert s.freq == "weekly"
    assert s.weekdays == [0]
    assert s.send_time == "09:00"


def test_weekly_tuesday():
    s = parse_schedule("каждый вторник продолжить курс", NOW, TZ)
    assert s.freq == "weekly"
    assert s.weekdays == [1]


def test_every_two_weeks():
    s = parse_schedule("раз в две недели", NOW, TZ)
    assert s.freq == "weekly"
    assert s.interval == 2


def test_daily_with_time():
    s = parse_schedule("каждый день в 10:30", NOW, TZ)
    assert s.freq == "daily"
    assert s.send_time == "10:30"


def test_monthly_and_quarterly():
    assert parse_schedule("ежемесячно", NOW, TZ).freq == "monthly"
    assert parse_schedule("раз в квартал", NOW, TZ).freq == "quarterly"


def test_one_off_tomorrow():
    s = parse_schedule("завтра в 15:00", NOW, TZ)
    assert s.run_at is not None
    assert s.run_at.hour == 15
    assert s.run_at.date() == datetime(2026, 3, 5).date()


def test_unparsable_is_empty():
    assert parse_schedule("просто привет", NOW, TZ).is_empty


def test_next_weekly_occurrence():
    s = Schedule(freq="weekly", weekdays=[0], send_time="09:00")
    nxt = next_occurrence(s, NOW, TZ)
    assert nxt.weekday() == 0
    assert nxt > NOW


def test_biweekly_skips_a_week():
    s = Schedule(freq="weekly", weekdays=[0], interval=2, send_time="09:00")
    first = next_occurrence(s, NOW, TZ, anchor=NOW)
    second = next_occurrence(s, first, TZ, anchor=NOW)
    assert (second - first).days == 14


def test_monthly_next():
    s = Schedule(freq="monthly", send_time="10:00")
    nxt = next_occurrence(s, NOW, TZ, anchor=NOW)
    assert nxt.month == 4 or nxt.date() == NOW.date()


def test_one_off_in_past_returns_none():
    s = Schedule(run_at=datetime(2020, 1, 1, tzinfo=ZoneInfo(TZ)))
    assert next_occurrence(s, NOW, TZ) is None


@pytest.mark.parametrize(
    "hour,expected_hour",
    [(23, 9), (3, 9), (9, 9), (12, 12), (21, 21)],
)
def test_quiet_hours(hour, expected_hour):
    moment = datetime(2026, 3, 4, hour, 0, tzinfo=ZoneInfo(TZ))
    assert apply_quiet_hours(moment, TZ).hour == expected_hour
