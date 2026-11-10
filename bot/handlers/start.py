from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot import api
from bot.handlers.common import ERROR_TEXT, reply

router = Router()


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    try:
        response = await api.start(message.from_user.id, message.chat.id)
    except api.BackendError:
        await message.answer(ERROR_TEXT)
        return
    await reply(message, response)
