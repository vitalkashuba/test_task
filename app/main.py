import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .bot.handlers import router
from .config import load_settings
from .ingest.archive import load_archive
from .knowledge.store import Store
from .llm.groq_client import GroqClient


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    store = Store(settings.db_path)
    groq = GroqClient(settings.groq_api_key, settings.groq_model, settings.groq_vision_model)

    bot = Bot(settings.telegram_token)
    dp = Dispatcher(storage=MemoryStorage(), store=store, groq=groq, settings=settings)
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Як користуватися ботом"),
        BotCommand(command="mydocs", description="Мої документи"),
    ])

    # Архів вантажиться у фоні: бот відповідає одразу, скани читаються один раз і кешуються
    archive_task = asyncio.create_task(load_archive(store, groq, settings))
    try:
        await dp.start_polling(bot)
    finally:
        archive_task.cancel()
        await groq.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
