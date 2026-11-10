from datetime import date
from pathlib import Path

import pytest

from app.services import tax_calendar as tc

PATH = str(Path(__file__).resolve().parents[2] / "data" / "tax_calendar.yaml")


def test_every_regime_has_events():
    for regime in tc.REGIME_LABELS:
        assert tc.events_for(regime, None, PATH), regime


def test_usn_ip_events_exclude_ooo_only():
    ids = {e.id for e in tc.events_for("usn_income", "ip", PATH)}
    assert "usn_advance" in ids
    assert "usn_year_ip" in ids
    assert "usn_year_ooo" not in ids


def test_usn_advance_next_due():
    event = tc.get_event("usn_advance", PATH)
    assert tc.next_due(event, date(2026, 1, 10), PATH) == date(2026, 4, 28)
    assert tc.next_due(event, date(2026, 4, 29), PATH) == date(2026, 7, 28)
    assert tc.next_due(event, date(2026, 10, 29), PATH) == date(2027, 4, 28)


def test_weekend_shift():
    event = tc.get_event("usn_advance", PATH)
    shifted = tc.next_due(event, date(2026, 7, 1), PATH)
    assert shifted.weekday() < 5


def test_monthly_rule():
    event = tc.get_event("npd_monthly", PATH)
    due = tc.due_dates(event, 2026)
    assert len(due) == 12
    assert all(d.weekday() < 5 for d in due)


def test_manual_rule_has_no_dates():
    event = tc.get_event("patent_payment", PATH)
    assert tc.due_dates(event, 2026) == []
    assert tc.next_due(event, date(2026, 1, 1), PATH) is None


@pytest.mark.parametrize("event_id", [e.id for e in tc.all_events(PATH)])
def test_events_have_title_and_lead(event_id):
    event = tc.get_event(event_id, PATH)
    assert event.title
    assert event.lead_days >= 0
