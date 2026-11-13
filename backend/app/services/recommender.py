import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.links import visible_url
from app.services.rag import Hit

SHORT_FORMATS = {"article", "template", "calculator", "term", "lesson"}
COURSE_HINT = re.compile(r"курс|обуч|научи|с нуля|систем|пошагов|разобраться|план", re.I)

STAGE_MAP = {"idea": "start", "start": "start", "running": "growth", "growth": "growth"}

WEIGHTS = {"sim": 0.40, "topic": 0.20, "stage": 0.15, "format": 0.10, "popularity": 0.10, "co": 0.05}


@dataclass
class Rec:
    ext_id: str
    kind: str
    title: str
    url: str | None
    is_paid: bool
    description: str | None
    price: int | None
    reason: str
    score: float


def wants_course(query: str) -> bool:
    return bool(COURSE_HINT.search(query))


def topic_match(topics: list[str], query: str, profile: dict) -> float:
    haystack = (query + " " + (profile.get("industry") or "") + " " + (profile.get("main_task") or "")).lower()
    if not topics:
        return 0.0
    hits = sum(1 for t in topics if t.strip().lower()[:6] and t.strip().lower()[:6] in haystack)
    return min(1.0, hits / 2)


def stage_match(stages: list[str], profile: dict) -> float:
    mapped = STAGE_MAP.get(profile.get("stage") or "")
    if mapped is None:
        return 0.5
    if mapped in stages:
        return 1.0
    return 0.6 if "any" in stages else 0.2


def stage_fits(hit: Hit, profile: dict) -> bool:
    mapped = STAGE_MAP.get(profile.get("stage") or "")
    if mapped is None or not hit.stage or "any" in hit.stage:
        return True
    return mapped in hit.stage


def format_fit(fmt: str | None, kind: str, course_wanted: bool) -> float:
    is_course = kind == "course"
    if course_wanted:
        return 1.0 if is_course else 0.4
    if fmt in SHORT_FORMATS or kind in {"article", "document", "calculator", "glossary"}:
        return 1.0
    return 0.3 if is_course else 0.6


def score_hit(hit: Hit, query: str, profile: dict, co_score: float = 0.0) -> float:
    parts = {
        "sim": max(0.0, min(1.0, hit.cos)),
        "topic": topic_match(hit.topics, query, profile),
        "stage": stage_match(hit.stage, profile),
        "format": format_fit(hit.format, hit.kind, wants_course(query)),
        "popularity": hit.popularity,
        "co": co_score,
    }
    return sum(WEIGHTS[k] * v for k, v in parts.items())


def build_reason(hit: Hit, profile: dict, topic: str | None) -> str:
    bits = []
    if topic:
        bits.append(f"вы спрашивали про «{topic}»")
    if profile.get("stage") in {"start", "idea"}:
        bits.append("вы на старте")
    elif profile.get("stage") in {"running", "growth"}:
        bits.append("у вас уже работающий бизнес")
    if profile.get("industry"):
        bits.append(f"сфера — {profile['industry']}")
    if not bits:
        bits.append("это популярный материал по вашей теме")
    return "Потому что " + ", ".join(bits)


def pick(
    scored: list[tuple[Hit, float]],
    profile: dict,
    topic: str | None,
    paid_allowed: bool,
    rejected: set[str],
    limit: int = 3,
) -> list[Rec]:
    result: list[Rec] = []
    paid_taken = False
    for hit, score in sorted(scored, key=lambda x: x[1], reverse=True):
        if hit.ext_id in rejected:
            continue
        if hit.is_paid:
            if not paid_allowed or paid_taken:
                continue
            paid_taken = True
        result.append(
            Rec(
                ext_id=hit.ext_id, kind=hit.kind, title=hit.title, url=hit.url, is_paid=hit.is_paid,
                description=hit.description, price=hit.price, reason=build_reason(hit, profile, topic), score=score,
            )
        )
        if len(result) >= limit:
            break
    return result


async def co_occurrence(session: AsyncSession, anchor_ext_id: str, candidates: list[str]) -> dict[str, float]:
    if not candidates:
        return {}
    rows = await session.execute(
        text(
            "SELECT b.material_ext_id AS ext_id, COUNT(DISTINCT b.ext_user_id) AS n "
            "FROM interactions a JOIN interactions b ON a.ext_user_id = b.ext_user_id "
            "WHERE a.material_ext_id = :anchor AND b.material_ext_id = ANY(:cands) "
            "AND b.material_ext_id <> :anchor GROUP BY b.material_ext_id"
        ),
        {"anchor": anchor_ext_id, "cands": candidates},
    )
    counts = {r.ext_id: r.n for r in rows}
    top = max(counts.values(), default=0)
    return {k: v / top for k, v in counts.items()} if top else {}


async def rejected_recently(session: AsyncSession, user_id, days: int = 14) -> set[str]:
    rows = await session.execute(
        text(
            "SELECT DISTINCT material_ext_id FROM recs_shown WHERE user_id = :u AND reaction = 'down' "
            "AND created_at > now() - make_interval(days => :d)"
        ),
        {"u": user_id, "d": days},
    )
    return {r.material_ext_id for r in rows}


async def popular(session: AsyncSession, stage: str | None, limit: int = 3) -> list[Hit]:
    mapped = STAGE_MAP.get(stage or "")
    rows = await session.execute(
        text(
            "SELECT ext_id, kind, title, url, is_paid, description, topics, stage, format, popularity, price "
            "FROM materials WHERE kind IN ('course','article','document','calculator') "
            "AND (:s IS NULL OR :s = ANY(stage) OR 'any' = ANY(stage)) "
            "ORDER BY is_paid ASC, popularity DESC LIMIT :n"
        ),
        {"s": mapped, "n": limit},
    )
    return [
        Hit(
            ext_id=r.ext_id, kind=r.kind, title=r.title, url=visible_url(r.kind, r.url), is_paid=r.is_paid, description=r.description,
            topics=list(r.topics or []), stage=list(r.stage or []), format=r.format, popularity=r.popularity,
            price=r.price, chunk="", cos=0.0, fts=0.0, score=r.popularity,
        )
        for r in rows
    ]


async def recommend(
    session: AsyncSession,
    user_id,
    hits: list[Hit],
    query: str,
    profile: dict,
    topic: str | None,
    paid_allowed: bool,
    exclude: set[str] | None = None,
) -> list[Rec]:
    rejected = await rejected_recently(session, user_id) | (exclude or set())
    fitting = [h for h in hits if stage_fits(h, profile)]
    hits = fitting if len(fitting) >= 2 else hits
    if not hits:
        cold = await popular(session, profile.get("stage"))
        return pick([(h, h.score) for h in cold], profile, topic, paid_allowed, rejected)
    co = await co_occurrence(session, hits[0].ext_id, [h.ext_id for h in hits])
    scored = [(h, score_hit(h, query, profile, co.get(h.ext_id, 0.0))) for h in hits]
    return pick(scored, profile, topic, paid_allowed, rejected)
