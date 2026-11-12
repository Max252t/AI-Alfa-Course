from unittest.mock import AsyncMock

from app.services.rag import Hit, generate_answer, has_foreign_script, strip_invalid_citations


def make_hit():
    return Hit(
        ext_id="1", kind="article", title="Налоги", url="https://x/1", is_paid=False,
        description=None, topics=[], stage=[], format=None, popularity=0.0, price=None,
        chunk="Текст", cos=0.9, fts=0.5, score=0.8,
    )


def test_detects_chinese_characters():
    assert has_foreign_script("налоговый режим 最合适的翻译")
    assert not has_foreign_script("Налоговый режим для кофейни")


async def test_retries_once_when_answer_has_chinese():
    llm = AsyncMock()
    llm.complete.side_effect = ["режим 为了选择", "Выберите УСН."]
    answer, ok = await generate_answer(llm, "вопрос", [make_hit()], "", [])
    assert ok is True
    assert answer == "Выберите УСН."
    assert llm.complete.await_count == 2


async def test_falls_back_when_chinese_persists():
    llm = AsyncMock()
    llm.complete.side_effect = ["为了选择", "为了选择"]
    answer, ok = await generate_answer(llm, "вопрос", [make_hit()], "", [])
    assert ok is False
    assert "Налоги" in answer


def test_keeps_valid_citations_and_drops_unknown_ones():
    assert strip_invalid_citations("Составьте план [1]. Выберите нишу [5].", 3) == "Составьте план [1]. Выберите нишу."
    assert strip_invalid_citations("Текст [2][3] и [0].", 3) == "Текст [2][3] и."
