import json
from pathlib import Path

import pytest

from app.services.intent import asks_paid_retell, rule_intent

DATA = json.loads((Path(__file__).resolve().parents[2] / "data" / "test" / "rag_questions.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("question", DATA["paid_provocations"])
def test_all_paid_provocations_detected(question):
    assert asks_paid_retell(question)


def test_ambiguous_share_by_rules():
    hits = [q for q in DATA["ambiguous"] if (r := rule_intent(q)) and r.intent == "ambiguous"]
    assert len(hits) / len(DATA["ambiguous"]) >= 0.8


def test_answerable_not_intercepted_by_rules():
    assert [q["q"] for q in DATA["answerable"] if rule_intent(q["q"])] == []


def test_out_of_scope_not_intercepted_by_rules():
    assert [q for q in DATA["out_of_scope"] if rule_intent(q)] == []


@pytest.mark.parametrize(
    "text",
    ["Сколько стоит курс?", "Что такое УСН?", "Как платить налоги меньше", "Как открыть ИП?"],
)
def test_normal_questions_are_not_paid_retell(text):
    assert not asks_paid_retell(text)


def test_dataset_sizes_match_spec():
    assert len(DATA["answerable"]) >= 40
    assert len(DATA["ambiguous"]) >= 10
    assert len(DATA["out_of_scope"]) >= 10
    assert len(DATA["paid_provocations"]) >= 10
