"""HR report with period filter."""

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery

import bot.keyboards as kb
from bot.services.sheets import SheetsDB
from bot.utils.dates import add_years, birthday_occurrence, diff_ymd, parse_date

router = Router()


def _range(kind: str, today: date) -> tuple[date, date]:
    if kind == "t":
        return today, today
    if kind == "w":
        monday = today - timedelta(days=today.weekday())
        return monday, monday + timedelta(days=6)
    if kind == "m":
        start = today.replace(day=1)
        return start, _month_end(start)
    if kind == "pm":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), _month_end(last_prev)
    return today, today


def _month_end(d: date) -> date:
    if d.month == 12:
        return d.replace(day=31)
    return d.replace(month=d.month + 1, day=1) - timedelta(days=1)


def _in_range(d: date | None, r: tuple[date, date]) -> bool:
    return d is not None and r[0] <= d <= r[1]


async def build_report(db: SheetsDB, period_kind: str) -> str:
    today = date.today()
    r = _range(period_kind, today)

    emps = await db.get_employees()
    total = len(emps)
    active = [e for e in emps if e.is_active]
    fired = [e for e in emps if not e.is_active]
    on_proba = [e for e in active if e.on_probation(today)]

    hired = sum(1 for e in emps if _in_range(e.hire(), r))
    fired_cnt = sum(1 for e in emps if _in_range(parse_date(e.fire_date), r))

    hist_rows = await db.get_history_all()
    transfer_ids = set()
    for row in hist_rows:
        if len(row) > 3 and row[3].strip() == "перевод":
            hd = parse_date(row[2])
            if _in_range(hd, r):
                transfer_ids.add(row[0].strip().upper())

    bdays = 0
    for e in active:
        bd = e.bday_date()
        if not bd:
            continue
        occ = birthday_occurrence(bd, today)
        # check current year too
        try:
            this_year = bd.replace(year=r[0].year)
        except ValueError:
            this_year = date(r[0].year, 3, 1)
        for occ_d in {occ, this_year}:
            if _in_range(occ_d, r):
                bdays += 1
                break

    annivs = 0
    for e in active:
        h = e.hire()
        if not h:
            continue
        y, _, _ = diff_ymd(h, today)
        for n in range(y + 4):  # covers previous month too
            occ = add_years(h, n)
            if _in_range(occ, r):
                annivs += 1
                break

    titles = {"t": "Сегодня", "w": "Эта неделя", "m": "Этот месяц", "pm": "Прошлый месяц"}
    lines = [
        "📊 HR-ОТЧЕТ",
        "",
        "Текущая численность:",
        f"👥 Всего сотрудников: {total}",
        f"Работают: {len(active)}",
        f"Уволены: {len(fired)}",
        f"На испытательном сроке: {len(on_proba)}",
        "",
        f"За период «{titles.get(period_kind, period_kind)}»:",
        f"➕ Принято: {hired}",
        f"➖ Уволено: {fired_cnt}",
        f"🔄 Переведено: {len(transfer_ids)}",
        "",
        "Дополнительно:",
        f"🎂 Дней рождения: {bdays}",
        f"🏆 Годовщин: {annivs}",
    ]
    return "\n".join(lines)


@router.callback_query(F.data == "rep")
async def cb_report(cb: CallbackQuery, user):
    await cb.answer()
    await cb.message.answer("📊 Выберите период:", reply_markup=kb.report_periods())


@router.callback_query(F.data.startswith("rep:"))
async def cb_report_period(cb: CallbackQuery, db: SheetsDB, user):
    kind = cb.data.split(":")[1]
    text = await build_report(db, kind)
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.report_periods())
