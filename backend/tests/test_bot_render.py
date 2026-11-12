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
    assert 'Бесплатно: <a href="https://x/a">Статья</a>' in block
    assert 'Платный курс: <a href="https://x/c">Курс</a>' in block
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


def test_sources_become_titled_links():
    text = build_text({"text": "Ответ.\n\nИсточники:\n[1] Как составить план — https://x/a?u=1&c=2"})
    assert '[1] <a href="https://x/a?u=1&amp;c=2">Как составить план</a>' in text


def test_more_list_items_become_titled_links():
    text = build_text({"text": "Ещё по теме:\n• Налоги в Китае — https://x/b"})
    assert '• <a href="https://x/b">Налоги в Китае</a>' in text


def test_bare_url_gets_short_label_and_html_is_escaped():
    text = build_text({"text": "Смотрите https://x/c и <b>тег</b>"})
    assert '<a href="https://x/c">ссылка</a>' in text
    assert "&lt;b&gt;тег&lt;/b&gt;" in text
