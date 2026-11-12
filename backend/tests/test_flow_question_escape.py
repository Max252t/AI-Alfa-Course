from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.models import Profile, User
from app.services import flows

NOW = datetime(2026, 11, 12, 12, tzinfo=ZoneInfo("UTC"))


def make_user(step):
    return User(tz="Europe/Moscow", state={"flow": "reminder", "rem": {"type": "custom", "step": step, "tries": 0}})


@pytest.mark.parametrize("text", ["с чего начать свой бизнес?", "как выбрать налоговый режим для кофейни"])
async def test_question_leaves_reminder_flow(text):
    user = make_user("when")
    assert await flows.flow_text(None, user, Profile(), text, NOW) is None
    assert "rem" not in user.state
    assert "flow" not in user.state


async def test_short_garbage_still_gets_hint_first():
    user = make_user("when")
    reply = await flows.flow_text(None, user, Profile(), "хм", NOW)
    assert reply is not None
    assert user.state["rem"]["tries"] == 1
