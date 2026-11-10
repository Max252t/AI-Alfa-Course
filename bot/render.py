from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MAX_LEN = 4000


def rec_block(recs: list[dict]) -> str:
    if not recs:
        return ""
    lines = ["📚 Что почитать дальше:"]
    for rec in recs:
        if rec.get("is_paid"):
            lines.append(f"\n⭐ Платный курс: {rec['title']}")
            if rec.get("benefit"):
                lines.append(rec["benefit"])
        else:
            lines.append(f"\n• Бесплатно: {rec['title']}")
        if rec.get("url"):
            lines.append(rec["url"])
        if rec.get("reason"):
            lines.append(f"{rec['reason']}.")
    return "\n".join(lines)


def build_text(response: dict) -> str:
    text = response["text"]
    block = rec_block(response.get("recommendations") or [])
    full = f"{text}\n\n{block}" if block else text
    return full[:MAX_LEN]


def build_markup(response: dict) -> InlineKeyboardMarkup | None:
    rows = []
    for row in response.get("buttons") or []:
        buttons = []
        for b in row:
            if b.get("url"):
                buttons.append(InlineKeyboardButton(text=b["text"], url=b["url"]))
            elif b.get("data"):
                buttons.append(InlineKeyboardButton(text=b["text"], callback_data=b["data"][:64]))
        if buttons:
            rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
