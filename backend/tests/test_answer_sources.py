from app.services.links import visible_url
from app.services.rag import renumber_citations, strip_urls


def test_citations_are_renumbered_by_first_appearance():
    answer, order = renumber_citations("Сначала план [3]. Затем налоги [1]. Ещё про план [3].", 3)
    assert answer == "Сначала план [1]. Затем налоги [2]. Ещё про план [1]."
    assert order == [3, 1]


def test_unknown_citations_are_removed_and_not_counted():
    answer, order = renumber_citations("Текст [5] и ещё [2].", 3)
    assert answer == "Текст и ещё [1]."
    assert order == [2]


def test_no_citations_returns_empty_order():
    answer, order = renumber_citations("Просто ответ.", 3)
    assert answer == "Просто ответ."
    assert order == []


def test_urls_are_removed_from_model_text():
    cleaned = strip_urls("Смотрите https://fake.example/page и [статью](https://fake.example/a) или www.fake.ru.")
    assert "http" not in cleaned
    assert "www" not in cleaned
    assert "статью" in cleaned


def test_only_verified_kinds_get_links():
    assert visible_url("article", "https://kurs.alfabank.ru/articles/a/") == "https://kurs.alfabank.ru/articles/a/"
    assert visible_url("course", "https://kurs.alfabank.ru/courses/c/") == "https://kurs.alfabank.ru/courses/c/"
    assert visible_url("webinar", "https://kurs.alfabank.ru/webinars/w/") is None
    assert visible_url("article", None) is None
