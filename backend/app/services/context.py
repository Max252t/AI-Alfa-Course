from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import DialogTurn, Event, Profile, User
from app.services.links import hash_tg_id
from app.services.profile_rules import SLOTS


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_user(session: AsyncSession, tg_id: int, chat_id: int | None = None) -> User:
    settings = get_settings()
    digest = hash_tg_id(tg_id, settings.id_hash_salt)
    result = await session.execute(select(User).where(User.tg_id_hash == digest))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(tg_id_hash=digest, chat_id=chat_id or tg_id, tz=settings.default_tz, state={})
        session.add(user)
        await session.flush()
        session.add(Profile(user_id=user.id, slot_confidence={}))
        await session.flush()
        await log_event(session, user.id, "user_created", {})
    if chat_id and user.chat_id != chat_id:
        user.chat_id = chat_id
    user.last_active_at = utcnow()
    return user


async def get_profile(session: AsyncSession, user: User) -> Profile:
    profile = await session.get(Profile, user.id)
    if profile is None:
        profile = Profile(user_id=user.id, slot_confidence={})
        session.add(profile)
        await session.flush()
    return profile


def profile_dict(profile: Profile) -> dict:
    return {slot: getattr(profile, slot) for slot in SLOTS}


def apply_slots(profile: Profile, slots: dict[str, str], confidence: float) -> dict[str, str]:
    changed = {}
    conf = dict(profile.slot_confidence or {})
    for slot, value in slots.items():
        if slot not in SLOTS or not value:
            continue
        if getattr(profile, slot) == value:
            continue
        if getattr(profile, slot) and conf.get(slot, 0) > confidence:
            continue
        setattr(profile, slot, value)
        conf[slot] = confidence
        changed[slot] = value
    if changed:
        profile.slot_confidence = conf
        profile.updated_at = utcnow()
    return changed


def set_state(user: User, **values) -> None:
    user.state = {**(user.state or {}), **values}


def clear_keys(user: User, *keys: str) -> None:
    user.state = {k: v for k, v in (user.state or {}).items() if k not in keys}


async def log_event(session: AsyncSession, user_id, name: str, payload: dict | None = None) -> None:
    session.add(Event(user_id=user_id, name=name, payload=payload or {}))


async def add_turn(session: AsyncSession, user_id, role: str, text: str, intent: str | None = None) -> None:
    session.add(DialogTurn(user_id=user_id, role=role, text_masked=text[:2000], intent=intent))
    await session.flush()


async def recent_history(session: AsyncSession, user_id, limit: int = 6) -> list[str]:
    result = await session.execute(
        select(DialogTurn).where(DialogTurn.user_id == user_id).order_by(DialogTurn.id.desc()).limit(limit)
    )
    turns = list(result.scalars())[::-1]
    return [f"{'Пользователь' if t.role == 'user' else 'Бот'}: {t.text_masked}" for t in turns]
