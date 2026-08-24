"""🔔 Раздел «События»: дни рождения, годовщины, испытательные сроки и др."""

from datetime import date

from aiogram import F, Router
from aiogram.types import CallbackQuery

import bot.keyboards as kb
from bot.services import events_calc
from bot.services.sheets import SheetsDB
from bot.utils.dates import fmt_date

router = Router()


def _fmt_bday_line(occ, e) -> str:
    place = " / ".join(x for x in (e.dept, e.branch) if x)
    return f"{fmt_date(occ)[:6]} — {e.fio}" + (f" ({place})" if place else "")


@router.callback_query(F.data == "evt")
async def cb_events(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("🔔 События — выберите категорию:", reply_markup=kb.events_menu())


@router.callback_query(F.data == "evt:bdy")
async def cb_evt_bday(cb: CallbackQuery, db: SheetsDB):
    emps = await db.get_employees()
    rows = events_calc.upcoming_birthdays(emps, date.today())
    text = "🎂 Дни рождения (30 дней):\n\n"
    text += "\n".join(f"• {_fmt_bday_line(o, e)}" for e, o, d in rows) if rows else "Нет дней рождения в ближайшие 30 дней."
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.events_menu())


@router.callback_query(F.data == "evt:anniv")
async def cb_evt_anniv(cb: CallbackQuery, db: SheetsDB):
    from bot.utils.dates import years_word
    emps = await db.get_employees()
    rows = events_calc.upcoming_anniversaries(emps, date.today())
    if rows:
        text = "🏆 Годовщины работы (30 дней):\n\n" + "\n".join(
            f"• {fmt_date(occ)} — {e.fio} — исполнится {years_word(y)}" for e, occ, y, d in rows)
    else:
        text = "Нет годовщин в ближайшие 30 дней."
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.events_menu())


@router.callback_query(F.data == "evt:proba")
async def cb_evt_proba(cb: CallbackQuery, db: SheetsDB):
    emps = await db.get_employees()
    rows = events_calc.upcoming_probations(emps, date.today())
    if rows:
        text = "⏳ Испытательные сроки (окончание в 30 днях):\n\n" + "\n".join(
            f"• {fmt_date(end)} — {e.fio} ({e.pos or '—'}) — через {d} дн." for e, end, d in rows)
    else:
        text = "Нет сотрудников с заканчивающимся испытательным сроком."
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.events_menu())


@router.callback_query(F.data == "evt:vac")
async def cb_evt_vac(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("🏖 Модуль отпусков будет добавлен в следующей версии.",
                            reply_markup=kb.events_menu())


@router.callback_query(F.data == "evt:dis")
async def cb_evt_dis(cb: CallbackQuery, db: SheetsDB):
    emps = await db.get_employees()
    rows = events_calc.recent_dismissals(emps, date.today())
    if rows:
        dismissals = await db.get_dismissals()
        reason_by_id = {}
        for r in dismissals:
            if r and r[0].strip():
                reason_by_id[r[0].strip().upper()] = r[7].strip() if len(r) > 7 else ""
        text = "👋 Увольнения за последние 30 дней:\n\n" + "\n".join(
            f"• {fmt_date(fd)} — {e.fio}" + (f" ({reason_by_id.get(e.eid.upper(), '')})" if reason_by_id.get(e.eid.upper()) else "")
            for e, fd in rows)
    else:
        text = "Увольнений за последние 30 дней нет."
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.events_menu())


@router.callback_query(F.data == "evt:new")
async def cb_evt_new(cb: CallbackQuery, db: SheetsDB):
    emps = await db.get_employees()
    rows = events_calc.recent_hires(emps, date.today())
    if rows:
        text = "👤 Новые сотрудники (последние 30 дней):\n\n" + "\n".join(
            f"• {fmt_date(hd)} — {e.fio} ({e.pos or '—'})" for e, hd in rows)
    else:
        text = "Новых сотрудников за последние 30 дней нет."
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.events_menu())
