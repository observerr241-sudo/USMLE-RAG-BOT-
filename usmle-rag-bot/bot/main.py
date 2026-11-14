"""Entrypoint: init MongoDB + indexes, build rotator, register routers, run polling (or webhook)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot import config, database
from bot.catalog import subtopic_count, topic_count
from bot.gemini_router import get_rotator, revalidate_loop
from bot.handlers import admin, user_quiz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bot")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)       # admin first so /grant etc. and adm_* callbacks are never shadowed
    dp.include_router(user_quiz.router)
    return dp


async def on_startup(bot: Bot) -> None:
    await database.init_db()
    rotator = get_rotator()
    logger.info("Mongo ready | %d topics / %d subtopics | %s", topic_count(), subtopic_count(), rotator.summary())
    await bot.set_my_commands([BotCommand(command="start", description="Open the USMLE practice menu")])
    asyncio.create_task(revalidate_loop(), name="rotator-revalidate")


async def on_shutdown(bot: Bot) -> None:
    await database.close_db()


async def main() -> None:
    config.validate(require_bot=True)
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()

    if config.WEBHOOK_BASE_URL:
        from aiohttp import web
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

        await on_startup(bot)  # aiogram only fires startup hooks automatically for polling
        await bot.set_webhook(
            config.WEBHOOK_BASE_URL + config.WEBHOOK_PATH,
            secret_token=config.WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=config.WEBHOOK_SECRET or None).register(app, path=config.WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, config.WEBAPP_HOST, config.WEBAPP_PORT).start()
        logger.info("Webhook mode on %s:%s", config.WEBAPP_HOST, config.WEBAPP_PORT)
        try:
            await asyncio.Event().wait()
        finally:
            await bot.delete_webhook()
            await on_shutdown(bot)
            await runner.cleanup()
    else:
        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
