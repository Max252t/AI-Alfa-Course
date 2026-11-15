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


async def test_get_user_reenables_notifications(monkeypatch):
    from app.services import context

    user = User(id=uuid.uuid4(), tg_id_hash="h", chat_id=1, notifications_enabled=False, state={})

    class Result:
        def scalar_one_or_none(self):
            return user

    class Session:
        async def execute(self, stmt):
            return Result()

    got = await context.get_user(Session(), 1, 1)
    assert got.notifications_enabled is True


async def test_expired_patent_reminder_is_not_created(monkeypatch):
    from pathlib import Path

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "tax_calendar_path", str(Path(__file__).resolve().parents[2] / "data" / "tax_calendar.yaml"))
    user = User(id=uuid.uuid4(), tz="Europe/Moscow", quiet_from=22, quiet_to=9, state={})
    draft = {
        "items": [
            {
                "type": "tax", "title": "Оплата патента", "tax_event_id": "patent_payment", "lead_days": 5,
                "send_time": "10:00", "run_at": datetime(2026, 3, 1, 10, tzinfo=timezone.utc).isoformat(),
            }
        ]
    }

    class Session:
        added = []

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            pass

    from app.services.reminders import create_from_draft

    session = Session()
    created = await create_from_draft(session, user, draft, NOW)
    assert created == []
    assert session.added == []


@pytest.mark.parametrize("data", ["rf:regime:" + "x" * 50, "rf:legal:bogus", "rf:regime:bogus"])
async def test_flow_callback_rejects_unknown_values(data):
    user = User(id=uuid.uuid4(), tz="Europe/Moscow", state={"rem": {"type": "tax", "step": "regime"}})
    from app.models import Profile

    profile = Profile(user_id=user.id, slot_confidence={})
    response = await flows.flow_callback(object(), user, profile, data, NOW)
    assert response.text == "Не понял команду."
    assert profile.tax_regime is None and profile.legal_form is None
