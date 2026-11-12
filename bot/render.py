import html
import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MAX_LEN = 4000

TITLED_LINK = re.compile(r"^((?:\[\d+\] |• )?)(.+?) — (https?://\S+)$", re.MULTILINE)
BARE_LINK = re.compile(r'(?<!["\'>=])(https?://[^\s<]+)')


def linkify(escaped: str) -> str:
    with_titles = TITLED_LINK.sub(lambda m: f'{m.group(1)}<a href="{m.group(3)}">{m.group(2)}</a>', escaped)
    return BARE_LINK.sub(lambda m: f'<a href="{m.group(1)}">ссылка</a>', with_titles)


def anchor(title: str, url: str | None) -> str:
    safe = html.escape(title)
    return f'<a href="{html.escape(url)}">{safe}</a>' if url else safe


def rec_block(recs: list[dict]) -> str:
    if not recs:
        return ""
    lines = ["📚 Что почитать дальше:"]
    for rec in recs:
        title = anchor(rec["title"], rec.get("url"))
        if rec.get("is_paid"):
            lines.append(f"\n⭐ Платный курс: {title}")
            if rec.get("benefit"):
                lines.append(html.escape(rec["benefit"]))
        else:
            lines.append(f"\n• Бесплатно: {title}")
        if rec.get("reason"):
            lines.append(f"{html.escape(rec['reason'])}.")
    return "\n".join(lines)


def build_text(response: dict) -> str:
    block = rec_block(response.get("recommendations") or [])
    room = MAX_LEN - len(block) - 2 if block else MAX_LEN
    text = linkify(html.escape(response["text"][: max(room, 500)]))
    return f"{text}\n\n{block}" if block else text


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
