"""Dismissal flow; employee stays in DB."""

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import bot.keyboards as kb
from bot.handlers.employees import find_emp
from bot.models import STATUS_FIRED, User
from bot.services.sheets import SheetsDB, SheetsUnavailable
from bot.texts import EMPLOYEE_NOT_FOUND, SAVE_FAILED
from bot.utils.dates import fmt_date, parse_date

log = logging.getLogger(__name__)
router = Router()


class Fire(StatesGroup):
    reason = State()
    reason_custom = State()
    fire_date = State()
    comment = State()
    confirm = State()


@router.callback_query(F.data == "firemenu")
async def cb_fire_menu(cb: CallbackQuery, state: FSMContext, user: User):
    if not user.is_full_access:
        await cb.answer("⛔ Недостаточно прав", show_alert=True)
        return
    from bot.handlers.search import Search
    await cb.answer()
    await state.set_state(Search.waiting_query)
    await state.update_data(mode="fire")
    await cb.message.answer(
        "👋 Увольнение.\nВведите ФИО, телефон или отдел для поиска работающего сотрудника:",
        reply_markup=kb.simple_cancel_keyboard("menu"))


@router.callback_query(F.data.startswith("fire:"))
async def cb_fire_start(cb: CallbackQuery, state: FSMContext, db: SheetsDB, user: User):
    if not user.is_full_access:
        await cb.answer("⛔ Недостаточно прав", show_alert=True)
        return
    eid = cb.data.split(":", 1)[1]
    e = await find_emp(db, eid)
    await cb.answer()
    if not e:
        await cb.message.answer(EMPLOYEE_NOT_FOUND)
        return
    if not e.is_active:
        await cb.message.answer(f"⚠ {e.fio} уже уволен ({e.fire_date or 'дата неизвестна'}).")
        return
    await state.clear()
    await state.update_data(eid=eid)
    dicts = await db.dicts()
    reasons = dicts.reasons or []
    b = InlineKeyboardBuilder()
    for i, r in enumerate(reasons):
        b.button(text=r[:40], callback_data=f"fri:{i}")
    b.row()
    b.button(text="✍️ Другая причина", callback_data="frcustom")
    b.button(text="❌ Отмена", callback_data="fcan")
    b.adjust(1)
    if reasons:
        await state.set_state(Fire.reason)
        await cb.message.answer(
            f"👋 Увольнение: {e.fio}\nВыберите причину:",
            reply_markup=b.as_markup())
    else:
        await state.set_state(Fire.reason_custom)
        await cb.message.answer(
            f"👋 Увольнение: {e.fio}\nВведите причину (справочник причин пуст):",
            reply_markup=kb.simple_cancel_keyboard("fcan"))


@router.callback_query(StateFilter(Fire.reason), F.data.startswith("fri:"))
async def cb_fire_reason(cb: CallbackQuery, state: FSMContext, db: SheetsDB):
    idx = int(cb.data.split(":")[1])
    dicts = await db.dicts()
    reason = dicts.reasons[idx]
    await state.update_data(reason=reason)
    await cb.answer()
    await _ask_date(cb.message, state)


@router.callback_query(StateFilter(Fire.reason), F.data == "frcustom")
async def cb_fire_reason_custom(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(Fire.reason_custom)
    await cb.message.answer("Введите причину текстом:",
                            reply_markup=kb.simple_cancel_keyboard("fcan"))


@router.message(StateFilter(Fire.reason_custom), F.text)
async def msg_fire_reason(message: Message, state: FSMContext):
    await state.update_data(reason=message.text.strip())
    await _ask_date(message, state)


async def _ask_date(message: Message, state: FSMContext):
    await state.set_state(Fire.fire_date)
    await message.answer("📅 Дата увольнения (ДД.ММ.ГГГГ):",
                         reply_markup=kb.today_or_input_keyboard("frdtoday", "fcan"))


@router.callback_query(StateFilter(Fire.fire_date), F.data == "frdtoday")
async def cb_fire_today(cb: CallbackQuery, state: FSMContext):
    await state.update_data(fire_date=fmt_date(date.today()))
    await cb.answer()
    await _ask_comment(cb.message, state)


@router.message(StateFilter(Fire.fire_date), F.text)
async def msg_fire_date(message: Message, state: FSMContext):
    d = parse_date(message.text.strip())
    if not d:
        await message.answer("Не понял дату. Введите ДД.ММ.ГГГГ:")
        return
    await state.update_data(fire_date=fmt_date(d))
    await _ask_comment(message, state)


async def _ask_comment(message: Message, state: FSMContext):
    await state.set_state(Fire.comment)
    await message.answer("💬 Комментарий к увольнению:",
                         reply_markup=kb.simple_cancel_keyboard("fcskip", "⏭ Пропустить"))


@router.callback_query(StateFilter(Fire.comment), F.data == "fcskip")
async def cb_fire_skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="")
    await cb.answer()
    await _confirm(cb.message, state)


@router.message(StateFilter(Fire.comment), F.text)
async def msg_fire_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text.strip())
    await _confirm(message, state)


async def _confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(Fire.confirm)
    lines = [
        "Проверьте данные увольнения:",
        "",
        f"Сотрудник ID: <code>{data['eid']}</code>",
        f"Дата увольнения: {data['fire_date']}",
        f"Причина: {data['reason']}",
        f"Комментарий: {data.get('comment') or '—'}",
    ]
    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить", callback_data="fgo")
    b.button(text="❌ Отмена", callback_data="fcan")
    b.adjust(1)
    await message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(StateFilter("*"), F.data == "fcan")
async def cb_fire_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Отменено")
    await cb.message.answer("❌ Увольнение отменено.")


@router.callback_query(F.data == "fgo")
async def cb_fire_apply(cb: CallbackQuery, state: FSMContext, db: SheetsDB, user: User):
    data = await state.get_data()
    eid = data.get("eid")
    if not eid or not data.get("fire_date"):
        await cb.answer("Сессия истекла", show_alert=True)
        return
    try:
        e = await find_emp(db, eid)
        if not e:
            await cb.message.answer(EMPLOYEE_NOT_FOUND)
            return
        e.status = STATUS_FIRED
        e.fire_date = data["fire_date"]
        await db.update_employee(e)

        await db.add_dismissal([
            e.eid, e.fio, e.pos, e.dept, e.branch, e.hire_date,
            data["fire_date"], data["reason"], data.get("comment", ""), user.name,
        ])
        await db.add_history(e.eid, e.fio, data["fire_date"], "увольнение",
                             "Работает", f"Уволен ({data['reason']})",
                             data.get("comment", ""), user.name)
    except SheetsUnavailable:
        log.exception("Sheets unavailable on dismissal")
        await cb.message.answer(SAVE_FAILED)
        return
    await state.clear()
    await cb.answer("Оформлено ✅")
    saved = await find_emp(db, eid)
    await cb.message.answer(
        f"✅ Сотрудник уволен. Он остался в базе со статусом «{STATUS_FIRED}»\n"
        "и больше не будет участвовать в уведомлениях о ДР и годовщинах.")
    if saved:
        await cb.message.answer(saved_fired_text(saved),
                                reply_markup=kb.card_keyboard(eid, user.is_full_access))


def saved_fired_text(e) -> str:
    return (
        f"👤 <b>{e.fio}</b>  (<code>{e.eid}</code>)\n"
        f"📌 Статус: {e.status}\n"
        f"📅 Дата приема: {e.hire_date or '—'}\n"
        f"👋 Дата увольнения: {e.fire_date or '—'}"
    )
