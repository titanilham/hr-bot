"""🔄 Кадровые изменения (переводы) с записью в историю."""

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import bot.keyboards as kb
from bot.handlers.employees import card_text, find_emp
from bot.models import User
from bot.services.sheets import SheetsDB, SheetsUnavailable
from bot.texts import EMPLOYEE_NOT_FOUND, SAVE_FAILED
from bot.utils.dates import fmt_date, parse_date

log = logging.getLogger(__name__)
router = Router()

FIELDS = [("pos", "Должность"), ("dept", "Отдел"), ("supervisor", "Руководитель")]


class Transfer(StatesGroup):
    pos = State()
    dept = State()
    sup = State()
    date = State()
    confirm = State()


STEP_STATES = {"pos": Transfer.pos, "dept": Transfer.dept,
               "supervisor": Transfer.sup}


@router.callback_query(F.data == "xfer")
async def cb_xfer_menu(cb: CallbackQuery, state: FSMContext, user: User):
    if not user.is_full_access:
        await cb.answer("⛔ Недостаточно прав", show_alert=True)
        return
    await cb.answer()
    # перенаправляем на выбор сотрудника через поиск
    from bot.handlers.search import Search
    await state.set_state(Search.waiting_query)
    await state.update_data(mode="transfer")
    await cb.message.answer(
        "🔄 Кадровые изменения.\nВведите ФИО, телефон или отдел для поиска сотрудника:",
        reply_markup=kb.simple_cancel_keyboard("menu"))


@router.callback_query(F.data.startswith("xfer:"))
async def cb_xfer_start(cb: CallbackQuery, state: FSMContext, db: SheetsDB, user: User):
    if not user.is_full_access:
        await cb.answer("⛔ Недостаточно прав", show_alert=True)
        return
    eid = cb.data.split(":", 1)[1]
    e = await find_emp(db, eid)
    await cb.answer()
    if not e:
        await cb.message.answer(EMPLOYEE_NOT_FOUND)
        return
    await state.clear()
    await state.update_data(eid=eid, changes={})
    await state.set_state(Transfer.pos)
    await cb.message.answer(
        f"🔄 Перевод: {e.fio}\n\n"
        f"Текущая должность: {e.pos or '—'}\nВведите новую должность (или нажмите «Пропустить»):",
        reply_markup=kb.simple_cancel_keyboard("xfskip_pos"))


@router.callback_query(StateFilter("*"), F.data == "xfcan")
async def cb_xfer_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Отменено")
    await cb.message.answer("❌ Перевод отменен.")


def _next_step(cur: str) -> str | None:
    order = ["pos", "dept", "supervisor"]
    idx = order.index(cur)
    return order[idx + 1] if idx + 1 < len(order) else None


async def _store_and_next(message_or_cb, state, field, value):
    data = await state.get_data()
    changes = data.setdefault("changes", {})
    if value:
        changes[field] = value
    await state.update_data(changes=changes)
    nxt = _next_step(field)
    if isinstance(message_or_cb, Message):
        send = message_or_cb.answer
    else:
        send = message_or_cb.message.answer
        await message_or_cb.answer()

    if nxt:
        titles = dict(FIELDS)
        await state.set_state(STEP_STATES[nxt])
        await send(f"{titles[nxt]}: введите новое значение (или «Пропустить»):",
                   reply_markup=kb.simple_cancel_keyboard(f"xfskip_{nxt}"))
    else:
        await state.set_state(Transfer.date)
        await send("📅 Дата изменения (ДД.ММ.ГГГГ):",
                   reply_markup=kb.today_or_input_keyboard("xftoday", "xfcan"))


@router.callback_query(StateFilter(Transfer.pos, Transfer.dept, Transfer.sup),
                       F.data.startswith("xfskip_"))
async def cb_xfer_skip(cb: CallbackQuery, state: FSMContext):
    suffix = cb.data.split("_", 1)[1]
    field = {"pos": "pos", "dept": "dept",
             "sup": "supervisor", "supervisor": "supervisor"}.get(suffix)
    if field is None:
        await cb.answer()
        return
    await _store_and_next(cb, state, field, "")


@router.callback_query(StateFilter(Transfer.date), F.data == "xftoday")
async def cb_xfer_today(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(change_date=fmt_date(date.today()))
    await _confirm(cb.message, state)


@router.message(StateFilter(Transfer.pos), F.text)
async def msg_tp(message: Message, state: FSMContext):
    await _store_and_next(message, state, "pos", message.text.strip())


@router.message(StateFilter(Transfer.dept), F.text)
async def msg_td(message: Message, state: FSMContext):
    await _store_and_next(message, state, "dept", message.text.strip())


@router.message(StateFilter(Transfer.sup), F.text)
async def msg_ts(message: Message, state: FSMContext):
    await _store_and_next(message, state, "supervisor", message.text.strip())


@router.message(StateFilter(Transfer.date), F.text)
async def msg_tdate(message: Message, state: FSMContext):
    d = parse_date(message.text.strip())
    if not d:
        await message.answer("Не понял дату. Введите ДД.ММ.ГГГГ:")
        return
    await state.update_data(change_date=fmt_date(d))
    await _confirm(message, state)


async def _confirm(message: Message, state: FSMContext):
    await state.set_state(Transfer.confirm)
    data = await state.get_data()
    changes = data.get("changes", {})
    if not changes:
        await message.answer("Ничего не изменено — перевод не требуется.")
        await state.clear()
        return
    titles = dict(FIELDS)
    eid = data["eid"]
    lines = ["Проверьте изменения:", ""]
    for k, v in changes.items():
        lines.append(f"{titles[k]}: → {v}")
    lines.append(f"Дата: {data['change_date']}")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить перевод", callback_data="xfd")
    b.button(text="❌ Отмена", callback_data="xfcan")
    b.adjust(1)
    await message.answer("\n".join(lines) + f"\n\nСотрудник: <code>{eid}</code>", reply_markup=b.as_markup())


@router.callback_query(F.data == "xfd")
async def cb_xfer_apply(cb: CallbackQuery, state: FSMContext, db: SheetsDB, user: User):
    data = await state.get_data()
    eid, changes = data.get("eid"), data.get("changes", {})
    if not eid or not changes:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    try:
        e = await find_emp(db, eid)
        if not e:
            await cb.message.answer(EMPLOYEE_NOT_FOUND)
            return
        old_vals = {"pos": e.pos, "dept": e.dept, "supervisor": e.supervisor}
        for field, new_val in changes.items():
            setattr(e, FIELD_ATTR[field], new_val)
        await db.update_employee(e)
        when = data.get("change_date") or fmt_date(date.today())
        for field, new_val in changes.items():
            title = dict(FIELDS)[field]
            await db.add_history(e.eid, e.fio, when, "перевод",
                                 old_vals[field], new_val, title, user.name)
    except SheetsUnavailable:
        log.exception("Sheets unavailable on transfer")
        await cb.message.answer(SAVE_FAILED)
        return
    await state.clear()
    await cb.answer("Перевод оформлен ✅")
    saved = await find_emp(db, eid)
    await cb.message.answer("✅ Перевод оформлен, история обновлена.")
    if saved:
        await cb.message.answer(card_text(saved, date.today()),
                                reply_markup=kb.card_keyboard(eid, user.is_full_access))


FIELD_ATTR = {"pos": "pos", "dept": "dept", "supervisor": "supervisor"}
