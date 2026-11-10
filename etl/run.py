import asyncio
import math
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import Chunk, Interaction, Material
from app.services.embeddings import encode_passages_sync
from etl.mapping import (
    ENTITY_TYPE_KINDS,
    FORMATS,
    PUBLISHED_STATUS,
    build_url,
    can_index_text,
    infer_stages,
    is_paid,
    parse_duration_minutes,
)
from etl.text import chunk_text, html_to_text

BACKUP_DIR = Path(os.environ.get("RAW_DIR", "/app/data/raw"))
SOURCE_DB = "alfa_source"


def find_backup() -> Path:
    candidates = sorted(BACKUP_DIR.glob("*.backup"))
    if not candidates:
        sys.exit(f"Файл .backup не найден в {BACKUP_DIR}. Положите выгрузку кейса в data/raw/.")
    return candidates[0]


def restore_source(backup: Path) -> str:
    url = make_url(get_settings().database_url)
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    base = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username]
    admin = ["psql", *base, "-d", url.database, "-v", "ON_ERROR_STOP=1", "-c"]
    subprocess.run([*admin, f'DROP DATABASE IF EXISTS "{SOURCE_DB}"'], check=True, env=env)
    subprocess.run([*admin, f'CREATE DATABASE "{SOURCE_DB}"'], check=True, env=env)
    result = subprocess.run(
        ["pg_restore", *base, "-d", SOURCE_DB, "--no-owner", "--no-privileges", str(backup)],
        env=env,
    )
    if result.returncode > 1:
        sys.exit("pg_restore завершился с ошибкой")
    return f"postgresql://{url.username}:{url.password}@{url.host}:{url.port or 5432}/{SOURCE_DB}"


async def rows(conn, sql: str) -> list[dict]:
    return [dict(r) for r in await conn.fetch(sql)]


def group_titles(links: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for link in links:
        title = (link["title"] or "").strip()
        key = str(link["entity_id"])
        if title and title not in result[key]:
            result[key].append(title)
    return result


async def load_labels(conn) -> dict[str, list[str]]:
    topics = await rows(
        conn,
        'SELECT cs."EntityId" AS entity_id, t."Title"::text AS title FROM "ContentSettings" cs '
        'JOIN "ContentSettingsTopics" x ON x."ContentSettingsId"=cs."Id" '
        'JOIN "Topics" t ON t."Id"=x."TopicId" WHERE NOT cs."IsDeleted"',
    )
    industries = await rows(
        conn,
        'SELECT cs."EntityId" AS entity_id, i."Title"::text AS title FROM "ContentSettings" cs '
        'JOIN "ContentSettingsIndustries" x ON x."ContentSettingsId"=cs."Id" '
        'JOIN "Industries" i ON i."Id"=x."IndustryId" WHERE NOT cs."IsDeleted"',
    )
    merged = group_titles(topics)
    for key, titles in group_titles(industries).items():
        for title in titles:
            if title not in merged[key]:
                merged[key].append(title)
    return merged


async def embed_items(conn, table: str, fk: str) -> dict[str, str]:
    data = await rows(
        conn,
        f'SELECT "{fk}" AS owner, "HtmlContent"::text AS html FROM "{table}" '
        f'WHERE "HtmlContent" IS NOT NULL ORDER BY "{fk}", "Order"',
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in data:
        piece = html_to_text(item["html"])
        if piece:
            grouped[str(item["owner"])].append(piece)
    return {k: "\n".join(v) for k, v in grouped.items()}


def build_material(kind: str, row: dict, labels: dict, base_url: str, paid: bool, parent: str | None = None) -> Material:
    topics = labels.get(str(row["Id"]), [])
    description = html_to_text(row.get("Description") or row.get("DescriptionExt"))
    return Material(
        ext_id=str(row["Id"]),
        kind=kind,
        title=str(row["Title"]).strip(),
        description=description or None,
        url=build_url(kind, row.get("Url"), base_url),
        is_paid=paid,
        price=row.get("Cost") if kind == "course" else None,
        topics=topics,
        stage=infer_stages(topics),
        format=FORMATS[kind],
        duration_min=parse_duration_minutes(row.get("Duration")),
        parent_ext_id=parent,
    )


async def collect_materials(conn, base_url: str) -> tuple[list[Material], dict[str, str]]:
    labels = await load_labels(conn)
    tariffs = {str(r["CourseId"]) for r in await rows(conn, 'SELECT "CourseId" FROM "CourseTariffBindings"')}
    article_text = await embed_items(conn, "ArticleEmbedItems", "ArticleId")
    document_text = await embed_items(conn, "DocumentEmbedItems", "DocumentId")
    glossary_text = await embed_items(conn, "GlossaryEmbedItems", "GlossaryId")
    lesson_text = await embed_items(conn, "LessonEmbedItems", "LessonId")

    materials: list[Material] = []
    texts: dict[str, str] = {}
    published = f"\"StatusId\"='{PUBLISHED_STATUS}' AND NOT \"IsDeleted\""

    for row in await rows(conn, f'SELECT * FROM "Articles" WHERE {published}'):
        paid = is_paid("article", row)
        m = build_material("article", row, labels, base_url, paid)
        materials.append(m)
        if can_index_text(paid):
            texts[m.ext_id] = article_text.get(m.ext_id) or html_to_text(row.get("Content"))

    course_rows = await rows(conn, f'SELECT * FROM "Courses" WHERE {published}')
    paid_courses: dict[str, bool] = {}
    course_materials: dict[str, Material] = {}
    for row in course_rows:
        cid = str(row["Id"])
        paid = is_paid("course", row, cid in tariffs)
        paid_courses[cid] = paid
        m = build_material("course", row, labels, base_url, paid)
        course_materials[cid] = m
        materials.append(m)
        if can_index_text(paid):
            extra = html_to_text(row.get("DescriptionAdditional")) + "\n" + html_to_text(row.get("Target"))
            texts[m.ext_id] = (m.description or "") + "\n" + extra

    bindings = await rows(
        conn, 'SELECT "CourseId", "LessonId", "Order" FROM "CourseLessonBindings" WHERE NOT "IsDeleted" ORDER BY "Order"'
    )
    lesson_course: dict[str, str] = {}
    for b in bindings:
        lesson_course.setdefault(str(b["LessonId"]), str(b["CourseId"]))

    for row in await rows(conn, 'SELECT * FROM "Lessons" WHERE NOT "IsDeleted" AND NOT "IsGroup"'):
        lid = str(row["Id"])
        cid = lesson_course.get(lid)
        if cid is None or cid not in course_materials or paid_courses.get(cid, True):
            continue
        course = course_materials[cid]
        m = Material(
            ext_id=lid,
            kind="lesson",
            title=str(row["Title"]).strip(),
            description=html_to_text(row.get("Description")) or None,
            url=course.url,
            is_paid=False,
            topics=course.topics,
            stage=course.stage,
            format="lesson",
            duration_min=parse_duration_minutes(row.get("Duration")),
            parent_ext_id=cid,
        )
        materials.append(m)
        texts[lid] = lesson_text.get(lid) or html_to_text(row.get("Content"))

    for row in await rows(conn, f'SELECT * FROM "Documents" WHERE {published}'):
        m = build_material("document", row, labels, base_url, False)
        materials.append(m)
        texts[m.ext_id] = document_text.get(m.ext_id, "")

    for row in await rows(conn, f'SELECT * FROM "Webinars" WHERE {published}'):
        m = build_material("webinar", row, labels, base_url, False)
        materials.append(m)
        texts[m.ext_id] = (m.description or "") + "\n" + html_to_text(row.get("DescriptionExt"))

    for row in await rows(conn, f'SELECT * FROM "Podcasts" WHERE {published}'):
        paid = is_paid("podcast", row)
        m = build_material("podcast", row, labels, base_url, paid)
        materials.append(m)
        if can_index_text(paid):
            texts[m.ext_id] = (m.description or "") + "\n" + html_to_text(row.get("DescriptionExt"))

    for row in await rows(conn, f'SELECT * FROM "Glossary" WHERE {published}'):
        m = build_material("glossary", row, labels, base_url, False)
        materials.append(m)
        texts[m.ext_id] = glossary_text.get(m.ext_id) or (m.description or "")

    for row in await rows(conn, 'SELECT * FROM "Calculators" WHERE NOT "IsDeleted"'):
        m = build_material("calculator", row, labels, base_url, False)
        materials.append(m)
        texts[m.ext_id] = m.description or ""

    return materials, texts


async def collect_interactions(conn, known: set[str]) -> list[Interaction]:
    items: list[Interaction] = []
    course_users = await rows(conn, 'SELECT * FROM "CourseUserBindings" WHERE NOT "IsDeleted"')
    cub_course: dict[str, str] = {}
    for r in course_users:
        cid = str(r["CourseId"])
        cub_course[str(r["Id"])] = cid
        if cid not in known:
            continue
        user = str(r["UserId"])
        items.append(Interaction(ext_user_id=user, material_ext_id=cid, type="course_start", created_at=r["Created"]))
        if r["IsCompleted"]:
            items.append(
                Interaction(ext_user_id=user, material_ext_id=cid, type="course_complete", created_at=r["Completed"])
            )
        if r["IsPaid"]:
            items.append(
                Interaction(ext_user_id=user, material_ext_id=cid, type="course_paid", created_at=r["BuyingDate"])
            )
    user_of = {str(r["Id"]): str(r["UserId"]) for r in course_users}
    for r in await rows(conn, 'SELECT * FROM "CourseUserLessonBindings"'):
        cub = str(r["CourseUserId"])
        cid = cub_course.get(cub)
        if cid is None or cid not in known:
            continue
        items.append(
            Interaction(
                ext_user_id=user_of[cub],
                material_ext_id=cid,
                type="lesson_complete" if r["Completed"] else "lesson_start",
                created_at=r["Completed"] or r["Created"],
            )
        )
    for r in await rows(conn, 'SELECT * FROM "UserRatings" WHERE NOT "IsDeleted"'):
        eid = str(r["EntityId"])
        if eid not in known:
            continue
        items.append(
            Interaction(
                ext_user_id=str(r["UserId"]) if r["UserId"] else None,
                material_ext_id=eid,
                type="rating",
                value=float(r["Value"]),
                created_at=r["Created"],
            )
        )
    return items


def compute_popularity(materials: list[Material], interactions: list[Interaction]) -> None:
    counts: dict[str, int] = defaultdict(int)
    for item in interactions:
        counts[item.material_ext_id] += 1
    top = max(counts.values(), default=1)
    for m in materials:
        m.popularity = math.log1p(counts.get(m.ext_id, 0)) / math.log1p(top)


def build_chunk_rows(materials: list[Material], texts: dict[str, str]) -> list[tuple[Material, str]]:
    pending: list[tuple[Material, str]] = []
    for m in materials:
        if m.is_paid:
            pieces = [f"{m.title}. {m.description or ''}".strip()]
        else:
            body = texts.get(m.ext_id, "")
            pieces = chunk_text(body) or [f"{m.title}. {m.description or ''}".strip()]
            pieces = [f"{m.title}. {p}" for p in pieces]
        pending.extend((m, p) for p in pieces if p)
    return pending


async def write_all(session: AsyncSession, materials, interactions, pending) -> None:
    await session.execute(delete(Chunk))
    await session.execute(delete(Material))
    await session.execute(delete(Interaction).where(Interaction.user_id.is_(None)))
    session.add_all(materials)
    await session.flush()
    by_ext = {m.ext_id: m for m in materials}
    batch = 64
    for start in range(0, len(pending), batch):
        part = pending[start : start + batch]
        vectors = await asyncio.to_thread(encode_passages_sync, [p for _, p in part])
        session.add_all(
            Chunk(material_id=by_ext[m.ext_id].id, text=p, embedding=v) for (m, p), v in zip(part, vectors)
        )
        await session.flush()
        print(f"chunks: {min(start + batch, len(pending))}/{len(pending)}", flush=True)
    session.add_all(interactions)
    await session.commit()
    await session.execute(text("ANALYZE chunks"))


async def main() -> None:
    backup = find_backup()
    print(f"restore {backup.name}", flush=True)
    dsn = await asyncio.to_thread(restore_source, backup)
    conn = await asyncpg.connect(dsn)
    try:
        materials, texts = await collect_materials(conn, get_settings().platform_base_url)
        known = {m.ext_id for m in materials}
        interactions = await collect_interactions(conn, known)
    finally:
        await conn.close()
    compute_popularity(materials, interactions)
    pending = build_chunk_rows(materials, texts)
    paid_leak = [p for m, p in pending if m.is_paid and len(p) > len(m.title) + len(m.description or "") + 5]
    assert not paid_leak, "платный контент попал в индекс"
    print(f"materials={len(materials)} interactions={len(interactions)} chunks={len(pending)}", flush=True)
    async with SessionLocal() as session:
        await write_all(session, materials, interactions, pending)
    print("done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
