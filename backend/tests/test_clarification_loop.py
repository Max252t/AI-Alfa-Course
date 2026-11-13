from unittest.mock import AsyncMock, Mock

from app.models import Profile, User
from app.schemas import ChatResponse
from app.services import orchestrator
from app.services.intent import Intent


async def run_route(monkeypatch, force_answer):
    monkeypatch.setattr(
        orchestrator, "classify", AsyncMock(return_value=Intent("ambiguous", clarify_options=["Регистрация", "Налоги"]))
    )
    answer = AsyncMock(return_value=ChatResponse(text="ответ"))
    monkeypatch.setattr(orchestrator, "answer_question", answer)
    response, name = await orchestrator.route(
        Mock(), User(state={}), Profile(), "расскажи подробнее про шаги", [], None, force_answer
    )
    return response, name, answer


async def test_ambiguous_question_asks_for_clarification(monkeypatch):
    response, name, answer = await run_route(monkeypatch, False)
    assert name == "ambiguous"
    assert response.buttons
    answer.assert_not_awaited()


async def test_after_clarification_bot_answers_instead_of_asking_again(monkeypatch):
    response, name, answer = await run_route(monkeypatch, True)
    assert name == "answerable"
    assert response.text == "ответ"
    answer.assert_awaited_once()
