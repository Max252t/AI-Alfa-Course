from etl.mapping import build_url, can_index_text, infer_stages, is_paid, parse_duration_minutes
from etl.text import chunk_text, html_to_text


def test_html_to_text_strips_tags_and_entities():
    html = "<p>Привет,&nbsp;мир</p><script>x()</script><ul><li>один</li><li>два</li></ul>"
    assert html_to_text(html) == "Привет, мир\nодин\nдва"


def test_html_to_text_empty():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_chunking_overlap_and_size():
    words = [f"w{i}" for i in range(1000)]
    chunks = chunk_text(" ".join(words), size=200, overlap=20)
    assert all(len(c.split()) <= 200 for c in chunks)
    assert chunks[0].split()[-20:] == chunks[1].split()[:20]
    assert chunks[-1].split()[-1] == "w999"


def test_short_text_single_chunk():
    assert chunk_text("один два три") == ["один два три"]
    assert chunk_text("") == []


def test_paid_courses_and_text_gate():
    assert is_paid("course", {"Cost": 3990})
    assert is_paid("course", {"Cost": None}, course_has_tariff=True)
    assert not is_paid("course", {"Cost": None})
    assert not can_index_text(True)
    assert can_index_text(False)


def test_paid_articles_and_podcasts():
    assert is_paid("article", {"IsClosed": True})
    assert not is_paid("article", {"IsClosed": False})
    assert is_paid("podcast", {"Cost": 100, "IsClosed": False})


def test_build_url():
    assert build_url("course", "usn", "https://x.ru/") == "https://x.ru/courses/usn"
    assert build_url("course", "", "https://x.ru") is None


def test_stages_and_duration():
    assert infer_stages(["Старт бизнеса"]) == ["start"]
    assert infer_stages(["Налоги"]) == ["any"]
    assert parse_duration_minutes("1 час 25 минут") == 85
    assert parse_duration_minutes("2,5 часа") == 150
    assert parse_duration_minutes(None) is None
