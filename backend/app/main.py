import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import Event, Material, Profile, Reminder, User
from app.schemas import (
    CallbackRequest,
    ChatRequest,
    ChatResponse,
    ProfileOut,
    ReminderOut,
)
from app.services import flows, orchestrator
from app.services.context import get_profile, get_user, profile_dict, utcnow
from app.services.links import hash_tg_id
from app.services.rag import search
from app.services.reminders import compute_next_run, describe_reminder
from app.services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

HELP_TEXT = (
    "Я помогаю с вопросами о бизнесе по материалам «Альфа-Курса»: налоги, учёт, маркетинг, запуск дела.\n\n"
    "Что можно сделать:\n"
    "• задать вопрос своими словами;\n"
    "• попросить напоминание: «Напоминай каждый понедельник продолжить курс» или «Напомни заплатить налог»;\n"
    "• изменить или отключить напоминание: «Сделай раз в две недели», «Отключи».\n\n"
    "Команды: /profile — что я о вас знаю, /reminders — ваши напоминания, /reset — удалить все данные."
)


async def session_scope():
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Альфа-Наставник", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/start", response_model=ChatResponse)
async def start(req: ChatRequest, session: AsyncSession = Depends(session_scope)):
    return await orchestrator.handle_start(session, req)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, session: AsyncSession = Depends(session_scope)):
    return await orchestrator.handle_chat(session, req)


@app.post("/callback", response_model=ChatResponse)
async def callback(req: CallbackRequest, session: AsyncSession = Depends(session_scope)):
    return await orchestrator.handle_callback(session, req)


class CommandRequest(BaseModel):
    tg_id: int
    chat_id: int | None = None
    name: str


@app.post("/command", response_model=list[ChatResponse])
async def command(req: CommandRequest, session: AsyncSession = Depends(session_scope)):
    user = await get_user(session, req.tg_id, req.chat_id)
    if req.name == "help":
        return [ChatResponse(text=HELP_TEXT)]
    if req.name == "profile":
        return [await orchestrator.profile_response(session, user)]
    if req.name == "reminders":
        return await flows.list_response(session, user)
    raise HTTPException(404, "unknown command")


async def _user_or_404(session: AsyncSession, tg_id: int) -> User:
    digest = hash_tg_id(tg_id, get_settings().id_hash_salt)
    result = await session.execute(select(User).where(User.tg_id_hash == digest))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "user not found")
    return user


@app.get("/users/{tg_id}/profile", response_model=ProfileOut)
async def read_profile(tg_id: int, session: AsyncSession = Depends(session_scope)):
    user = await _user_or_404(session, tg_id)
    return ProfileOut(**profile_dict(await get_profile(session, user)))


@app.patch("/users/{tg_id}/profile", response_model=ProfileOut)
async def patch_profile(tg_id: int, body: ProfileOut, session: AsyncSession = Depends(session_scope)):
    user = await _user_or_404(session, tg_id)
    profile = await get_profile(session, user)
    for slot, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, slot, value)
    return ProfileOut(**profile_dict(profile))


@app.delete("/users/{tg_id}")
async def reset_user(tg_id: int, session: AsyncSession = Depends(session_scope)):
    user = await _user_or_404(session, tg_id)
    await session.execute(delete(Event).where(Event.user_id == user.id))
    await session.delete(user)
    return {"status": "deleted"}


@app.get("/users/{tg_id}/reminders", response_model=list[ReminderOut])
async def read_reminders(tg_id: int, session: AsyncSession = Depends(session_scope)):
    user = await _user_or_404(session, tg_id)
    items = await flows.list_for_user(session, user.id)
    return [
        ReminderOut(
            id=str(r.id),
            type=r.type,
            title=r.title,
            description=describe_reminder(r),
            active=r.active,
            next_run_at=r.next_run_at.isoformat() if r.next_run_at else None,
        )
        for r in items
    ]


class ReminderPatch(BaseModel):
    active: bool | None = None
    frequency: str | None = None


@app.patch("/reminders/{reminder_id}", response_model=ReminderOut)
async def patch_reminder(reminder_id: str, body: ReminderPatch, session: AsyncSession = Depends(session_scope)):
    r = await session.get(Reminder, reminder_id)
    if r is None:
        raise HTTPException(404, "reminder not found")
    user = await session.get(User, r.user_id)
    now = utcnow()
    if body.frequency:
        flows.apply_frequency(r, body.frequency, now, user.tz)
    if body.active is not None:
        r.active = body.active
    r.next_run_at = compute_next_run(r, now, user.tz, user) if r.active else r.next_run_at
    return ReminderOut(
        id=str(r.id), type=r.type, title=r.title, description=describe_reminder(r), active=r.active,
        next_run_at=r.next_run_at.isoformat() if r.next_run_at else None,
    )


@app.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str, session: AsyncSession = Depends(session_scope)):
    r = await session.get(Reminder, reminder_id)
    if r is None:
        raise HTTPException(404, "reminder not found")
    await session.delete(r)
    return {"status": "deleted"}


@app.get("/materials/search")
async def materials_search(q: str, include_paid: bool = False, session: AsyncSession = Depends(session_scope)):
    hits = await search(session, q, limit=8, include_paid=include_paid)
    return [
        {"ext_id": h.ext_id, "title": h.title, "kind": h.kind, "url": h.url, "is_paid": h.is_paid, "score": round(h.score, 3)}
        for h in hits
    ]


@app.get("/stats")
async def stats(session: AsyncSession = Depends(session_scope)):
    async def count(model) -> int:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()

    return {"materials": await count(Material), "users": await count(User), "profiles": await count(Profile)}
