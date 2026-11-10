import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import dateparser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder, User
from app.services import tax_calendar as tc
from app.services.schedule import Schedule, apply_quiet_hours, describe, next_occurrence

TAX_WORDS = re.compile(r"налог|взнос|ндс|усн|патент|аванс|декларац|ндфл|енп", re.I)
LEARN_WORDS = re.compile(r"курс|урок|обучен|изуч|материал|вебинар|прохожд|учит", re.I)
DISABLE_WORDS = re.compile(r"(отключ|выключ|останов|удал|убер|отмен)\w*", re.I)
CHANGE_WORDS = re.compile(r"(сделай|измени|поменяй|давай|пусть|переставь|перенеси)", re.I)


def detect_type(text: str) -> str:
    if TAX_WORDS.search(text):
        return "tax"
    if LEARN_WORDS.search(text):
        return "learning"
    return "custom"


def manage_command(text: str) -> str | None:
    lowered = text.lower()
    if DISABLE_WORDS.search(lowered) and re.search(r"напоминан|напомин|уведомлен", lowered):
        return "disable_all" if re.search(r"\bвсе\b|\bвсё\b", lowered) else "disable"
    if re.fullmatch(r"\W*(отключи|выключи|останови|удали)\W*", lowered):
        return "disable"
    if CHANGE_WORDS.search(lowered) and re.search(r"раз в|кажд|ежедневн|еженедельн|ежемесячн|реже|чаще", lowered):
        return "change"
    return None


def parse_lead_and_time(text: str) -> tuple[int | None, str | None]:
    lowered = text.lower()
    lead = None
    match = re.search(r"за\s+(\d+)\s*(?:дн|день|дня)", lowered)
    if match:
        lead = int(match.group(1))
    elif re.search(r"в день (?:уплаты|оплаты|срока)|в тот же день", lowered):
        lead = 0
    time_match = re.search(r"(?:в|к)\s*(\d{1,2})(?:[:.](\d{2}))?(?!\d)", lowered)
    send_time = None
    if time_match:
        h, m = int(time_match.group(1)), int(time_match.group(2) or 0)
        if h < 24 and m < 60:
            send_time = f"{h:02d}:{m:02d}"
    return lead, send_time


def parse_date(text: str, now: datetime, tz: str) -> date | None:
    parsed = dateparser.parse(
        text,
        languages=["ru"],
        settings={
            "RELATIVE_BASE": now.astimezone(ZoneInfo(tz)).replace(tzinfo=None),
            "PREFER_DATES_FROM": "future",
        },
    )
    return parsed.date() if parsed else None


def tax_next_run(
    event: tc.TaxEvent,
    now: datetime,
    tz: str,
    send_time: str = "10:00",
    lead_days: int | None = None,
    path: str | None = None,
) -> tuple[datetime, date] | None:
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    lead = event.lead_days if lead_days is None else lead_days
    hh, mm = map(int, send_time.split(":"))
    cursor = local_now.date()
    for _ in range(40):
        due = tc.next_due(event, cursor, path)
        if due is None:
            return None
        run_at = datetime.combine(due - timedelta(days=lead), time(hh, mm), tzinfo=zone)
        if run_at > local_now:
            return run_at, due
        cursor = due + timedelta(days=1)
    return None


def row_schedule(r: Reminder) -> Schedule:
    return Schedule(freq=r.freq, weekdays=list(r.weekdays or []), interval=r.interval, send_time=r.send_time, run_at=r.run_at)


def compute_next_run(r: Reminder, now: datetime, tz: str, user: User | None = None) -> datetime | None:
    if r.type == "tax" and r.tax_event_id:
        event = tc.get_event(r.tax_event_id)
        if event is None:
            return None
        if event.rule["type"] == "manual":
            return r.run_at if r.run_at and r.run_at > now else None
        found = tax_next_run(event, now, tz, r.send_time, r.lead_days)
        return found[0] if found else None
    moment = next_occurrence(row_schedule(r), now, tz, anchor=r.created_at or now)
    if moment is None:
        return None
    if user is not None:
        moment = apply_quiet_hours(moment, tz, user.quiet_from, user.quiet_to)
    return moment


def describe_reminder(r: Reminder) -> str:
    if r.type == "tax" and r.tax_event_id:
        event = tc.get_event(r.tax_event_id)
        title = event.title if event else r.title
        when = "в день срока" if r.lead_days == 0 else f"за {r.lead_days} дн. до срока"
        return f"{title} — {when}, в {r.send_time}"
    return f"{r.title} — {describe(row_schedule(r))}"


def draft_lines(draft: dict) -> list[str]:
    lines = []
    for item in draft["items"]:
        if item["type"] == "tax":
            event = tc.get_event(item["tax_event_id"])
            lead = item["lead_days"]
            when = "в день срока" if lead == 0 else f"за {lead} дн. до срока"
            lines.append(f"• {event.title} — {when}, в {item['send_time']}")
        else:
            schedule = Schedule(
                freq=item.get("freq"),
                weekdays=item.get("weekdays", []),
                interval=item.get("interval", 1),
                send_time=item.get("send_time"),
                run_at=datetime.fromisoformat(item["run_at"]) if item.get("run_at") else None,
            )
            lines.append(f"• {item['title']} — {describe(schedule)}")
    return lines


async def create_from_draft(session: AsyncSession, user: User, draft: dict, now: datetime) -> list[Reminder]:
    created = []
    for item in draft["items"]:
        r = Reminder(
            user_id=user.id,
            type=item["type"],
            title=item["title"],
            freq=item.get("freq"),
            weekdays=item.get("weekdays", []),
            interval=item.get("interval", 1),
            send_time=item.get("send_time", "10:00"),
            lead_days=item.get("lead_days", 0),
            material_ext_id=item.get("material_ext_id"),
            tax_event_id=item.get("tax_event_id"),
            run_at=datetime.fromisoformat(item["run_at"]) if item.get("run_at") else None,
            created_at=now,
            active=True,
        )
        r.next_run_at = compute_next_run(r, now, user.tz, user)
        if r.next_run_at is None and r.type != "tax":
            continue
        session.add(r)
        created.append(r)
    await session.flush()
    return created


async def list_for_user(session: AsyncSession, user_id) -> list[Reminder]:
    result = await session.execute(
        select(Reminder).where(Reminder.user_id == user_id).order_by(Reminder.active.desc(), Reminder.next_run_at)
    )
    return list(result.scalars())
