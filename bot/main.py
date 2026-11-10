import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.config import settings
from bot.handlers import callbacks, commands, qa, start

COMMANDS = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="help", description="Что я умею"),
    BotCommand(command="profile", description="Мой профиль"),
    BotCommand(command="reminders", description="Мои напоминания"),
    BotCommand(command="reset", description="Удалить мои данные"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан. Укажите токен бота в .env.")
    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(start.router)
    dispatcher.include_router(commands.router)
    dispatcher.include_router(callbacks.router)
    dispatcher.include_router(qa.router)
    await bot.set_my_commands(COMMANDS)
    await bot.delete_webhook(drop_pending_updates=False)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
