import asyncio
from collections import defaultdict

from aiogram.types import Message

from bot.render import build_markup, build_text

ERROR_TEXT = "Что-то пошло не так на моей стороне. Попробуйте ещё раз через минуту."

_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def user_lock(tg_id: int) -> asyncio.Lock:
    return _locks[tg_id]


async def reply(message: Message, response: dict) -> None:
    await message.answer(
        build_text(response),
        reply_markup=build_markup(response),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
