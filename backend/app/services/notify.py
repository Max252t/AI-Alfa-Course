import logging

import httpx

from app.config import get_settings
from app.schemas import Button

log = logging.getLogger(__name__)
# HTTP request URLs contain the bot token. Do not emit transport request logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


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
            return False
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        # Exception messages and tracebacks can include the authenticated URL.
        log.warning("failed to send telegram message (%s)", type(exc).__name__)
        return False
