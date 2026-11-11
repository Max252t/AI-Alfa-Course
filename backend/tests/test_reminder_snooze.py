from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models import Reminder, User
from app.services import flows


async def test_snooze_reactivates_delivered_one_time_reminder(monkeypatch):
    now = datetime(2026, 11, 11, 12, tzinfo=ZoneInfo("UTC"))
    user = User(id=uuid4(), tz="Europe/Moscow")
    reminder = Reminder(id=uuid4(), user_id=user.id, type="custom", active=False,
                        freq=None, run_at=now - timedelta(minutes=1), next_run_at=None)
    monkeypatch.setattr(flows, "get_reminder", AsyncMock(return_value=reminder))
    session = AsyncMock()
    session.add = Mock()
    await flows.reminder_action(session, user, f"rem:snooze:{reminder.id}", now)
    assert reminder.active is True
    assert reminder.next_run_at == now + timedelta(days=1)
