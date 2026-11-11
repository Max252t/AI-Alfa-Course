from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.models import Profile, User
from app.services import flows
from app.services.schedule import Schedule


@pytest.mark.parametrize("zone", list(flows.TZ_OPTIONS))
async def test_timezone_selection_preserves_explicit_date(zone, monkeypatch):
    moment = datetime(2026, 12, 15, 15, 30, tzinfo=ZoneInfo("Europe/Moscow"))
    user = User(tz="Europe/Moscow", state={"rem": {
        "type": "custom", "schedule": flows.sched_to_dict(
            Schedule(run_at=moment, send_time="15:30")
        ),
    }})
    monkeypatch.setattr(flows, "next_step", AsyncMock())
    now = datetime(2026, 11, 11, 12, tzinfo=ZoneInfo("UTC"))
    await flows.flow_callback(None, user, Profile(), f"rf:tz:{zone}", now)
    actual = flows.sched_from_dict(user.state["rem"]["schedule"])
    assert actual.run_at == moment.replace(tzinfo=ZoneInfo(zone))
    assert actual.send_time == "15:30"
