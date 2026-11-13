import asyncio
import logging
from collections import defaultdict

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from bot.render import build_markup, build_text

MAX_PLAIN_LEN = 4000
log = logging.getLogger(__name__)
ERROR_TEXT = "Что-то пошло не так на моей стороне. Попробуйте ещё раз через минуту."

_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def user_lock(tg_id: int) -> asyncio.Lock:
    return _locks[tg_id]


async def reply(message: Message, response: dict) -> None:
    markup = build_markup(response)
    try:
        await message.answer(
            build_text(response), reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True
        )
    except TelegramBadRequest:
        log.warning("html message rejected, sending plain text")
        await message.answer(response["text"][:MAX_PLAIN_LEN], reply_markup=markup, disable_web_page_preview=True)
