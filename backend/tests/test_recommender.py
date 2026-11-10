from app.services.rag import Hit, combine, fallback_answer, format_sources, relevant, to_tsquery
from app.services.recommender import pick, score_hit, wants_course


def make_hit(ext_id="a", paid=False, kind="article", fmt="article", cos=0.8, topics=None, stage=None, pop=0.5):
    return Hit(
        ext_id=ext_id, kind=kind, title=f"T{ext_id}", url=f"https://x/{ext_id}", is_paid=paid, description="d",
        topics=topics or [], stage=stage or ["any"], format=fmt, popularity=pop, price=None,
        chunk="c", cos=cos, fts=0.0, score=cos,
    )


def test_tsquery_or_and_dedup():
    assert to_tsquery("Как выбрать режим режим для ИП?") == "как | выбрать | режим | для"


def test_combine_weights():
    assert combine(1.0, 1.0) == 1.0
    assert round(combine(0.5, 0.0), 2) == 0.35
    assert combine(0.9, 0.4, has_vector=False) == 0.4


def test_relevant_threshold():
    hits = [make_hit("a", cos=0.9), make_hit("b", cos=0.2)]
    assert [h.ext_id for h in relevant(hits, 0.5)] == ["a"]


def test_fallback_lists_materials():
    text = fallback_answer([make_hit("a"), make_hit("b")])
    assert "Ta" in text and "https://x/b" in text


def test_sources_numbered():
    assert format_sources([make_hit("a")]).startswith("[1] Ta")


def test_course_hint():
    assert wants_course("хочу научиться бухгалтерии с нуля")
    assert not wants_course("какая ставка по УСН")


def test_start_stage_boosts_start_material():
    start = make_hit("s", stage=["start"])
    other = make_hit("o", stage=["growth"])
    profile = {"stage": "start"}
    assert score_hit(start, "q", profile) > score_hit(other, "q", profile)


def test_pick_one_paid_max_and_respects_gate():
    scored = [
        (make_hit("p1", paid=True, kind="course"), 0.9),
        (make_hit("p2", paid=True, kind="course"), 0.8),
        (make_hit("f1"), 0.7),
        (make_hit("f2"), 0.6),
    ]
    allowed = pick(scored, {}, "налоги", True, set())
    assert sum(r.is_paid for r in allowed) == 1
    blocked = pick(scored, {}, "налоги", False, set())
    assert not any(r.is_paid for r in blocked)


def test_pick_excludes_rejected_and_limits():
    scored = [(make_hit(str(i)), 1 - i / 10) for i in range(6)]
    result = pick(scored, {}, None, False, {"0"})
    assert len(result) == 3
    assert "0" not in [r.ext_id for r in result]


def test_reason_mentions_context():
    scored = [(make_hit("a"), 0.9)]
    rec = pick(scored, {"stage": "start", "industry": "общепит"}, "налоги", False, set())[0]
    assert "налоги" in rec.reason and "на старте" in rec.reason and "общепит" in rec.reason
