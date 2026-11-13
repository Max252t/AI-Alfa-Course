import uuid
from datetime import datetime, timezone

import pytest

from app.models import Reminder, User
from app.schemas import CallbackRequest
from app.services import flows, orchestrator

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self, reminder):
        self.reminder = reminder
        self.added = []

    async def get(self, model, key):
        return self.reminder

    def add(self, obj):
        self.added.append(obj)


@pytest.mark.parametrize(
    "text,zone",
    [
        ("Новосибирск", "Asia/Novosibirsk"),
        ("я живу в екатеринбурге", "Asia/Yekaterinburg"),
        ("Europe/Moscow", "Europe/Moscow"),
        ("Владивосток", "Asia/Vladivostok"),
    ],
)
def test_match_timezone(text, zone):
    assert flows.match_timezone(text) == zone


def test_match_timezone_unknown():
    assert flows.match_timezone("Париж") is None


async def test_get_reminder_rejects_invalid_uuid():
    assert await flows.get_reminder(FakeSession(None), User(id=uuid.uuid4()), "not-a-uuid") is None


async def test_malformed_callback_does_not_raise(monkeypatch):
    async def boom(session, req):
        raise ValueError

    monkeypatch.setattr(orchestrator, "dispatch_callback", boom)
    response = await orchestrator.handle_callback(None, CallbackRequest(tg_id=1, data="ex:abc"))
    assert response.text == "Не понял команду."


async def test_enabling_expired_one_time_reminder_stays_off():
    user = User(id=uuid.uuid4(), tz="Europe/Moscow", quiet_from=22, quiet_to=9)
    r = Reminder(
        id=uuid.uuid4(), user_id=user.id, type="custom", title="t", freq=None, weekdays=[], interval=1,
        send_time="10:00", lead_days=0, active=False, run_at=datetime(2026, 3, 1, 10, tzinfo=timezone.utc),
        created_at=NOW,
    )
    session = FakeSession(r)
    response = await flows.reminder_action(session, user, f"rem:toggle:{r.id}", NOW)
    assert r.active is False
    assert "не сработает" in response.text


async def test_timezone_change_recomputes_active_reminders(monkeypatch):
    user = User(id=uuid.uuid4(), tz="Europe/Moscow", quiet_from=22, quiet_to=9, state={})
    r = Reminder(
        id=uuid.uuid4(), user_id=user.id, type="custom", title="t", freq="daily", weekdays=[], interval=1,
        send_time="10:00", lead_days=0, active=True, created_at=NOW, next_run_at=NOW,
    )

    async def fake_list(session, user_id):
        return [r]

    monkeypatch.setattr(flows, "list_for_user", fake_list)
    await flows.change_timezone(object(), user, "Asia/Novosibirsk", {"schedule": None, "type": "custom"}, NOW)
    assert user.tz == "Asia/Novosibirsk"
    assert r.next_run_at != NOW
    assert r.next_run_at.astimezone(flows.ZoneInfo("Asia/Novosibirsk")).hour == 10
