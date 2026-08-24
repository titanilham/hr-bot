"""Seed demo data into Google Sheets."""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from bot.config import load_config  # noqa: E402
from bot.models import STATUS_FIRED, Employee  # noqa: E402
from bot.services.sheets import SheetsDB, SheetsUnavailable  # noqa: E402
from bot.utils.dates import add_months, fmt_date  # noqa: E402

TODAY = date.today()


def d(days: int) -> str:
    """Date relative to today."""
    return fmt_date(TODAY + timedelta(days=days))


def months_ago(n: int) -> str:
    return fmt_date(add_months(TODAY, -n))


DEPARTMENTS = ["Розница", "Касса", "Склад", "Офис", "IT-отдел"]
POSITIONS = ["Бариста", "Старший бариста", "Кассир", "Администратор",
             "Кладовщик", "HR-менеджер", "Разработчик"]
BRANCHES = ["Магазин №7", "Магазин №3", "Центральный офис", "Склад №1"]
SUPERVISORS = ["Петрова Анна", "Смирнов Игорь", "Ким Ольга"]

# row: fio, gender, dept, pos, branch, supervisor,
# bday, hire, probation end, [fired date, reason], comment
PEOPLE = [
    # --- special cases for notifications ---
    dict(fio="Иванова Алина", gender="Ж", dept="Розница", pos="Бариста",
         branch="Магазин №7", sup="Петрова Анна",
         bday=d(3), hire=months_ago(14), proba="",
         comment="Демо: ДР через 3 дня"),
    dict(fio="Петров Максим", gender="М", dept="Касса", pos="Кассир",
         branch="Магазин №3", sup="Смирнов Игорь",
         bday=d(0), hire=months_ago(8), proba=d(-30),
         comment="Демо: сегодня ДР"),
    dict(fio="Сидорова Мария", gender="Ж", dept="Розница", pos="Старший бариста",
         branch="Магазин №7", sup="Петрова Анна",
         bday=d(120), hire=months_ago(1), proba=d(7),
         comment="Демо: ИС через 7 дней"),
    dict(fio="Козлов Дмитрий", gender="М", dept="Склад", pos="Кладовщик",
         branch="Склад №1", sup="Ким Ольга",
         bday=d(200), hire=months_ago(2), proba=d(3),
         comment="Демо: ИС через 3 дня"),
    dict(fio="Морозова Елена", gender="Ж", dept="Офис", pos="Администратор",
         branch="Центральный офис", sup="Ким Ольга",
         bday=d(45), hire=months_ago(1), proba=d(0),
         comment="Демо: ИС заканчивается сегодня"),
    dict(fio="Новиков Сергей", gender="М", dept="IT-отдел", pos="Разработчик",
         branch="Центральный офис", sup="Смирнов Игорь",
         bday=d(300), hire=fmt_date(TODAY),
         proba=fmt_date(add_months(TODAY, 3)),
         comment="Демо: принят сегодня"),
    dict(fio="Годков Виктор", gender="М", dept="Офис", pos="HR-менеджер",
         branch="Центральный офис", sup="Ким Ольга",
         bday=d(90),
         hire=fmt_date((TODAY + timedelta(days=7)).replace(year=TODAY.year - 3)),
         proba="",
         comment="Демо: годовщина 3 года через 7 дней"),
    # --- regular employees ---
    dict(fio="Волкова Ольга", gender="Ж", dept="Розница", pos="Бариста",
         branch="Магазин №3", sup="Петрова Анна",
         bday="12.03.1999", hire=months_ago(20), proba="", comment=""),
    dict(fio="Соколов Артем", gender="М", dept="Касса", pos="Старший бариста",
         branch="Магазин №7", sup="Смирнов Игорь",
         bday="07.07.1994", hire=months_ago(26), proba="",
         comment="Переведен из кассиров"),
    dict(fio="Лебедева Анна", gender="Ж", dept="Офис", pos="Администратор",
         branch="Центральный офис", sup="Ким Ольга",
         bday="25.11.1990", hire=months_ago(33), proba="", comment=""),
    dict(fio="Егоров Павел", gender="М", dept="Склад", pos="Кладовщик",
         branch="Склад №1", sup="Ким Ольга",
         bday="02.02.1988", hire=months_ago(40), proba="", comment=""),
    dict(fio="Захарова Юлия", gender="Ж", dept="Розница", pos="Бариста",
         branch="Магазин №7", sup="Петрова Анна",
         bday="18.05.2001", hire=fmt_date(TODAY.replace(day=1)),
         proba=fmt_date(add_months(TODAY, 2)),
         comment="Принята в этом месяце"),
    dict(fio="Киселев Роман", gender="М", dept="IT-отдел", pos="Разработчик",
         branch="Центральный офис", sup="Смирнов Игорь",
         bday="30.04.1996",
         hire=fmt_date(TODAY.replace(day=max(TODAY.day - 5, 1))),
         proba=fmt_date(add_months(TODAY, 3)), comment="Принят в этом месяце"),
    dict(fio="Фомина Дарья", gender="Ж", dept="Касса", pos="Кассир",
         branch="Магазин №3", sup="Смирнов Игорь",
         bday="09.09.2003", hire=months_ago(5),
         proba=fmt_date(add_months(TODAY, 1)), comment=""),
    dict(fio="Гуров Антон", gender="М", dept="Розница", pos="Бариста",
         branch="Магазин №3", sup="Петрова Анна",
         bday="21.06.1997", hire=months_ago(11),
         proba=fmt_date(add_months(TODAY, 1)), comment=""),
    dict(fio="Титова Вера", gender="Ж", dept="Офис", pos="HR-менеджер",
         branch="Центральный офис", sup="Ким Ольга",
         bday="14.12.1992", hire=months_ago(50), proba="", comment=""),
    # --- fired (kept in db) ---
    dict(fio="Ушкин Тест", gender="М", dept="Розница", pos="Бариста",
         branch="Магазин №7", sup="Петрова Анна",
         bday="01.01.1995", hire=months_ago(13), proba="",
         fired=d(-2), reason="По собственному желанию",
         comment="Демо: уволен 2 дня назад"),
    dict(fio="Расформов Иван", gender="М", dept="Склад", pos="Кладовщик",
         branch="Склад №1", sup="Ким Ольга",
         bday="17.10.1989", hire=months_ago(9), proba="",
         fired=d(-10), reason="Не прошел испытательный срок",
         comment="Демо: ИС не пройден"),
]


async def main(force: bool) -> None:
    cfg = load_config()
    db = SheetsDB(cfg)

    print("Подключаюсь к Google Sheets...")
    try:
        await db.ensure_structure()
    except SheetsUnavailable as e:
        print(f"Не удалось подключиться: {e}")
        print("Проверьте service_account.json и что таблица расшарена на email")
        print("сервисного аккаунта (Редактор). Инструкция — README.md.")
        sys.exit(1)
    print("OK: структура листов готова.")

    existing = await db.get_employees()
    if existing and not force:
        print(f"-- В таблице уже {len(existing)} сотрудников. "
              "Для перезаписи запустите с флагом --force")
        return
    if force and existing:
        print("--force: очищаю листы данных...")
        for title in ("Сотрудники", "История", "Увольнения"):
            await db.clear_sheet_data(title)
        print("OK: данные удалены.")

    dicts = await db.dicts()
    if not dicts.departments:
        await db.dict_append_many(0, DEPARTMENTS)
        await db.dict_append_many(1, POSITIONS)
        await db.dict_append_many(2, BRANCHES)
        await db.dict_append_many(3, SUPERVISORS)
        print("OK: справочники заполнены.")
    else:
        print("-- справочники уже заполнены, пропускаю")

    who = "demo"
    count = 0
    phones = iter(f"+7 70{1000000 + i * 111111}" for i in range(len(PEOPLE)))
    transfers_plan = []
    for p in PEOPLE:
        emp = Employee(
            fio=p["fio"], phone=next(phones), gender=p["gender"],
            dept=p["dept"], pos=p["pos"], branch=p["branch"], supervisor=p["sup"],
            birthday=p["bday"], hire_date=p["hire"],
            probation_end=p.get("proba", ""),
            status=STATUS_FIRED if p.get("fired") else "Работает",
            fire_date=p.get("fired", ""),
            comment=p.get("comment", ""),
            created_at=fmt_date(TODAY), created_by=who,
        )
        eid = await db.next_emp_id()
        emp.eid = eid
        await db.append_employee(emp)
        await db.add_history(eid, emp.fio, p["hire"], "принятие на работу",
                             "", f"{emp.pos} / {emp.dept}", "", who)
        if p.get("fired"):
            await db.add_dismissal([eid, emp.fio, emp.pos, emp.dept, emp.branch,
                                    p["hire"], p["fired"], p["reason"],
                                    emp.comment, who])
            await db.add_history(eid, emp.fio, p["fired"], "увольнение",
                                 "Работает", f"Уволен ({p['reason']})", "", who)
        if emp.fio == "Соколов Артем":
            transfers_plan.append((eid, emp.fio, "Кассир", "Старший бариста"))
        count += 1
    print(f"OK: добавлено сотрудников: {count}")

    when = fmt_date(TODAY.replace(day=max(TODAY.day - 3, 1)))
    for eid, fio, old_pos, new_pos in transfers_plan:
        await db.add_history(eid, fio, when, "перевод",
                             old_pos, new_pos, "повышение", who)
    print(f"OK: история переводов ({len(transfers_plan)} шт.).")

    for uid in cfg.admin_ids:
        if not await db.user_find(uid):
            await db.user_upsert(uid, "admin", "admin", True, ".env")
            print(f"OK: админ {uid} добавлен в Пользователи.")

    print("\nГотово! Запускайте бота: python main.py")
    print("Что проверить:")
    print(" • 🔎 поиск: «Иванова», «Кассир» или телефон")
    print(" • 🔔 События: ДР/годовщины/испытательные сроки из демо-данных")
    print(" • 📊 HR-отчет → Этот месяц: принятые, переводы, увольнения")
    print(" • ⚙ Настройки: время дайджеста можно поставить на пару минут вперед")
    print("   и получить дайджест с уведомлениями")


if __name__ == "__main__":
    asyncio.run(main("--force" in sys.argv))
