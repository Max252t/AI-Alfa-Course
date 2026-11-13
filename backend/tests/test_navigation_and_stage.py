from unittest.mock import AsyncMock

import pytest

from app.models import Profile, User
from app.schemas import Button, CallbackRequest, ChatResponse
from app.services import flows
from app.services import orchestrator
from app.services.orchestrator import (
    BACK_BUTTON,
    EXAMPLES,
    EXAMPLES_RUNNING,
    example_buttons,
    examples_for,
    go_back,
    remember,
)
from app.services.rag import Hit
from app.services.recommender import stage_fits


def reply(text):
    return ChatResponse(text=text, buttons=[[Button(text="👍", data="fb:up")]])


def has_back(response):
    return any(b.data == BACK_BUTTON.data for row in response.buttons for b in row)


def make_hit(stage):
    return Hit(
        ext_id="x", kind="article", title="t", url=None, is_paid=False, description=None, topics=[],
        stage=stage, format=None, popularity=0.0, price=None, chunk="", cos=0.5, fts=0.0, score=0.5,
    )


def test_first_answer_has_back_button_to_menu():
    user = User(state={})
    assert has_back(remember(user, reply("a")))
    menu = go_back(user, None)
    assert "начало диалога" in menu.text
    assert menu.buttons


def test_second_answer_has_back_and_back_restores_first():
    user = User(state={})
    remember(user, reply("a"))
    second = remember(user, reply("b"))
    assert has_back(second)
    restored = go_back(user, None)
    assert restored.text == "a"
    assert has_back(restored)


def test_back_chain_and_start_of_dialogue():
    user = User(state={})
    for text in ("a", "b", "c"):
        remember(user, reply(text))
    assert go_back(user, None).text == "b"
    assert go_back(user, None).text == "a"
    assert "начало диалога" in go_back(user, None).text


def test_history_is_limited():
    user = User(state={})
    for i in range(20):
        remember(user, reply(str(i)))
    assert len(user.state["nav"]) <= 6


@pytest.mark.parametrize("idx", range(4))
async def test_clarification_buttons_work_after_back(monkeypatch, idx):
    user = User(state={})
    options = ["Бизнес-план", "Регистрация бизнеса", "Поиск финансирования", "Маркетинг"]
    pending = {"question": "С чего начать свой бизнес?", "options": options}
    user.state = {"pending": pending}
    remember(user, ChatResponse(text="Уточните", buttons=[[
        Button(text=option, data=f"clar:{i}") for i, option in enumerate(options)
    ]]))
    monkeypatch.setattr(orchestrator, "get_user", AsyncMock(return_value=user))
    monkeypatch.setattr(orchestrator, "get_profile", AsyncMock(return_value=Profile()))
    chat = AsyncMock(return_value=reply("Ответ"))
    monkeypatch.setattr(orchestrator, "handle_chat", chat)

    await orchestrator.handle_callback(None, CallbackRequest(tg_id=1, chat_id=1, data="clar:1"))
    assert "pending" not in user.state
    remember(user, reply("Регистрация бизнеса"))
    restored = go_back(user, None)
    assert restored.buttons[0][idx].data == f"clar:{idx}"
    await orchestrator.handle_callback(None, CallbackRequest(tg_id=1, chat_id=1, data=f"clar:{idx}"))
    assert chat.await_args.args[1].text == f"{pending['question']} — {options[idx]}"
    assert chat.await_count == 2


def test_back_restores_each_clarification_context():
    user = User(state={"pending": {"question": "Первый", "options": ["А"]}})
    remember(user, reply("Первый"))
    user.state = {**user.state, "pending": {"question": "Второй", "options": ["Б"]}}
    remember(user, reply("Второй"))
    go_back(user, None)
    assert user.state["pending"] == {"question": "Первый", "options": ["А"]}
    go_back(user, None)
    assert "pending" not in user.state


def test_examples_depend_on_stage():
    assert examples_for("running") == EXAMPLES_RUNNING
    assert examples_for("growth") == EXAMPLES_RUNNING
    assert examples_for("start") == EXAMPLES
    assert examples_for(None) == EXAMPLES
    labels = [b.text for row in example_buttons("running") for b in row]
    assert not any("С чего начать" in label for label in labels)


def test_start_only_materials_do_not_fit_running_business():
    assert not stage_fits(make_hit(["start"]), {"stage": "running"})
    assert stage_fits(make_hit(["start", "growth"]), {"stage": "running"})
    assert stage_fits(make_hit(["any"]), {"stage": "running"})
    assert stage_fits(make_hit(["start"]), {"stage": None})
    assert stage_fits(make_hit(["start"]), {"stage": "idea"})


def test_timezone_label_shows_offset():
    assert flows.tz_label("Europe/Moscow") == "Москва, UTC+3"
    assert flows.tz_label("Asia/Yekaterinburg") == "Екатеринбург, UTC+5"
    assert flows.tz_label("Asia/Vladivostok") == "Владивосток, UTC+10"
