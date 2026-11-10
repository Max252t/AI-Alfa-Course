import logging

from aiogram import F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from bot import api
from bot.handlers.common import ERROR_TEXT, reply, user_lock

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text)
async def on_text(message: Message) -> None:
    tg_id, chat_id = message.from_user.id, message.chat.id
    async with user_lock(tg_id), ChatActionSender.typing(bot=message.bot, chat_id=chat_id):
        try:
            response = await api.chat(tg_id, chat_id, message.text)
        except api.BackendError:
            log.exception("chat failed")
            await message.answer(ERROR_TEXT)
            return
    await reply(message, response)


@router.message()
async def on_other(message: Message) -> None:
    await message.answer("Пока я понимаю только текст. Напишите свой вопрос словами.")
