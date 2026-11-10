from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import api
from bot.handlers.common import ERROR_TEXT, reply

router = Router()


async def run_command(message: Message, name: str) -> None:
    try:
        responses = await api.command(message.from_user.id, message.chat.id, name)
    except api.BackendError:
        await message.answer(ERROR_TEXT)
        return
    for response in responses:
        await reply(message, response)


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    await run_command(message, "help")


@router.message(Command("profile"))
async def on_profile(message: Message) -> None:
    await run_command(message, "profile")


@router.message(Command("reminders"))
async def on_reminders(message: Message) -> None:
    await run_command(message, "reminders")


@router.message(Command("reset"))
async def on_reset(message: Message) -> None:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить всё", callback_data="reset:yes"),
                InlineKeyboardButton(text="Отмена", callback_data="reset:no"),
            ]
        ]
    )
    await message.answer(
        "Удалю ваш профиль, историю диалога и все напоминания. Это нельзя отменить. Продолжить?",
        reply_markup=markup,
    )


@router.callback_query(F.data.startswith("reset:"))
async def on_reset_choice(query: CallbackQuery) -> None:
    await query.answer()
    if query.data == "reset:no":
        await query.message.answer("Хорошо, ничего не удаляю.")
        return
    try:
        await api.reset(query.from_user.id)
    except api.BackendError:
        await query.message.answer("Пока нечего удалять или сервис недоступен. Если вы уже писали мне — попробуйте позже.")
        return
    await query.message.answer("Готово: все ваши данные удалены. Если захотите начать заново — нажмите /start.")
