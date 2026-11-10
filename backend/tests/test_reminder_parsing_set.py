import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.schedule import parse_schedule

DATA = Path(__file__).resolve().parents[2] / "data" / "test" / "reminders.json"
TZ = "Europe/Moscow"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=ZoneInfo(TZ))


def check(case: dict) -> list[str]:
    s = parse_schedule(case["text"], NOW, TZ)
    errors = []
    if case.get("once"):
        if s.run_at is None or s.recurring:
            errors.append("expected one-off")
        elif case.get("time") and s.run_at.strftime("%H:%M") != case["time"]:
            errors.append(f"time {s.run_at.strftime('%H:%M')} != {case['time']}")
        return errors
    if s.freq != case.get("freq"):
        errors.append(f"freq {s.freq} != {case.get('freq')}")
    if "weekdays" in case and s.weekdays != case["weekdays"]:
        errors.append(f"weekdays {s.weekdays} != {case['weekdays']}")
    if "interval" in case and s.interval != case["interval"]:
        errors.append(f"interval {s.interval} != {case['interval']}")
    if "time" in case and s.send_time != case["time"]:
        errors.append(f"time {s.send_time} != {case['time']}")
    return errors


def test_schedule_parsing_accuracy_on_test_set():
    cases = json.loads(DATA.read_text(encoding="utf-8"))
    assert len(cases) >= 30
    failures = {c["text"]: e for c in cases if (e := check(c))}
    accuracy = 1 - len(failures) / len(cases)
    assert accuracy >= 0.9, failures
