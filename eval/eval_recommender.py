import asyncio
import math
from collections import defaultdict

from sqlalchemy import text

from app.db import SessionLocal
from app.services.rag import search
from app.services.recommender import co_occurrence, score_hit

MAX_USERS = 300
K_HIT = 5
K_NDCG = 10


def hit_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if any(item in relevant for item in ranked[:k]) else 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, item in enumerate(ranked[:k]) if item in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


async def load_histories(session) -> dict[str, list[str]]:
    rows = await session.execute(
        text(
            "SELECT i.ext_user_id, i.material_ext_id, MIN(i.created_at) AS first_seen "
            "FROM interactions i JOIN materials m ON m.ext_id = i.material_ext_id AND m.kind = 'course' "
            "WHERE i.ext_user_id IS NOT NULL AND i.type IN ('course_start', 'course_complete', 'lesson_complete') "
            "GROUP BY i.ext_user_id, i.material_ext_id ORDER BY i.ext_user_id, first_seen"
        )
    )
    histories: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        histories[row.ext_user_id].append(row.material_ext_id)
    return {u: items for u, items in histories.items() if len(items) >= 2}


async def main() -> None:
    async with SessionLocal() as session:
        histories = await load_histories(session)
        courses = {
            r.ext_id: r
            for r in await session.execute(text("SELECT ext_id, title, topics, popularity FROM materials WHERE kind = 'course'"))
        }
        users = list(histories.items())[:MAX_USERS]
        ours = {"hit": 0.0, "ndcg": 0.0}
        base = {"hit": 0.0, "ndcg": 0.0}
        popular = {"hit": 0.0, "ndcg": 0.0}
        evaluated = 0
        ranked_popular = [e for e, _ in sorted(courses.items(), key=lambda kv: kv[1].popularity, reverse=True)]
        for _, items in users:
            anchor, relevant = items[0], set(items[1:])
            anchor_row = courses.get(anchor)
            if anchor_row is None:
                continue
            candidates = [e for e in courses if e != anchor]
            hits = await search(session, anchor_row.title, limit=30)
            hits = [h for h in hits if h.kind == "course" and h.ext_id != anchor]
            co = await co_occurrence(session, anchor, candidates)
            scored = {h.ext_id: score_hit(h, anchor_row.title, {}, co.get(h.ext_id, 0.0)) for h in hits}
            for e in candidates:
                scored.setdefault(e, 0.2 * co.get(e, 0.0) + 0.1 * courses[e].popularity)
            ranked_ours = sorted(scored, key=scored.get, reverse=True)
            anchor_topics = set(anchor_row.topics or [])
            ranked_base = sorted(candidates, key=lambda e: -len(anchor_topics & set(courses[e].topics or [])))
            ranked_pop = [e for e in ranked_popular if e != anchor]
            for acc, ranked in ((ours, ranked_ours), (base, ranked_base), (popular, ranked_pop)):
                acc["hit"] += hit_at_k(ranked, relevant, K_HIT)
                acc["ndcg"] += ndcg_at_k(ranked, relevant, K_NDCG)
            evaluated += 1

    if not evaluated:
        print("Недостаточно данных: нет пользователей с двумя и более курсами.")
        return
    print(f"users evaluated: {evaluated}")
    print(f"{'model':28s} Hit@{K_HIT}   NDCG@{K_NDCG}")
    for name, acc in (("baseline: topic match", base), ("popularity", popular), ("our recommender", ours)):
        print(f"{name:28s} {acc['hit'] / evaluated:.3f}   {acc['ndcg'] / evaluated:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
