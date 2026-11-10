import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from app.db import SessionLocal
from app.services.rag import search

DATA = Path(__file__).resolve().parents[1] / "data" / "test" / "rag_questions.json"


def source_matches(hits, keywords: list[str], top: int = 3) -> bool:
    for hit in hits[:top]:
        haystack = (hit.title + " " + " ".join(hit.topics)).lower()
        if any(k.lower() in haystack for k in keywords):
            return True
    return False


async def paid_leaks(session) -> int:
    row = await session.execute(
        text(
            "SELECT COUNT(*) FROM chunks c JOIN materials m ON m.id = c.material_id "
            "WHERE m.is_paid AND length(c.text) > length(m.title) + length(coalesce(m.description, '')) + 10"
        )
    )
    return row.scalar_one()


async def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    async with SessionLocal() as session:
        answerable = []
        for item in data["answerable"]:
            hits = await search(session, item["q"], limit=5, include_paid=False)
            best = hits[0].score if hits else 0.0
            answerable.append((best, source_matches(hits, item["expect_any"])))
        out_scores = []
        for question in data["out_of_scope"]:
            hits = await search(session, question, limit=5, include_paid=False)
            out_scores.append(hits[0].score if hits else 0.0)
        leaks = await paid_leaks(session)

    source_accuracy = sum(ok for _, ok in answerable) / len(answerable)
    print(f"source accuracy (top-3, keyword match): {source_accuracy:.0%}  [target >= 85%]")
    print(f"paid content chunks beyond title+description: {leaks}  [target 0]")
    print()
    print("threshold  answered(answerable)  refused(out_of_scope)")
    best_t, best_score = 0.0, -1.0
    for step in range(30, 91, 5):
        t = step / 100
        coverage = sum(score >= t for score, _ in answerable) / len(answerable)
        refusal = sum(score < t for score in out_scores) / len(out_scores)
        print(f"{t:9.2f}  {coverage:20.0%}  {refusal:21.0%}")
        if min(coverage, refusal) > best_score:
            best_t, best_score = t, min(coverage, refusal)
    print(f"\nrecommended RELEVANCE_THRESHOLD ≈ {best_t:.2f}  [targets: refusals >= 90%]")


if __name__ == "__main__":
    asyncio.run(main())
