from datetime import datetime, timezone

import pytest

from app.models import Reminder, User
from app.services import scheduler
from app.services.notify import UserBlocked

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self, user):
        self.user = user
        self.added = []

    async def get(self, model, key):
        return self.user

    def add(self, obj):
        self.added.append(obj)


def make_user(**kwargs):
    defaults = dict(
        chat_id=1, tz="Europe/Moscow", quiet_from=22, quiet_to=9, notifications_enabled=True, last_proactive_at=None
    )
    return User(**{**defaults, **kwargs})


def make_reminder(**kwargs):
    defaults = dict(
        type="custom", title="t", freq="daily", weekdays=[], interval=1, send_time="10:00", lead_days=0, active=True,
        created_at=NOW, next_run_at=NOW,
    )
    return Reminder(**{**defaults, **kwargs})


@pytest.fixture(autouse=True)
def stub_text(monkeypatch):
    async def fake_text(session, r, user):
        return "text"

    monkeypatch.setattr(scheduler, "build_text", fake_text)


def stub_send(monkeypatch, result=True, blocked=False):
    calls = []

    async def fake_send(chat_id, text, buttons=None):
        calls.append(chat_id)
        if blocked:
            raise UserBlocked
        return result

    monkeypatch.setattr(scheduler, "send_message", fake_send)
    return calls


async def test_blocked_user_disables_notifications(monkeypatch):
    stub_send(monkeypatch, blocked=True)
    user, r = make_user(), make_reminder()
    assert await scheduler.process_reminder(FakeSession(user), r, NOW) is False
    assert user.notifications_enabled is False
    assert r.next_run_at > NOW


async def test_failed_send_retries_later(monkeypatch):
    stub_send(monkeypatch, result=False)
    user, r = make_user(), make_reminder()
    assert await scheduler.process_reminder(FakeSession(user), r, NOW) is False
    assert (r.next_run_at - NOW).total_seconds() == 1800


async def test_daily_limit_defers_regular_reminder(monkeypatch):
    calls = stub_send(monkeypatch)
    user, r = make_user(last_proactive_at=NOW), make_reminder()
    assert await scheduler.process_reminder(FakeSession(user), r, NOW) is False
    assert calls == []
    assert r.next_run_at > NOW


async def test_daily_limit_does_not_defer_tax_reminder(monkeypatch):
    calls = stub_send(monkeypatch)
    user = make_user(last_proactive_at=NOW)
    r = make_reminder(type="tax", tax_event_id="missing", freq=None)
    assert await scheduler.process_reminder(FakeSession(user), r, NOW) is True
    assert calls == [1]


async def test_one_time_reminder_deactivated_after_send(monkeypatch):
    stub_send(monkeypatch)
    user, r = make_user(), make_reminder(freq=None)
    assert await scheduler.process_reminder(FakeSession(user), r, NOW) is True
    assert r.active is False and r.next_run_at is None
    assert user.last_proactive_at == NOW
