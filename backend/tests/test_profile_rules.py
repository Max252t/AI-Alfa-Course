import pytest

from app.services.profile_rules import extract_slots, extract_tax_regime, summarize


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Хочу открыть кофейню, какой режим налогов выбрать?", {"industry": "общепит", "stage": "start", "main_task": "taxes"}),
        ("Я ИП на УСН доходы 6%", {"legal_form": "ip", "tax_regime": "usn_income"}),
        ("мы ООО на упрощёнке доходы минус расходы", {"legal_form": "ooo", "tax_regime": "usn_income_expense"}),
        ("я самозанятый", {"legal_form": "selfemployed", "tax_regime": "npd"}),
        ("работаю на патенте", {"tax_regime": "patent"}),
    ],
)
def test_extract_slots(text, expected):
    slots = extract_slots(text)
    for key, value in expected.items():
        assert slots.get(key) == value


def test_no_false_ip_in_words():
    assert "legal_form" not in extract_slots("как поставить сип-телефонию")


def test_regimes():
    assert extract_tax_regime("перешёл на АУСН") == "ausn"
    assert extract_tax_regime("общая система налогообложения") == "osn"
    assert extract_tax_regime("привет") is None


def test_summary():
    assert summarize({}) == "неизвестен"
    assert "сфера: общепит" in summarize({"industry": "общепит"})
