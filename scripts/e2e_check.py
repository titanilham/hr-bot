"""End-to-end handler checks through a real aiogram dispatcher."""

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
    """Intercepts all outgoing Telegram API calls."""

    def __init__(self, token: str):
        super().__init__(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.sent: list[tuple[str, str]] = []
        self.markups: list[list[list[str]]] = []  # button texts per row

    async def __call__(self, method, request_timeout: int | None = None):
        name = type(method).__name__
        text = getattr(method, "text", None)
        if text is None:
            text = str(getattr(method, "action", "") or "")
        self.sent.append((name, str(text or "")))
        markup = getattr(method, "reply_markup", None)
        rows = []
        ik = getattr(markup, "inline_keyboard", None) if markup is not None else None
        if ik:
            rows = [[f"{b.text}|{b.callback_data}" for b in row] for row in ik]
        self.markups.append(rows)
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

    UID = 1456945518  # admin uid from .env
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

    def last_markup() -> list[list[str]]:
        return bot.markups[-1] if bot.markups else []

    def cb_from_last_markup(substr: str) -> str | None:
        for row in last_markup():
            for btn in row:
                if substr in btn:
                    return btn.split("|", 1)[1]
        return None

    def has_in_last_markup(substr: str) -> bool:
        return any(substr in btn for row in last_markup() for btn in row)

    # 1. /start -> menu
    await send("/start")
    check("меню открывается", any("HR" in t for t in last_texts()))

    # 2. employee filters
    await tap("emp")
    check("подменю фильтров", any("фильтр" in t.lower() for t in last_texts()))

    # 3. all employees (pagination)
    await tap("empl:all:0")
    check("список всех сотрудников", any("Всего:" in t for t in last_texts()),
          str(last_texts(1)))
    grid = last_markup()
    check("сетка списка 2 в ряд",
          bool(grid) and len(grid[0]) == 2,
          str(grid[:2]))

    dicts = await db.dicts()
    await tap("fdep")
    check("выбор отдела", any("отдел" in t.lower() for t in last_texts()))
    dep_cb = cb_from_last_markup("empl:dep-")
    if dicts.departments and dep_cb:
        await tap(dep_cb)  # exact callback Telegram sends
        check("фильтр по отделу (реальная кнопка)",
              any("Отдел:" in t for t in last_texts()), str(last_texts(1)))
    await tap("emp")
    await tap("fbr")
    br_cb = cb_from_last_markup("empl:br-")
    if dicts.branches and br_cb:
        await tap(br_cb)
        check("фильтр по филиалу (реальная кнопка)",
              any("Филиал:" in t for t in last_texts()), str(last_texts(1)))

    # 4. active
    await tap("empl:act:0")
    check("фильтр работающих", any("Работающие" in t for t in last_texts()))

    # 5. probation filter
    await tap("empl:proba:0")
    check("фильтр ИС", any("испытательном" in t for t in last_texts()))

    # 6. by department
    await tap("fdep")
    check("выбор отдела", any("отдел" in t.lower() for t in last_texts()))
    dicts = await db.dicts()
    if dicts.departments:
        await tap(f"empl:dep-0:0")
        check("фильтр по отделу", any(dicts.departments[0] in t or "Сотрудники" in t
                                      for t in last_texts()))

    # 7. card
    emps = await db.get_employees()
    target = next((e for e in emps if e.eid == "EMP-0001"), emps[0])
    await tap(f"card:{target.eid}")
    check("карточка со стажем", any("Стаж" in t for t in last_texts()),
          str(last_texts(1)))

    # 8. history
    await tap(f"hist:{target.eid}")
    check("история карточки", any("История" in t for t in last_texts()))

    # 9. events: birthdays
    await tap("evt:bdy")
    check("список ДР", any("Дни рождения" in t for t in last_texts()))

    # 10. events: probation
    await tap("evt:proba")
    check("список ИС", any("Испытательные сроки" in t for t in last_texts()))

    # 11. monthly report
    await tap("rep:m")
    check("HR-отчет", any("HR-ОТЧЕТ" in t for t in last_texts()), str(last_texts(1)))

    # 12. search
    await tap("srch")
    check("промпт поиска", any("Введите ФИО" in t for t in last_texts()))
    await send("Кассир")
    check("результаты поиска", any("Найдено" in t for t in last_texts()))

    # 13. add wizard (up to preview, no save)
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

    # 14. transfer with skips (no writes)
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

    # 15. transfer with real change (history written)
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

    # 16. dismissal with confirmation
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

    # 17. edit fields open/back
    await tap(f"edit:{target.eid}")
    check("редактирование: список полей", any("Что изменить" in t for t in last_texts()))
    await tap(f"card:{target.eid}")
    check("возврат к карточке", any("Стаж" in t for t in last_texts()))

    # 18. settings (panel, users, dicts)
    await tap("set")
    check("панель настроек", any("астройки" in t for t in last_texts()))
    await tap("set:users")
    check("список пользователей", any(str(UID) in t for t in last_texts()))
    await tap("set:dicts")
    check("категории справочников", any("выберите список" in t for t in last_texts()))
    await tap("dcat:0")
    check("просмотр отделов", any(dicts.departments[0] in t for t in last_texts())
          if dicts.departments else False)

    # 18a. role change safety checks
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

    # demote self to HR leaving OTHER as last admin
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

    # restore self to admin, other back to manager
    await db.user_upsert(UID, me_before.name, ROLE_ADMIN,
                         notifications=me_before.notifications)
    auth.invalidate(UID)
    await tap(f"uset:{OTHER_UID}:{ROLE_MANAGER}")
    restored_other = await db.user_find(OTHER_UID)
    check("после восстановления смена роли работает",
          restored_other is not None and restored_other.role == ROLE_MANAGER)
    await db.user_delete(OTHER_UID)

    # 18b. add wizard: no-supervisor button (no save)
    await tap("add")
    await send("Е2е Без Руководителя")
    await send("+7 7011122233")
    if dicts.departments:
        await tap("addd:dept:0")
    else:
        await send("IT-отдел")
    if dicts.positions:
        await tap("addd:pos:0")
    else:
        await send("Разработчик")
    if dicts.branches:
        await tap("addd:branch:0")
    else:
        await send("Центральный офис")
    sup_markup = last_markup()
    check("кнопка Нет руководителя в мастере",
          any("Нет руководителя" in b for row in sup_markup for b in row),
          str(sup_markup))
    await tap("addd:supervisor:none")
    check("после нет руководителя шаг даты рождения",
          any("рождения" in t.lower() for t in last_texts()), str(last_texts(1)))
    await send("02.02.1995")
    await send(fmt_date(date.today() - timedelta(days=5)))
    await tap("addp:m3")
    await tap("addg:F")
    await tap("addskip_comment")
    preview_tail = [t for name, t in bot.sent if name == "SendMessage"][-1]
    check("в превью руководитель пустой", "Руководитель: —" in preview_tail,
          preview_tail)
    await tap("addcancel")

    # 18c. timezone setting
    from bot.utils.dates import normalize_timezone as _ntz
    check("нормализация пояса: МСК",
          _ntz("мск") == "Europe/Moscow" and _ntz("+3") == "Etc/GMT-3")

    await tap("set")
    tz_markup = None
    await tap("set:tz")
    tz_markup = last_markup()
    check("меню выбора пояса открылось",
          any("МСК" in b for row in tz_markup for b in row), str(tz_markup))
    await tap("tzp:0")
    saved_tz = await db.setting_get("timezone", "")
    check("пояс сохранен в настройках",
          saved_tz == "Europe/Moscow", f"saved={saved_tz}")

    # 19. other report periods
    for kind, label in (("rep:t", "Сегодня"), ("rep:w", "Эта неделя"), ("rep:pm", "Прошлый месяц")):
        await tap(kind)
        check(f"отчет {label}", any(label in t for t in last_texts()))

    # 20. events: anniversaries/new/fired
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
