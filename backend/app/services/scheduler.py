import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Reminder, User
from app.schemas import Button
from app.services import tax_calendar as tc
from app.services.context import log_event, utcnow
from app.services.flows import reminder_link_material
from app.services.links import with_utm
from app.services.notify import send_message
from app.services.reminders import compute_next_run
from app.services.schedule import apply_quiet_hours

log = logging.getLogger(__name__)


def next_allowed_slot(now: datetime, user: User) -> datetime:
    local = now.astimezone(ZoneInfo(user.tz))
    target = (local + timedelta(days=1)).replace(hour=user.quiet_to, minute=0, second=0, microsecond=0)
    return target


def daily_limit_hit(now: datetime, user: User) -> bool:
    if user.last_proactive_at is None:
        return False
    zone = ZoneInfo(user.tz)
    return user.last_proactive_at.astimezone(zone).date() == now.astimezone(zone).date()


async def build_text(session: AsyncSession, r: Reminder, user: User) -> str:
    material = await reminder_link_material(session, r)
    lines = []
    if r.type == "tax" and r.tax_event_id:
        event = tc.get_event(r.tax_event_id)
        title = event.title if event else r.title
        lines.append(f"⏰ Скоро срок: {title}.")
        lines.append(tc.disclaimer())
    elif r.type == "learning":
        lines.append(f"⏰ {r.title}.")
    else:
        lines.append(f"⏰ Напоминание: {r.title}.")
    if material and material.url:
        content = "tax" if r.type == "tax" else "reminder"
        link = with_utm(material.url, content, material.ext_id, user.tg_id_hash)
        lines.append(f"Материал по теме: {material.title}\n{link}")
    return "\n".join(lines)


def reminder_buttons(r: Reminder) -> list[list[Button]]:
    return [
        [
            Button(text="Отложить на день", data=f"rem:snooze:{r.id}"),
            Button(text="Отключить", data=f"rem:toggle:{r.id}"),
        ]
    ]


async def dispatch_due() -> int:
    sent = 0
    now = utcnow()
    async with SessionLocal() as session:
        result = await session.execute(
            select(Reminder).where(Reminder.active.is_(True), Reminder.next_run_at <= now).limit(100)
        )
        for r in result.scalars():
            user = await session.get(User, r.user_id)
            if user is None or user.chat_id is None:
                r.active = False
                continue
            if not user.notifications_enabled:
                r.next_run_at = next_allowed_slot(now, user)
                continue
            shifted = apply_quiet_hours(now, user.tz, user.quiet_from, user.quiet_to)
            if shifted > now:
                r.next_run_at = shifted
                continue
            if daily_limit_hit(now, user):
                r.next_run_at = next_allowed_slot(now, user)
                continue
            ok = await send_message(user.chat_id, await build_text(session, r, user), reminder_buttons(r))
            if not ok:
                r.next_run_at = now + timedelta(minutes=30)
                continue
            user.last_proactive_at = now
            sent += 1
            await log_event(session, user.id, "reminder_sent", {"type": r.type})
            nxt = compute_next_run(r, now + timedelta(minutes=1), user.tz, user)
            if nxt is None or (r.type != "tax" and not r.freq):
                r.active = False
                r.next_run_at = None
            else:
                r.next_run_at = nxt
        await session.commit()
    return sent


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(dispatch_due, "interval", seconds=60, id="dispatch_due", max_instances=1, coalesce=True)
    scheduler.start()
    return scheduler
