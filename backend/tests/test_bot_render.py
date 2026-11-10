from bot.render import build_markup, build_text, rec_block


def test_text_without_recs():
    assert build_text({"text": "Привет"}) == "Привет"


def test_rec_block_free_and_paid():
    block = rec_block(
        [
            {"title": "Статья", "url": "https://x/a", "is_paid": False, "reason": "Потому что вы на старте"},
            {"title": "Курс", "url": "https://x/c", "is_paid": True, "benefit": "Разберёте УСН за вечер."},
        ]
    )
    assert "Бесплатно: Статья" in block
    assert "Платный курс: Курс" in block
    assert "Разберёте УСН за вечер." in block


def test_text_is_truncated():
    assert len(build_text({"text": "я" * 9000})) == 4000


def test_markup_rows_and_limits():
    markup = build_markup(
        {
            "text": "x",
            "buttons": [
                [{"text": "A", "data": "a"}, {"text": "B", "data": "b" * 100}],
                [{"text": "Ссылка", "url": "https://x.ru"}],
            ],
        }
    )
    assert len(markup.inline_keyboard) == 2
    assert len(markup.inline_keyboard[0][1].callback_data) == 64
    assert markup.inline_keyboard[1][0].url == "https://x.ru"


def test_no_buttons_no_markup():
    assert build_markup({"text": "x", "buttons": []}) is None
