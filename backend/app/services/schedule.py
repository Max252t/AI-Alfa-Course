import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import dateparser

WEEKDAYS = {
    "понедельник": 0, "пн": 0, "понедельникам": 0,
    "вторник": 1, "вт": 1, "вторникам": 1,
    "сред": 2, "ср": 2,
    "четверг": 3, "чт": 3,
    "пятниц": 4, "пт": 4,
    "суббот": 5, "сб": 5,
    "воскресень": 6, "вс": 6,
}

WEEKDAY_NAMES = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

NUMBER_WORDS = {
    "две": 2, "два": 2, "2": 2, "три": 3, "3": 3, "четыре": 4, "4": 4,
    "пять": 5, "5": 5, "шесть": 6, "6": 6,
}


@dataclass
class Schedule:
    freq: str | None = None
    weekdays: list[int] = field(default_factory=list)
    interval: int = 1
    send_time: str | None = None
    run_at: datetime | None = None

    @property
    def recurring(self) -> bool:
        return self.freq in {"daily", "weekly", "monthly", "quarterly"}

    @property
    def is_empty(self) -> bool:
        return self.freq is None and self.run_at is None


def _parse_time(text: str) -> str | None:
    match = re.search(r"\b(?:в|к|около)?\s*(\d{1,2})[:.](\d{2})\b", text)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if h < 24 and m < 60:
            return f"{h:02d}:{m:02d}"
    match = re.search(r"\b(?:в|к)\s+(\d{1,2})\s*(утра|вечера|дня|часов|часа|час)?\b", text)
    if match:
        h = int(match.group(1))
        suffix = match.group(2) or ""
        if suffix in {"вечера", "дня"} and h < 12:
            h += 12
        if h < 24:
            return f"{h:02d}:00"
    return None


def _parse_weekdays(text: str) -> list[int]:
    found = []
    for stem, number in WEEKDAYS.items():
        if len(stem) <= 2:
            if re.search(rf"(?<![а-яё]){stem}(?![а-яё])", text):
                found.append(number)
        elif stem in text:
            found.append(number)
    return sorted(set(found))


def _parse_interval(text: str) -> int:
    match = re.search(r"раз в (\S+) (?:недел|месяц|дн)", text) or re.search(r"каждые (\S+) (?:недел|месяц|дн)", text)
    if match:
        return NUMBER_WORDS.get(match.group(1), 1)
    return 1


def parse_schedule(text: str, now: datetime, tz: str = "Europe/Moscow") -> Schedule:
    lowered = text.lower().replace("ё", "е")
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    result = Schedule(send_time=_parse_time(lowered))
    interval = _parse_interval(lowered)
    weekdays = _parse_weekdays(lowered)

    if re.search(r"ежедневно|каждый день|каждое утро|каждый вечер|кажд\w+ дн", lowered):
        result.freq = "daily"
        result.interval = interval
    elif re.search(r"раз в (?:\S+ )?недел|еженедельно|каждую недел|кажд\w+ недел", lowered) or (
        weekdays and re.search(r"кажд|по ", lowered)
    ):
        result.freq = "weekly"
        result.interval = interval
        result.weekdays = weekdays
    elif re.search(r"ежеквартально|каждый квартал|раз в квартал", lowered):
        result.freq = "quarterly"
    elif re.search(r"ежемесячно|каждый месяц|раз в месяц|кажд\w+ месяц", lowered):
        result.freq = "monthly"
        result.interval = interval

    if result.freq is None:
        parsed = dateparser.parse(
            lowered,
            languages=["ru"],
            settings={
                "RELATIVE_BASE": local_now.replace(tzinfo=None),
                "PREFER_DATES_FROM": "future",
                "TIMEZONE": tz,
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        if parsed is not None:
            if result.send_time is None and parsed.time() != time(0, 0):
                result.send_time = parsed.strftime("%H:%M")
            at = result.send_time or "10:00"
            hh, mm = map(int, at.split(":"))
            run_at = parsed.replace(hour=hh, minute=mm, second=0, microsecond=0, tzinfo=zone)
            if run_at <= local_now:
                run_at += timedelta(days=1)
            result.run_at = run_at
    return result


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def next_occurrence(
    schedule: Schedule,
    after: datetime,
    tz: str,
    anchor: datetime | None = None,
) -> datetime | None:
    zone = ZoneInfo(tz)
    local_after = after.astimezone(zone)
    if not schedule.recurring:
        run_at = schedule.run_at
        return run_at if run_at and run_at > after else None

    hh, mm = map(int, (schedule.send_time or "10:00").split(":"))
    anchor_local = (anchor or after).astimezone(zone)

    def at(d: date) -> datetime:
        return datetime.combine(d, time(hh, mm), tzinfo=zone)

    if schedule.freq == "daily":
        candidate = at(local_after.date())
        if candidate <= local_after:
            candidate = at(local_after.date() + timedelta(days=1))
        step = schedule.interval
        if step > 1:
            days = (candidate.date() - anchor_local.date()).days
            if days % step:
                candidate = at(candidate.date() + timedelta(days=step - days % step))
        return candidate

    if schedule.freq == "weekly":
        days = schedule.weekdays or [anchor_local.weekday()]
        for offset in range(0, 7 * max(schedule.interval, 1) + 8):
            d = local_after.date() + timedelta(days=offset)
            if d.weekday() not in days:
                continue
            candidate = at(d)
            if candidate <= local_after:
                continue
            if schedule.interval > 1:
                weeks = ((d - timedelta(days=d.weekday())) - (anchor_local.date() - timedelta(days=anchor_local.weekday()))).days // 7
                if weeks % schedule.interval:
                    continue
            return candidate
        return None

    step = 3 if schedule.freq == "quarterly" else max(schedule.interval, 1)
    base = anchor_local.date()
    for n in range(0, 600):
        d = _add_months(base, n * step)
        candidate = at(d)
        if candidate > local_after:
            return candidate
    return None


def describe(schedule: Schedule) -> str:
    at = schedule.send_time or "10:00"
    if schedule.freq == "daily":
        return f"каждый день в {at}" if schedule.interval == 1 else f"раз в {schedule.interval} дн. в {at}"
    if schedule.freq == "weekly":
        names = ", ".join(WEEKDAY_NAMES[d] for d in schedule.weekdays) or "в тот же день недели"
        if schedule.interval == 1:
            return f"каждую неделю ({names}) в {at}"
        return f"раз в {schedule.interval} нед. ({names}) в {at}"
    if schedule.freq == "monthly":
        return f"раз в {schedule.interval} мес. в {at}" if schedule.interval > 1 else f"каждый месяц в {at}"
    if schedule.freq == "quarterly":
        return f"раз в квартал в {at}"
    if schedule.run_at:
        return f"{schedule.run_at.strftime('%d.%m.%Y в %H:%M')}"
    return "время не задано"


def apply_quiet_hours(moment: datetime, tz: str, quiet_from: int = 22, quiet_to: int = 9) -> datetime:
    local = moment.astimezone(ZoneInfo(tz))
    hour = local.hour
    in_quiet = hour >= quiet_from or hour < quiet_to if quiet_from > quiet_to else quiet_from <= hour < quiet_to
    if not in_quiet:
        return moment
    target = local.replace(hour=quiet_to, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target
