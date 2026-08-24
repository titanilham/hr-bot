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
    import time as _time
    uniq_phone = "+7 70" + str(int(_time.time()) % 100000000)
    await tap("add")
    check("шаг ФИО", any("ФИО" in t for t in last_texts()))
    await send("Е2е Тестовый Сотрудник")
    check("шаг телефон", any("елефон" in t for t in last_texts()))
    await send(uniq_phone)
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
    await tap("addsave")
    saved_tail = [t for name, t in bot.sent if name == "SendMessage"][-2:]
    check("сотрудник сохранен", any("сохранен" in t.lower() for t in saved_tail),
          str(saved_tail))

    import re as _re
    new_eid = None
    for t in reversed(saved_tail):
        m = _re.search(r"EMP-\d{4}", t)
        if m:
            new_eid = m.group(0)
            break

    new_emp = None
    if new_eid:
        for _ in range(10):
            for e in await db.get_employees(fresh=True):
                if e.eid == new_eid:
                    new_emp = e
                    break
            if new_emp:
                break
            await asyncio.sleep(0.5)
    check("новый сотрудник в таблице", new_emp is not None)

    # 14. полный цикл перевода со пропусками (без записи в таблицу)
    other = new_emp or next((e for e in emps if e.is_active and e.eid != target.eid), target)
    await tap(f"xfer:{other.eid}")
    check("перевод: запрос должности", any("олжность" in t for t in last_texts()))
    await tap("xfskip_pos")
    check("перевод: запрос отдела", any("тдел" in t for t in last_texts()))
    await tap("xfskip_dept")
    check("перевод: запрос руководителя", any("уководител" in t for t in last_texts()))
    await tap("xfskip_sup")
    check("перевод: дата", any("ата изменения" in t for t in last_texts()))
    await tap("xftoday")
    check("перевод: ничего не менялось", any("Ничего не изменено" in t
                                             for t in last_texts()), str(last_texts(1)))

    # 15. перевод с реальным изменением должности (запись в историю)
    await tap(f"xfer:{other.eid}")
    await send("Старший тест-инженер")
    await tap("xfskip_dept")
    await tap("xfskip_sup")
    await tap("xftoday")
    check("перевод: подтверждение", any("Проверьте изменения" in t for t in last_texts()))
    await tap("xfd")
    check("перевод применен", any("Перевод оформлен" in t for t in last_texts()))
    hist_after = await db.get_history(other.eid)
    check("история перевода записана",
          any(r[3] == "перевод" and r[5] == "Старший тест-инженер" for r in hist_after))

    # 16. увольнение с подтверждением (полный путь записи)
    await tap(f"fire:{other.eid}")
    check("увольнение: выбор причины", any("ыберите причину" in t for t in last_texts()),
          str(last_texts(2)))
    await tap("fri:0")
    check("увольнение: дата", any("ата увольнения" in t for t in last_texts()))
    await tap("frdtoday")
    check("увольнение: комментарий", any("омментарий" in t for t in last_texts()))
    await tap("fcskip")
    check("увольнение: предпросмотр", any("Проверьте данные увольнения" in t
                                          for t in last_texts()))
    await tap("fgo")
    fired_db = await db.find_employee_by_id(other.eid)
    check("статус Уволен в таблице",
          fired_db is not None and fired_db.status == "Уволен")
    dis = await db.get_dismissals()
    check("запись в листе Увольнения",
          any(r and r[0].strip() == other.eid for r in dis))

    # 17. редактирование карточки: открыть список полей и вернуться
    await tap(f"edit:{target.eid}")
    check("редактирование: список полей", any("Что изменить" in t for t in last_texts()))
    await tap(f"card:{target.eid}")
    check("возврат к карточке", any("Стаж" in t for t in last_texts()))

    # 18. настройки (панель, пользователи, справочники)
    await tap("set")
    check("панель настроек", any("астройки" in t for t in last_texts()))
    await tap("set:users")
    check("список пользователей", any(str(UID) in t for t in last_texts()))
    await tap("set:dicts")
    check("категории справочников", any("выберите список" in t for t in last_texts()))
    await tap("dcat:0")
    check("просмотр отделов", any(dicts.departments[0] in t for t in last_texts())
          if dicts.departments else False)

    # 18a. Смена роли: безопасная механика вместо слепого цикла
    def last_answer() -> str:
        ans = [t for name, t in bot.sent if name == "AnswerCallbackQuery"]
        return ans[-1] if ans else ""

    from bot.models import ROLE_ADMIN, ROLE_HR, ROLE_MANAGER

    OTHER_UID = 999000001
    await db.user_upsert(OTHER_UID, "Е2е Второй", ROLE_HR)
    auth.invalidate(OTHER_UID)

    await tap(f"urole:{UID}")
    check("сменить роль на себе запрещена",
          "собственную роль" in last_answer(), last_answer())

    await tap(f"urole:{OTHER_UID}")
    check("меню выбора роли открывается",
          any("Выберите новую роль" in t for t in last_texts()), str(last_texts(1)))
    other_after_menu = await db.user_find(OTHER_UID)
    check("роль не изменилась без подтверждения",
          other_after_menu is not None and other_after_menu.role == ROLE_HR)

    await tap(f"uset:{OTHER_UID}:{ROLE_ADMIN}")
    other_promoted = await db.user_find(OTHER_UID)
    check("роль применена по подтверждению",
          other_promoted is not None and other_promoted.role == ROLE_ADMIN)

    await tap(f"uset:{OTHER_UID}:{ROLE_MANAGER}")
    other_demoted = await db.user_find(OTHER_UID)
    check("понижение второго админа работает при двух админах",
          other_demoted is not None and other_demoted.role == ROLE_MANAGER)

    # последний админ: временно понижаем себя до HR, в системе остается один админ
    me_before = await db.user_find(UID)
    await db.user_upsert(UID, me_before.name, ROLE_HR,
                         notifications=me_before.notifications)
    auth.invalidate(UID)
    await db.user_upsert(OTHER_UID, other_demoted.name, ROLE_ADMIN,
                         notifications=other_demoted.notifications)

    await tap(f"uset:{OTHER_UID}:{ROLE_MANAGER}")
    check("нельзя понизить последнего админа",
          "администратор" in last_answer(), last_answer())
    still_admin = await db.user_find(OTHER_UID)
    check("роль последнего админа не изменилась",
          still_admin is not None and still_admin.role == ROLE_ADMIN)

    await tap(f"udel:{OTHER_UID}")
    check("нельзя удалить последнего админа",
          "последнего администратора" in last_answer(), last_answer())

    # восстановление: снова админ, второй возвращаем в manager
    await db.user_upsert(UID, me_before.name, ROLE_ADMIN,
                         notifications=me_before.notifications)
    auth.invalidate(UID)
    await tap(f"uset:{OTHER_UID}:{ROLE_MANAGER}")
    restored_other = await db.user_find(OTHER_UID)
    check("после восстановления смена роли работает",
          restored_other is not None and restored_other.role == ROLE_MANAGER)
    await db.user_delete(OTHER_UID)

    # 19. остальные периоды отчета
    for kind, label in (("rep:t", "Сегодня"), ("rep:w", "Эта неделя"), ("rep:pm", "Прошлый месяц")):
        await tap(kind)
        check(f"отчет {label}", any(label in t for t in last_texts()))

    # 20. события: годовщины, новые, увольнения
    await tap("evt:anniv")
    check("годовщины список", any("одовщины" in t for t in last_texts()))
    await tap("evt:new")
    check("новые сотрудники", any("овые сотрудники" in t for t in last_texts()))
    await tap("evt:dis")
    check("увольнения список", any("вольнения" in t for t in last_texts()))

    print()
    print(f"Итог: {len(PASSED)} прошло, {len(FAILED)} упало")
    if FAILED:
        print("Упавшие шаги:", ", ".join(FAILED))
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
