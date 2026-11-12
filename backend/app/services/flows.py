import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Material, Profile, Reminder, User
from app.schemas import Button, ChatResponse, rows
from app.services import tax_calendar as tc
from app.services.context import apply_slots, clear_keys, log_event, set_state
from app.services.profile_rules import extract_legal_form, extract_tax_regime
from app.services.reminders import (
    compute_next_run,
    create_from_draft,
    describe_reminder,
    detect_type,
    draft_lines,
    list_for_user,
    parse_date,
    parse_lead_and_time,
)
from app.services.schedule import Schedule, parse_schedule

YES = re.compile(r"^\W*(да|верно|ок|окей|подтверждаю|создавай|давай|все верно|всё верно|согласен|yes)\W*$", re.I)
NO = re.compile(r"^\W*(нет|не надо|отмена|отмени|неверно|не то)\W*$", re.I)

TZ_OPTIONS = {
    "Europe/Moscow": "Москва",
    "Asia/Yekaterinburg": "Екатеринбург",
    "Asia/Novosibirsk": "Новосибирск",
    "Asia/Vladivostok": "Владивосток",
}

CLEAN_PREFIX = re.compile(r"^\W*(?:пожалуйста[, ]*)?(?:напомни(?:ть)?|напоминай)\s*(?:мне)?\s*", re.I)
CLEAN_SCHEDULE = re.compile(
    r"\b(?:каждый|каждую|каждое|каждые|раз в|ежедневно|еженедельно|ежемесячно|ежеквартально|завтра|послезавтра|сегодня)\b.*$",
    re.I,
)


def sched_to_dict(s: Schedule) -> dict:
    return {
        "freq": s.freq,
        "weekdays": s.weekdays,
        "interval": s.interval,
        "send_time": s.send_time,
        "run_at": s.run_at.isoformat() if s.run_at else None,
    }


def sched_from_dict(d: dict) -> Schedule:
    return Schedule(
        freq=d.get("freq"),
        weekdays=d.get("weekdays") or [],
        interval=d.get("interval") or 1,
        send_time=d.get("send_time"),
        run_at=datetime.fromisoformat(d["run_at"]) if d.get("run_at") else None,
    )


def make_title(text: str, kind: str, material_title: str | None) -> str:
    if kind == "learning":
        return f"Продолжить обучение: {material_title}" if material_title else "Продолжить обучение"
    cleaned = CLEAN_SCHEDULE.sub("", CLEAN_PREFIX.sub("", text)).strip(" .,!?")
    return cleaned[:120].capitalize() if cleaned else "Напоминание"


def button_row(*pairs: tuple[str, str], per_row: int = 3) -> list[list[Button]]:
    return rows([Button(text=t, data=d) for t, d in pairs], per_row)


def confirm_buttons() -> list[list[Button]]:
    return button_row(("Да", "rf:yes"), ("Изменить", "rf:edit"), ("Отмена", "rf:cancel"))


async def start_reminder(
    session: AsyncSession,
    user: User,
    profile: Profile,
    text: str,
    now: datetime,
    material: dict | None = None,
) -> ChatResponse:
    kind = "learning" if material else detect_type(text)
    lead, send_time = parse_lead_and_time(text)
    regime = extract_tax_regime(text)
    form = extract_legal_form(text)
    if regime or form:
        apply_slots(profile, {k: v for k, v in {"tax_regime": regime, "legal_form": form}.items() if v}, 0.9)
    schedule = parse_schedule(text, now, user.tz)
    last = (user.state or {}).get("last_material")
    mat = material or (last if kind == "learning" else None)
    rem = {
        "type": kind,
        "title": make_title(text, kind, mat["title"] if mat else None),
        "material_ext_id": mat["ext_id"] if mat else None,
        "schedule": None if kind == "tax" or schedule.is_empty else sched_to_dict(schedule),
        "send_time": send_time or (schedule.send_time if kind == "tax" else None) or "10:00",
        "lead_days": lead,
        "step": "start",
        "tries": 0,
        "items": None,
    }
    set_state(user, flow="reminder", rem=rem)
    await log_event(session, user.id, "reminder_flow_started", {"type": kind})
    return await next_step(session, user, profile, now)


async def next_step(session: AsyncSession, user: User, profile: Profile, now: datetime) -> ChatResponse:
    rem = dict(user.state["rem"])

    if rem["type"] == "tax":
        regime, form = profile.tax_regime, profile.legal_form
        if not regime:
            return await ask(user, rem, "regime", "По какому режиму налогообложения вы работаете?", button_row(
                *[(label, f"rf:regime:{key}") for key, label in tc.REGIME_LABELS.items()]
            ))
        if not form and regime not in {"npd", "patent"}:
            return await ask(user, rem, "legal", "Вы ИП или ООО?", button_row(
                ("ИП", "rf:legal:ip"), ("ООО", "rf:legal:ooo")
            ))
        events = tc.events_for(regime, form if regime not in {"npd", "patent"} else None)
        if not events:
            clear_keys(user, "flow", "rem")
            return ChatResponse(text="Не нашёл сроков для этого режима. Попробуйте уточнить режим через /profile.")
        manual = [e for e in events if e.rule["type"] == "manual"]
        if manual and not rem.get("patent_date"):
            return await ask(user, rem, "patent_date", "Назовите дату, до которой нужно оплатить патент (например, 15 июня).", [])
        rem["items"] = build_tax_items(events, rem, user.tz)
    else:
        if not rem.get("schedule"):
            return await ask(user, rem, "when", "Когда и как часто напоминать?", button_row(
                ("Завтра в 10:00", "rf:when:tomorrow"),
                ("Каждый понедельник", "rf:when:weekly"),
                ("Каждый день", "rf:when:daily"),
            ))
        schedule = sched_from_dict(rem["schedule"])
        if schedule.send_time is None:
            schedule.send_time = rem.get("send_time") or "10:00"
        rem["schedule"] = sched_to_dict(schedule)
        rem["items"] = [
            {
                "type": rem["type"],
                "title": rem["title"],
                "material_ext_id": rem.get("material_ext_id"),
                **sched_to_dict(schedule),
            }
        ]

    if not (user.state or {}).get("tz_set"):
        return await ask(user, rem, "tz", "В каком часовом поясе вы живёте? Я напомню по вашему времени.", button_row(
            *[(label, f"rf:tz:{zone}") for zone, label in TZ_OPTIONS.items()]
        ))

    rem["step"] = "confirm"
    set_state(user, rem=rem)
    lines = "\n".join(draft_lines(rem))
    note = ""
    if rem["type"] == "tax":
        note = f"\n\n{tc.disclaimer()}"
    return ChatResponse(
        text=f"Создам напоминание:\n{lines}\n\nВсё верно?{note}",
        buttons=confirm_buttons(),
    )


def build_tax_items(events: list[tc.TaxEvent], rem: dict, tz: str) -> list[dict]:
    items = []
    for event in events:
        lead = rem.get("lead_days")
        lead = event.lead_days if lead is None else lead
        item = {
            "type": "tax",
            "title": event.title,
            "tax_event_id": event.id,
            "lead_days": lead,
            "send_time": rem.get("send_time") or "10:00",
        }
        if event.rule["type"] == "manual":
            due = datetime.fromisoformat(rem["patent_date"])
            hh, mm = map(int, item["send_time"].split(":"))
            run = datetime.combine(due.date() - timedelta(days=lead), time(hh, mm), tzinfo=ZoneInfo(tz))
            item["run_at"] = run.isoformat()
        items.append(item)
    return items


async def ask(user: User, rem: dict, step: str, text: str, buttons: list[list[Button]]) -> ChatResponse:
    rem["step"] = step
    set_state(user, rem=rem)
    return ChatResponse(text=text, buttons=buttons)


async def cancel(user: User, text: str = "Хорошо, не создаю напоминание.") -> ChatResponse:
    clear_keys(user, "flow", "rem")
    return ChatResponse(text=text)


async def finish(session: AsyncSession, user: User, now: datetime) -> ChatResponse:
    rem = user.state["rem"]
    created = await create_from_draft(session, user, rem, now)
    clear_keys(user, "flow", "rem")
    if not created:
        return ChatResponse(text="Не получилось определить время напоминания. Попробуйте ещё раз, например: «каждый понедельник в 9».")
    await log_event(session, user.id, "reminder_created", {"count": len(created), "type": rem["type"]})
    when = created[0].next_run_at.astimezone(ZoneInfo(user.tz)).strftime("%d.%m в %H:%M") if created[0].next_run_at else ""
    tail = f" Ближайшее — {when}." if when else ""
    return ChatResponse(
        text=f"Готово, создал напоминаний: {len(created)}.{tail}\nУправлять ими можно в /reminders.",
        buttons=button_row(("Мои напоминания", "rem:list")),
    )


async def flow_text(
    session: AsyncSession, user: User, profile: Profile, text: str, now: datetime
) -> ChatResponse | None:
    rem = dict(user.state["rem"])
    step = rem["step"]
    lowered = text.strip().lower()

    if step == "confirm":
        if YES.match(lowered):
            return await finish(session, user, now)
        if NO.match(lowered):
            return await cancel(user)
        return await edit_prompt(user, rem)

    if step == "regime":
        value = extract_tax_regime(text)
        if value:
            apply_slots(profile, {"tax_regime": value}, 0.95)
            return await next_step(session, user, profile, now)
    elif step == "legal":
        value = extract_legal_form(text)
        if value:
            apply_slots(profile, {"legal_form": value}, 0.95)
            return await next_step(session, user, profile, now)
    elif step == "when":
        schedule = parse_schedule(text, now, user.tz)
        if not schedule.is_empty:
            rem["schedule"] = sched_to_dict(schedule)
            set_state(user, rem=rem)
            return await next_step(session, user, profile, now)
    elif step == "patent_date":
        due = parse_date(text, now, user.tz)
        if due:
            rem["patent_date"] = datetime.combine(due, time(0, 0)).isoformat()
            set_state(user, rem=rem)
            return await next_step(session, user, profile, now)
    elif step == "edit":
        return await apply_edit(session, user, profile, rem, text, now)
    elif step == "tz":
        set_state(user, tz_set=True)
        return await next_step(session, user, profile, now)

    if step in {"regime", "legal", "when", "patent_date"} and ("?" in text or len(text.split()) >= 4):
        clear_keys(user, "flow", "rem")
        return None
    rem["tries"] = rem.get("tries", 0) + 1
    if rem["tries"] >= 2:
        return await cancel(user, "Не получилось понять. Давайте начнём заново — напишите, что и когда напомнить.")
    set_state(user, rem=rem)
    hints = {
        "regime": "Выберите режим кнопкой или напишите, например: «УСН доходы».",
        "legal": "Напишите «ИП» или «ООО».",
        "when": "Напишите, например: «каждый понедельник в 9» или «завтра в 15:00».",
        "patent_date": "Напишите дату, например: «15 июня».",
    }
    return ChatResponse(text=hints.get(step, "Не понял. Попробуйте ещё раз."))


async def edit_prompt(user: User, rem: dict) -> ChatResponse:
    rem["step"] = "edit"
    rem["tries"] = 0
    set_state(user, rem=rem)
    if rem["type"] == "tax":
        hint = "Напишите, за сколько дней и во сколько напомнить, например: «за 5 дней в 9:00»."
    else:
        hint = "Напишите, когда и как часто напомнить, например: «каждую среду в 18:00»."
    return ChatResponse(text=hint)


async def apply_edit(
    session: AsyncSession, user: User, profile: Profile, rem: dict, text: str, now: datetime
) -> ChatResponse:
    if rem["type"] == "tax":
        lead, send_time = parse_lead_and_time(text)
        if lead is None and send_time is None:
            return ChatResponse(text="Напишите, например: «за 5 дней в 9:00».")
        if lead is not None:
            rem["lead_days"] = lead
        if send_time:
            rem["send_time"] = send_time
    else:
        schedule = parse_schedule(text, now, user.tz)
        if schedule.is_empty:
            return ChatResponse(text="Напишите, например: «каждую среду в 18:00».")
        rem["schedule"] = sched_to_dict(schedule)
    rem["step"] = "start"
    set_state(user, rem=rem)
    return await next_step(session, user, profile, now)


async def flow_callback(
    session: AsyncSession, user: User, profile: Profile, data: str, now: datetime
) -> ChatResponse:
    if "rem" not in (user.state or {}):
        return ChatResponse(text="Это напоминание уже неактуально. Напишите, что и когда напомнить.")
    rem = dict(user.state["rem"])
    parts = data.split(":")
    action = parts[1]

    if action == "yes":
        return await finish(session, user, now)
    if action == "cancel":
        return await cancel(user)
    if action == "edit":
        return await edit_prompt(user, rem)
    if action == "regime":
        apply_slots(profile, {"tax_regime": parts[2]}, 0.95)
    elif action == "legal":
        apply_slots(profile, {"legal_form": parts[2]}, 0.95)
    elif action == "tz":
        if parts[2] in TZ_OPTIONS:
            user.tz = parts[2]
        set_state(user, tz_set=True)
        if rem.get("schedule") and rem["type"] != "tax":
            old = sched_from_dict(rem["schedule"])
            if old.run_at:
                old.run_at = old.run_at.replace(tzinfo=ZoneInfo(user.tz))
                rem["schedule"] = sched_to_dict(old)
                set_state(user, rem=rem)
    elif action == "when":
        key = parts[2]
        send = rem.get("send_time") or "10:00"
        text = {"tomorrow": f"завтра в {send}", "weekly": f"каждый понедельник в {send}", "daily": f"каждый день в {send}"}[key]
        rem["schedule"] = sched_to_dict(parse_schedule(text, now, user.tz))
        set_state(user, rem=rem)
    return await next_step(session, user, profile, now)


async def reminder_link_material(session: AsyncSession, r: Reminder) -> Material | None:
    if r.material_ext_id:
        result = await session.execute(select(Material).where(Material.ext_id == r.material_ext_id))
        return result.scalar_one_or_none()
    topic = None
    if r.tax_event_id:
        event = tc.get_event(r.tax_event_id)
        topic = event.topic if event else None
    if not topic:
        return None
    result = await session.execute(
        select(Material)
        .where(Material.is_paid.is_(False), Material.title.ilike(f"%{topic}%"), Material.kind.in_(["article", "course"]))
        .order_by(Material.popularity.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def reminder_buttons(r: Reminder) -> list[list[Button]]:
    toggle = "Отключить" if r.active else "Включить"
    result = [
        [
            Button(text=toggle, data=f"rem:toggle:{r.id}"),
            Button(text="Отложить", data=f"rem:snooze:{r.id}"),
            Button(text="Удалить", data=f"rem:del:{r.id}"),
        ]
    ]
    if r.type != "tax":
        result.append([Button(text="Изменить частоту", data=f"rem:freqmenu:{r.id}")])
    return result


async def list_response(session: AsyncSession, user: User) -> list[ChatResponse]:
    reminders = await list_for_user(session, user.id)
    if not reminders:
        return [ChatResponse(text="У вас пока нет напоминаний. Напишите, например: «Напоминай каждый понедельник продолжить курс».")]
    tz = ZoneInfo(user.tz)
    result = []
    for r in reminders:
        state = "включено" if r.active else "выключено"
        nxt = f"\nБлижайшее: {r.next_run_at.astimezone(tz).strftime('%d.%m в %H:%M')}" if r.active and r.next_run_at else ""
        result.append(ChatResponse(text=f"⏰ {describe_reminder(r)} ({state}){nxt}", buttons=reminder_buttons(r)))
    return result


async def get_reminder(session: AsyncSession, user: User, rid: str) -> Reminder | None:
    r = await session.get(Reminder, rid)
    return r if r and r.user_id == user.id else None


async def reminder_action(session: AsyncSession, user: User, data: str, now: datetime) -> ChatResponse:
    parts = data.split(":")
    action = parts[1]
    if action == "list":
        responses = await list_response(session, user)
        merged = "\n\n".join(r.text for r in responses)
        return ChatResponse(text=merged, action="list_reminders")
    r = await get_reminder(session, user, parts[2]) if len(parts) > 2 else None
    if r is None:
        return ChatResponse(text="Не нашёл это напоминание — возможно, оно уже удалено.")
    if action == "toggle":
        r.active = not r.active
        if r.active:
            r.next_run_at = compute_next_run(r, now, user.tz, user)
        await log_event(session, user.id, "reminder_toggled", {"active": r.active})
        return ChatResponse(
            text="Напоминание включено." if r.active else "Напоминание выключено. Включить снова можно в /reminders.",
            buttons=reminder_buttons(r),
        )
    if action == "del":
        await session.delete(r)
        await log_event(session, user.id, "reminder_deleted", {})
        return ChatResponse(text="Напоминание удалено.")
    if action == "snooze":
        r.next_run_at = (now + timedelta(days=1)).astimezone(ZoneInfo(user.tz)).replace(second=0, microsecond=0)
        r.active = True
        await log_event(session, user.id, "reminder_snoozed", {})
        return ChatResponse(text="Отложил на завтра.")
    if action == "freqmenu":
        return ChatResponse(
            text="Как часто напоминать?",
            buttons=button_row(
                ("Каждый день", f"rem:freq:{r.id}:daily"),
                ("Каждую неделю", f"rem:freq:{r.id}:weekly"),
                ("Раз в 2 недели", f"rem:freq:{r.id}:biweekly"),
                ("Каждый месяц", f"rem:freq:{r.id}:monthly"),
            ),
        )
    if action == "freq":
        apply_frequency(r, parts[3], now, user.tz)
        r.next_run_at = compute_next_run(r, now, user.tz, user)
        await log_event(session, user.id, "reminder_frequency_changed", {"freq": parts[3]})
        return ChatResponse(text=f"Изменил: {describe_reminder(r)}", buttons=reminder_buttons(r))
    return ChatResponse(text="Не понял действие.")


def apply_frequency(r: Reminder, key: str, now: datetime, tz: str) -> None:
    anchor = (r.created_at or now).astimezone(ZoneInfo(tz))
    r.run_at = None
    if key == "daily":
        r.freq, r.interval, r.weekdays = "daily", 1, []
    elif key == "weekly":
        r.freq, r.interval, r.weekdays = "weekly", 1, r.weekdays or [anchor.weekday()]
    elif key == "biweekly":
        r.freq, r.interval, r.weekdays = "weekly", 2, r.weekdays or [anchor.weekday()]
    elif key == "monthly":
        r.freq, r.interval, r.weekdays = "monthly", 1, []


async def manage_text(
    session: AsyncSession, user: User, text: str, command: str, now: datetime
) -> ChatResponse | None:
    reminders = [r for r in await list_for_user(session, user.id) if r.active]
    if not reminders:
        return ChatResponse(text="У вас нет активных напоминаний. Создать новое? Напишите, что и когда напомнить.")
    if command == "disable_all":
        for r in reminders:
            r.active = False
        await log_event(session, user.id, "reminders_disabled_all", {"count": len(reminders)})
        return ChatResponse(text="Отключил все напоминания. Включить снова можно в /reminders.")
    latest = max(reminders, key=lambda r: r.created_at)
    if command == "disable":
        latest.active = False
        await log_event(session, user.id, "reminder_toggled", {"active": False})
        return ChatResponse(
            text=f"Отключил: {describe_reminder(latest)}. Включить снова можно в /reminders.",
            buttons=button_row(("Включить обратно", f"rem:toggle:{latest.id}")),
        )
    if command == "change":
        if latest.type == "tax":
            lead, send_time = parse_lead_and_time(text)
            if lead is not None:
                latest.lead_days = lead
            if send_time:
                latest.send_time = send_time
        else:
            parsed = parse_schedule(text, now, user.tz)
            if parsed.is_empty or not parsed.freq:
                return ChatResponse(text="Как часто напоминать? Например: «раз в две недели» или «каждый день в 9».")
            latest.freq, latest.interval = parsed.freq, parsed.interval
            latest.weekdays = parsed.weekdays or latest.weekdays
            if parsed.send_time:
                latest.send_time = parsed.send_time
            latest.run_at = None
        latest.next_run_at = compute_next_run(latest, now, user.tz, user)
        await log_event(session, user.id, "reminder_frequency_changed", {"via": "text"})
        return ChatResponse(text=f"Готово: {describe_reminder(latest)}", buttons=reminder_buttons(latest))
    return None
