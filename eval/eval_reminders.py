import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services import tax_calendar as tc
from app.services.schedule import parse_schedule

ROOT = Path(__file__).resolve().parents[1]
TZ = "Europe/Moscow"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=ZoneInfo(TZ))

EXPECTED_TAX_DATES_2026 = {
    "usn_advance": [date(2026, 4, 28), date(2026, 7, 28), date(2026, 10, 28)],
    "usn_year_ooo": [date(2026, 3, 30)],
    "usn_year_ip": [date(2026, 4, 28)],
    "ip_insurance_fixed": [date(2026, 12, 31)],
    "ip_insurance_one_percent": [date(2026, 7, 1)],
}


def check(case: dict) -> list[str]:
    s = parse_schedule(case["text"], NOW, TZ)
    errors = []
    if case.get("once"):
        if s.run_at is None or s.recurring:
            errors.append("expected one-off")
        elif case.get("time") and s.run_at.strftime("%H:%M") != case["time"]:
            errors.append("time")
        return errors
    for key, value in (("freq", case.get("freq")), ("weekdays", case.get("weekdays")), ("interval", case.get("interval"))):
        if value is not None and getattr(s, key) != value:
            errors.append(key)
    if case.get("time") and s.send_time != case["time"]:
        errors.append("time")
    return errors


def main() -> None:
    cases = json.loads((ROOT / "data" / "test" / "reminders.json").read_text(encoding="utf-8"))
    failed = {c["text"]: e for c in cases if (e := check(c))}
    accuracy = 1 - len(failed) / len(cases)
    print(f"schedule parsing: {len(cases) - len(failed)}/{len(cases)} = {accuracy:.0%}  [target >= 90%]")
    for text, errors in failed.items():
        print(f"  ✗ {text}: {errors}")

    tax_failed = 0
    for event_id, expected in EXPECTED_TAX_DATES_2026.items():
        event = tc.get_event(event_id)
        actual = tc.due_dates(event, 2026)
        if actual != expected:
            tax_failed += 1
            print(f"  ✗ tax {event_id}: {actual} != {expected}")
    print(f"tax calendar reference dates: {len(EXPECTED_TAX_DATES_2026) - tax_failed}/{len(EXPECTED_TAX_DATES_2026)}  [target 100%]")
    for regime in tc.REGIME_LABELS:
        for form in ("ip", "ooo"):
            events = tc.events_for(regime, form)
            print(f"  {regime:20s} {form:4s} events: {len(events)}")
    sys.exit(1 if failed and accuracy < 0.9 or tax_failed else 0)


if __name__ == "__main__":
    main()
