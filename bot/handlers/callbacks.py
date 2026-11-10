import logging

from aiogram import Router
from aiogram.types import CallbackQuery
from aiogram.utils.chat_action import ChatActionSender

from bot import api
from bot.handlers.common import ERROR_TEXT, reply, user_lock

router = Router()
log = logging.getLogger(__name__)


@router.callback_query()
async def on_callback(query: CallbackQuery) -> None:
    await query.answer()
    if not query.data or query.message is None:
        return
    tg_id, chat_id = query.from_user.id, query.message.chat.id
    async with user_lock(tg_id), ChatActionSender.typing(bot=query.bot, chat_id=chat_id):
        try:
            response = await api.callback(tg_id, chat_id, query.data)
        except api.BackendError:
            log.exception("callback failed")
            await query.message.answer(ERROR_TEXT)
            return
    await reply(query.message, response)
