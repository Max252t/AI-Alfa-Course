from app.services.pii import contains_pii, mask_pii


def test_masks_phone():
    assert "[телефон]" in mask_pii("Позвоните +7 (916) 123-45-67 пожалуйста")
    assert "[телефон]" in mask_pii("мой номер 89161234567")


def test_masks_email_and_username():
    masked = mask_pii("пишите ivan@example.com или @ivan_petrov")
    assert "ivan@example.com" not in masked
    assert "@ivan_petrov" not in masked


def test_masks_inn_and_card():
    assert "[инн]" in mask_pii("ИНН 7707083893")
    assert "[инн]" in mask_pii("ИНН ИП 500100732259")
    assert "[номер]" in mask_pii("карта 4276 1234 5678 9012")


def test_masks_name_after_introduction():
    assert "Иван" not in mask_pii("Меня зовут Иван Петров, хочу открыть кофейню")


def test_clean_text_unchanged():
    text = "Как выбрать налоговый режим для кофейни?"
    assert mask_pii(text) == text
    assert not contains_pii(text)


async def test_rag_context_is_not_masked_but_question_is():
    from app.services.rag import Hit, generate_answer

    seen = {}

    class Fake:
        async def complete(self, system, user, json_mode=False, temperature=0.2):
            seen["prompt"] = user
            return "ответ [1]"

    hit = Hit(
        ext_id="a", kind="article", title="КБК", url=None, is_paid=False, description=None, topics=[], stage=[],
        format=None, popularity=0.0, price=None, chunk="КБК 18210101011011000110 для платежа", cos=1, fts=1, score=1,
    )
    await generate_answer(Fake(), "мой телефон +7 916 123-45-67", [hit], "неизвестен", [])
    assert "18210101011011000110" in seen["prompt"]
    assert "916" not in seen["prompt"]
