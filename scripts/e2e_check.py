"""Сквозная проверка хендлеров через реальный диспетчер aiogram.

Telegram-сеть не используется: исходящие сообщения перехватываются,
а данные читаются/пишутся в настоящую Google-таблицу.

Запуск: python scripts/e2e_check.py
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update

from bot.config import load_config
from bot.handlers import all_routers
from bot.middlewares import AccessMiddleware
from bot.services.auth import AuthService
from bot.services.sheets import SheetsDB

PASSED = []
FAILED = []


class RecordingBot(Bot):
    """Перехватывает все исходящие вызовы к Telegram API."""

    def __init__(self, token: str):
        super().__init__(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.sent: list[tuple[str, str]] = []

    async def __call__(self, method, request_timeout: int | None = None):
        name = type(method).__name__
        text = getattr(method, "text", None)
        if text is None:
            text = str(getattr(method, "action", "") or "")
        self.sent.append((name, str(text or "")))
        return True


def make_message(user_id: int, chat_id: int, text: str, mid: int) -> Message:
    return Message(
        message_id=mid,
        date=datetime.now(),
        chat=Chat(id=chat_id, type="private"),
        from_user={"id": user_id, "is_bot": False, "first_name": "HR"},
        text=text,
    )


def make_callback(user_id: int, chat_id: int, data: str, mid: int) -> CallbackQuery:
    return CallbackQuery(
        id=str(mid),
        from_user={"id": user_id, "is_bot": False, "first_name": "HR"},
        chat_instance="e2e",
        data=data,
        message=make_message(user_id, chat_id, "...", mid),
    )


async def feed(bot: RecordingBot, dp: Dispatcher, obj, uid: int, cid: int, update_id: int):
    if isinstance(obj, Message):
        upd = Update(update_id=update_id, message=obj)
    else:
        upd = Update(update_id=update_id, callback_query=obj)
    await dp.feed_update(bot, upd)


def check(name: str, cond: bool, detail: str = ""):
    mark = "PASS" if cond else "FAIL"
    (PASSED if cond else FAILED).append(name)
    print(f"[{mark}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


async def main() -> int:
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

    UID = 1456945518  # админ из .env
    CID = UID
    seq = {"n": 100}

    async def send(text: str):
        seq["n"] += 1
        await feed(bot, dp, make_message(UID, CID, text, seq["n"]), UID, CID, seq["n"])

    async def tap(data: str):
        seq["n"] += 1
        await feed(bot, dp, make_callback(UID, CID, data, seq["n"]), UID, CID, seq["n"])

    def last_texts(n: int = 3) -> list[str]:
        sends = [t for name, t in bot.sent if name == "SendMessage"]
        return sends[-n:]

    # 1. /start -> меню
    await send("/start")
    check("меню открывается", any("HR" in t for t in last_texts()))

    # 2. фильтры сотрудников
    await tap("emp")
    check("подменю фильтров", any("фильтр" in t.lower() for t in last_texts()))

    # 3. список всех (пагинация)
    await tap("empl:all:0")
    check("список всех сотрудников", any("Всего:" in t for t in last_texts()),
          str(last_texts(1)))

    # 4. работающие
    await tap("empl:act:0")
    check("фильтр работающих", any("Работающие" in t for t in last_texts()))

    # 5. испытательный срок
    await tap("empl:proba:0")
    check("фильтр ИС", any("испытательном" in t for t in last_texts()))

    # 6. по отделам
    await tap("fdep")
    check("выбор отдела", any("отдел" in t.lower() for t in last_texts()))
    dicts = await db.dicts()
    if dicts.departments:
        await tap(f"empl:dep-0:0")
        check("фильтр по отделу", any(dicts.departments[0] in t or "Сотрудники" in t
                                      for t in last_texts()))

    # 7. карточка
    emps = await db.get_employees()
    target = next((e for e in emps if e.eid == "EMP-0001"), emps[0])
    await tap(f"card:{target.eid}")
    check("карточка со стажем", any("Стаж" in t for t in last_texts()),
          str(last_texts(1)))

    # 8. история
    await tap(f"hist:{target.eid}")
    check("история карточки", any("История" in t for t in last_texts()))

    # 9. события: ДР
    await tap("evt:bdy")
    check("список ДР", any("Дни рождения" in t for t in last_texts()))

    # 10. события: испытательные сроки
    await tap("evt:proba")
    check("список ИС", any("Испытательные сроки" in t for t in last_texts()))

    # 11. отчет за месяц
    await tap("rep:m")
    check("HR-отчет", any("HR-ОТЧЕТ" in t for t in last_texts()), str(last_texts(1)))

    # 12. поиск
    await tap("srch")
    check("промпт поиска", any("Введите ФИО" in t for t in last_texts()))
    await send("Кассир")
    check("результаты поиска", any("Найдено" in t for t in last_texts()))

    # 13. мастер добавления (до предпросмотра, без сохранения)
    await tap("add")
    check("шаг ФИО", any("ФИО" in t for t in last_texts()))
    await send("Е2е Тестовый Сотрудник")
    check("шаг телефон", any("елефон" in t for t in last_texts()))
    await send("+7 701 555 66 77")
    check("выбор отдела", any("Отдел" in t for t in last_texts()))
    if dicts.departments:
        await tap("addd:dept:0")
    else:
        await send("IT-отдел")
    check("выбор должности", any("олжность" in t for t in last_texts()))
    if dicts.positions:
        await tap("addd:pos:0")
    else:
        await send("Разработчик")
    check("выбор филиала", any("илиал" in t for t in last_texts()))
    if dicts.branches:
        await tap("addd:branch:0")
    else:
        await send("Центральный офис")
    check("выбор руководителя", any("уководител" in t for t in last_texts()))
    if dicts.supervisors:
        await tap("addd:supervisor:0")
    else:
        await send("Ким Ольга")
    check("дата рождения", any("рождения" in t.lower() for t in last_texts()))
    await send("01.01.1999")
    check("дата приема", any("приема" in t for t in last_texts()))
    from bot.utils.dates import fmt_date
    from datetime import date, timedelta
    await send(fmt_date(date.today() - timedelta(days=10)))
    check("испытательный срок", any("спытательный" in t for t in last_texts()))
    await tap("addp:m3")
    check("пол", any("Пол" in t for t in last_texts()))
    await tap("addg:M")
    check("комментарий", any("омментарий" in t for t in last_texts()))
    await tap("addskip_comment")
    check("предпросмотр", any("Проверьте данные" in t for t in last_texts()),
          str(last_texts(1)))
    await tap("addcancel")
    check("отмена мастера", any("отменен" in t.lower() for t in last_texts()))

    print()
    print(f"Итог: {len(PASSED)} прошло, {len(FAILED)} упало")
    if FAILED:
        print("Упавшие шаги:", ", ".join(FAILED))
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
