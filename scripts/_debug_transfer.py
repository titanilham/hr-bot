"""Отладка цикла перевода: печатает каждое исходящее сообщение по шагам."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from aiogram import Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Update

from bot.config import load_config
from bot.handlers import all_routers
from bot.middlewares import AccessMiddleware
from bot.services.auth import AuthService
from bot.services.sheets import SheetsDB

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_check import RecordingBot, make_callback, make_message  # noqa: E402


async def main() -> None:
    cfg = load_config()
    db = SheetsDB(cfg)
    await db.ensure_structure()
    auth = AuthService(db, cfg)
    await auth.bootstrap()

    bot = RecordingBot(cfg.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["auth"] = auth
    dp["cfg"] = cfg
    dp.include_routers(*all_routers())
    dp.message.middleware(AccessMiddleware(auth))
    dp.callback_query.middleware(AccessMiddleware(auth))

    UID = CID = 1456945518
    seq = {"n": 500}

    async def feed(obj):
        seq["n"] += 1
        if hasattr(obj, "text") and not isinstance(obj, CallbackQuery):
            upd = Update(update_id=seq["n"], message=obj)
        else:
            upd = Update(update_id=seq["n"], callback_query=obj)
        try:
            await dp.feed_update(bot, upd)
        except Exception as e:
            print(f"!!! HANDLER EXCEPTION: {type(e).__name__}: {e}")

    async def tap(data, note=""):
        await feed(make_callback(UID, CID, data, seq["n"] + 1))
        last = bot.sent[-1] if bot.sent else ("<none>", "")
        print(f"TAP {data:22s} -> [{last[0]}] {last[1][:90]}")

    async def send(text, note=""):
        await feed(make_message(UID, CID, text, seq["n"] + 1))
        last = bot.sent[-1] if bot.sent else ("<none>", "")
        print(f"TEXT {text[:26]:26s} -> [{last[0]}] {last[1][:90]}")

    emps = await db.get_employees(fresh=True)
    emp = next(e for e in emps if e.eid == "EMP-0003")
    print(f"Цель: {emp.eid} {emp.fio} pos={emp.pos}")

    await tap(f"xfer:{emp.eid}")
    await send("Старший тест-инженер")
    await tap("xfskip_dept")
    await tap("xfskip_sup")
    await tap("xftoday")
    await tap("xfd")
    print("--- готово")


if __name__ == "__main__":
    asyncio.run(main())
