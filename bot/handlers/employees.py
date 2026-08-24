"""Раздел 👥 Сотрудники: фильтры, пагинация, карточка, история, редактирование."""

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import bot.keyboards as kb
from bot.models import STATUS_FIRED, Dicts, Employee, User
from bot.services.sheets import SheetsDB, SheetsUnavailable
from bot.texts import EMPLOYEE_NOT_FOUND, SAVE_FAILED
from bot.utils.dates import fmt_date, parse_date

log = logging.getLogger(__name__)
router = Router()


class EditEmp(StatesGroup):
    waiting_value = State()


FILTER_TITLES = {
    "all": "Все сотрудники",
    "act": "Работающие",
    "fired": "Уволенные",
    "proba": "На испытательном сроке",
}


def resolve_filter(dicts: Dicts, key: str, today: date):
    """Возвращает (заголовок, предикат)."""
    if key == "all":
        return FILTER_TITLES["all"], lambda e: True
    if key == "act":
        return FILTER_TITLES["act"], lambda e: e.is_active
    if key == "fired":
        return FILTER_TITLES["fired"], lambda e: not e.is_active
    if key == "proba":
        return FILTER_TITLES["proba"], lambda e: e.on_probation(today)
    if key.startswith("dep-"):
        idx = int(key[4:])
        if 0 <= idx < len(dicts.departments):
            name = dicts.departments[idx]
            return f"Отдел: {name}", lambda e: e.dept == name
    if key.startswith("br-"):
        idx = int(key[3:])
        if 0 <= idx < len(dicts.branches):
            name = dicts.branches[idx]
            return f"Филиал: {name}", lambda e: e.branch == name
    return FILTER_TITLES["all"], lambda e: True


def card_text(e: Employee, today: date) -> str:
    proba = f"до {e.probation_end}" if e.probation_end else "—"
    lines = [
        f"👤 <b>{e.fio}</b>  (<code>{e.eid}</code>)",
        "",
        f"Должность: {e.pos or '—'}",
        f"Отдел: {e.dept or '—'}",
        f"Филиал: {e.branch or '—'}",
        f"Руководитель: {e.supervisor or '—'}",
        f"Телефон: {e.phone or '—'}",
        f"🎂 Дата рождения: {e.birthday or '—'}",
        f"📅 Дата приема: {e.hire_date or '—'}",
        f"⏳ Испытательный срок: {proba}",
        f"📌 Статус: {e.status_label(today)}",
        f"📆 Стаж: {e.tenure(today) or '—'}",
    ]
    if e.comment:
        lines.append(f"\n💬 {e.comment}")
    return "\n".join(lines)


async def find_emp(db: SheetsDB, eid: str) -> Employee | None:
    emps = await db.get_employees(fresh=True)
    eid_u = eid.strip().upper()
    for e in emps:
        if e.eid.upper() == eid_u:
            return e
    return None


# --------------------------------------------------------------------------
# Меню фильтров
# --------------------------------------------------------------------------

@router.callback_query(F.data == "emp")
async def cb_emp(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await cb.message.answer("👥 Сотрудники — выберите фильтр:",
                            reply_markup=kb.employees_filters())


@router.callback_query(F.data.in_({"fdep", "fbr"}))
async def cb_filter_dicts(cb: CallbackQuery, db: SheetsDB):
    await cb.answer()
    dicts = await db.dicts()
    if cb.data == "fdep":
        values = dicts.departments
        prefix, title = "empl:dep-", "🏬 Выберите отдел:"
    else:
        values = dicts.branches
        prefix, title = "empl:br-", "📍 Выберите филиал:"
    if not values:
        await cb.message.answer("Справочник пуст. Добавьте значения: ⚙ Настройки → 📚 Справочники.")
        return
    await cb.message.answer(title, reply_markup=kb.dict_list_keyboard(prefix, values, "emp"))


# --------------------------------------------------------------------------
# Постраничный список
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("empl:"))
async def cb_list(cb: CallbackQuery, db: SheetsDB):
    parts = cb.data.split(":")
    key = parts[1] if len(parts) > 1 else "all"
    # Кнопки из справочника могут прийти без страницы (empl:dep-0) — считаем её первой
    page = max(0, int(parts[2])) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else 0
    today = date.today()
    dicts = await db.dicts()
    title, pred = resolve_filter(dicts, key, today)

    emps = [e for e in await db.get_employees() if pred(e)]
    emps.sort(key=lambda e: e.fio.lower())

    if not emps:
        await cb.answer()
        await cb.message.answer(f"👥 {title}\n\nСотрудники не найдены.",
                                reply_markup=kb.employees_filters())
        return

    total_pages = (len(emps) + kb.PAGE_SIZE - 1) // kb.PAGE_SIZE
    page = min(page, total_pages - 1)
    chunk = emps[page * kb.PAGE_SIZE:(page + 1) * kb.PAGE_SIZE]
    items = [(page * kb.PAGE_SIZE + i + 1, e) for i, e in enumerate(chunk)]

    status_note = ""
    if key == "all":
        active = sum(1 for e in emps if e.is_active)
        status_note = f" (работают: {active}, уволены: {len(emps) - active})"

    text = (f"👥 {title}{status_note}\n"
            f"Всего: {len(emps)} · стр. {page + 1} из {total_pages}\n\n"
            "Нажмите на фамилию, чтобы открыть карточку.")
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.employees_page(items, page, total_pages, key))


# --------------------------------------------------------------------------
# Карточка и история
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("card:"))
async def cb_card(cb: CallbackQuery, state: FSMContext, db: SheetsDB, user: User):
    await state.clear()
    eid = cb.data.split(":", 1)[1]
    e = await find_emp(db, eid)
    await cb.answer()
    if not e:
        await cb.message.answer(EMPLOYEE_NOT_FOUND)
        return
    await cb.message.answer(card_text(e, date.today()),
                            reply_markup=kb.card_keyboard(e.eid, user.is_full_access))


@router.callback_query(F.data.startswith("hist:"))
async def cb_history(cb: CallbackQuery, state: FSMContext, db: SheetsDB):
    await state.clear()
    eid = cb.data.split(":", 1)[1]
    e = await find_emp(db, eid)
    await cb.answer()
    if not e:
        await cb.message.answer(EMPLOYEE_NOT_FOUND)
        return
    rows = await db.get_history(eid)
    if not rows:
        await cb.message.answer(f"📜 История {e.fio} пуста.")
        return
    lines = [f"📜 История: {e.fio} (<code>{eid}</code>)\n"]
    for r in rows:
        # ID | ФИО | Дата | Тип | Старое | Новое | Комментарий | Кто
        d, typ, old, new = r[2], r[3], r[4], r[5]
        line = f"• {d} — {typ}"
        if old or new:
            line += f"\n  {old or '—'} → {new or '—'}"
        if len(r) > 7 and r[7]:
            line += f"\n  ({r[7]})"
        lines.append(line)
    for i in range(0, len(lines), 40):
        await cb.message.answer("\n\n".join(lines[i:i + 40]))


# --------------------------------------------------------------------------
# Редактирование полей карточки
# --------------------------------------------------------------------------

DATE_FIELDS = {"birthday": "Дата рождения", "hire_date": "Дата приема",
               "probation_end": "Испытательный срок"}
FIELD_ATTRS = {
    "fio": "fio", "phone": "phone", "gender": "gender", "dept": "dept",
    "pos": "pos", "branch": "branch", "supervisor": "supervisor",
    "birthday": "birthday", "hire_date": "hire_date",
    "probation_end": "probation_end", "comment": "comment",
}


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit(cb: CallbackQuery, db: SheetsDB, user: User):
    if not user.is_full_access:
        await cb.answer("⛔ Недостаточно прав", show_alert=True)
        return
    eid = cb.data.split(":", 1)[1]
    e = await find_emp(db, eid)
    await cb.answer()
    if not e:
        await cb.message.answer(EMPLOYEE_NOT_FOUND)
        return
    await cb.message.answer(f"✏ Что изменить у {e.fio}?",
                            reply_markup=kb.edit_fields_keyboard(eid))


@router.callback_query(F.data.startswith("edf:"))
async def cb_edit_field(cb: CallbackQuery, state: FSMContext, user: User):
    if not user.is_full_access:
        await cb.answer("⛔ Недостаточно прав", show_alert=True)
        return
    _, eid, field = cb.data.split(":")
    if field not in FIELD_ATTRS:
        await cb.answer("Неизвестное поле")
        return
    await cb.answer()
    await state.set_state(EditEmp.waiting_value)
    await state.update_data(eid=eid, field=field)
    if field == "gender":
        await cb.message.answer("Выберите пол:", reply_markup=kb.choice_keyboard("edg", kb.GENDER_OPTIONS))
        return
    title = kb.EDITABLE_FIELDS[field]
    if field in DATE_FIELDS:
        hint = "\nФормат: ДД.ММ.ГГГГ. Отправьте «-», чтобы очистить."
    elif field == "comment":
        hint = "\nОтправьте «-», чтобы очистить."
    else:
        hint = ""
    await cb.message.answer(f"✏ {title}:\nВведите новое значение{hint}",
                            reply_markup=kb.simple_cancel_keyboard(f"card:{eid}", "❌ Не менять"))


@router.callback_query(F.data.startswith("edg:"))
async def cb_edit_gender(cb: CallbackQuery, db: SheetsDB, user: User, state: FSMContext):
    _, val = cb.data.split(":")
    data = await state.get_data()
    eid = data.get("eid")
    if not eid:
        await cb.answer("Сессия истекла, откройте карточку заново", show_alert=True)
        return
    await apply_edit(cb, db, user, state, eid, "gender", val)


@router.message(StateFilter(EditEmp.waiting_value), F.text)
async def msg_edit_value(message: Message, state: FSMContext, db: SheetsDB, user: User):
    data = await state.get_data()
    eid, field, raw = data["eid"], data["field"], message.text.strip()
    if field in DATE_FIELDS:
        if raw == "-":
            raw = ""
        else:
            d = parse_date(raw)
            if not d:
                await message.answer("Не понял дату. Введите в формате ДД.ММ.ГГГГ:")
                return
            raw = fmt_date(d)
    elif raw == "-":
        raw = ""
    await apply_edit_msg(message, state, db, user, eid, field, raw)


async def apply_edit_msg(message: Message, state, db, user, eid, field, value):
    try:
        e = await find_emp(db, eid)
        if not e:
            await message.answer(EMPLOYEE_NOT_FOUND)
            return
        old = getattr(e, FIELD_ATTRS[field])
        setattr(e, FIELD_ATTRS[field], value)
        await db.update_employee(e)
        await db.add_history(e.eid, e.fio, fmt_date(date.today()), "редактирование",
                             old, value, kb.EDITABLE_FIELDS[field], user.name)
        await state.clear()
        await message.answer("✅ Обновлено.")
        await message.answer(card_text(e, date.today()),
                             reply_markup=kb.card_keyboard(e.eid, user.is_full_access))
    except SheetsUnavailable:
        log.exception("Sheets unavailable on edit")
        await message.answer(SAVE_FAILED)


async def apply_edit(cb: CallbackQuery, db, user, state, eid, field, value):
    try:
        e = await find_emp(db, eid)
        if not e:
            await cb.message.answer(EMPLOYEE_NOT_FOUND)
            return
        old = getattr(e, FIELD_ATTRS[field])
        setattr(e, FIELD_ATTRS[field], value)
        await db.update_employee(e)
        await db.add_history(e.eid, e.fio, fmt_date(date.today()), "редактирование",
                             old, value, kb.EDITABLE_FIELDS[field], user.name)
        await state.clear()
        await cb.answer("✅ Обновлено")
        await cb.message.answer(card_text(e, date.today()),
                                reply_markup=kb.card_keyboard(e.eid, user.is_full_access))
    except SheetsUnavailable:
        log.exception("Sheets unavailable on edit(gender)")
        await cb.message.answer(SAVE_FAILED)
