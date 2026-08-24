"""Точка входа HR-бота.

Запуск: python main.py
"""

import asyncio
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BASE_DIR, load_config
from bot.handlers import all_routers
from bot.middlewares import AccessMiddleware
from bot.services.auth import AuthService
from bot.services.notifications import scheduler_loop
from bot.services.sheets import SheetsDB, SheetsUnavailable


def setup_logging() -> None:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_h = RotatingFileHandler(log_dir / "bot.log", maxBytes=1_000_000, backupCount=5,
                                 encoding="utf-8")
    file_h.setFormatter(fmt)
    root.addHandler(file_h)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def main() -> None:
    cfg = load_config()
    setup_logging()
    log = logging.getLogger(__name__)

    db = SheetsDB(cfg)
    try:
        await db.ensure_structure()
        log.info("Структура Google Sheets готова")
    except SheetsUnavailable as e:
        log.critical(
            "Google Sheets недоступен: %s\n"
            "Проверьте:\n"
            " 1) файл сервисного аккаунта (GOOGLE_CREDENTIALS_FILE в .env)\n"
            " 2) что таблицей поделились с email сервисного аккаунта (Редактор)\n"
            " 3) включен ли Google Sheets API в проекте Google Cloud", e)
        return

    auth = AuthService(db, cfg)
    await auth.bootstrap()

    bot = Bot(cfg.bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp["db"] = db
    dp["auth"] = auth
    dp["cfg"] = cfg

    dp.include_routers(*all_routers())

    dp.message.middleware(AccessMiddleware(auth))
    dp.callback_query.middleware(AccessMiddleware(auth))

    me = await bot.get_me()
    log.info("Бот @%s запущен", me.username)

    def _events_kb():
        from bot.keyboards import events_menu
        return events_menu()

    notify_task = asyncio.create_task(
        scheduler_loop(bot, db, auth, cfg, events_kb=_events_kb))
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        notify_task.cancel()
        await asyncio.gather(notify_task, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Остановлено")
