import logging

import httpx

from app.config import get_settings
from app.schemas import Button

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class UserBlocked(Exception):
    pass


def _keyboard(buttons: list[list[Button]]) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": b.text, **({"url": b.url} if b.url else {"callback_data": b.data or "noop"})}
                for b in row
            ]
            for row in buttons
        ]
    }


async def send_message(chat_id: int, text: str, buttons: list[list[Button]] | None = None) -> bool:
    token = get_settings().telegram_bot_token
    if not token:
        log.warning("telegram token is not set, message skipped")
        return False
    payload: dict = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = _keyboard(buttons)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
        if response.status_code == 403:
            log.info("user blocked the bot")
            raise UserBlocked
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.warning("failed to send telegram message (%s)", type(exc).__name__)
        return False
