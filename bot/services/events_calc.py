"""HR event calculations; pure functions, no IO."""

import re
from dataclasses import dataclass
from datetime import date

from bot.models import Employee
from bot.utils.dates import (
    add_years,
    birthday_occurrence,
    diff_ymd,
    fmt_date,
    fmt_short,
    parse_date,
    years_word,
)

# event kinds (logged to Events sheet)
EV_BIRTHDAY_PRE = "birthday_pre"
EV_BIRTHDAY = "birthday"
EV_ANNIV_PRE = "anniversary_pre"
EV_ANNIV = "anniversary"
EV_PROBATION_PRE7 = "probation_pre7"
EV_PROBATION_PRE3 = "probation_pre3"
EV_PROBATION = "probation_end"

WINDOW_LIST_DAYS = 30  # events window, days


@dataclass(frozen=True)
class Notification:
    key: str  # dedup key
    kind: str
    eid: str
    fio: str
    text: str


def _active(emps: list[Employee]) -> list[Employee]:
    return [e for e in emps if e.is_active]


def _line(e: Employee) -> str:
    place = " / ".join(x for x in (e.dept, e.branch) if x)
    return f"{e.fio}" + (f" ({place})" if place else "")



def upcoming_birthdays(emps, today, window=WINDOW_LIST_DAYS):
    out = []
    for e in _active(emps):
        bd = e.bday_date()
        if not bd:
            continue
        occ = birthday_occurrence(bd, today)
        delta = (occ - today).days
        if 0 <= delta <= window:
            out.append((e, occ, delta))
    return sorted(out, key=lambda x: x[2])


def upcoming_anniversaries(emps, today, window=WINDOW_LIST_DAYS):
    out = []
    for e in _active(emps):
        h = e.hire()
        if not h:
            continue
        y, _, _ = diff_ymd(h, today)
        if y < 1:
            continue
        for years in (y, y + 1):
            occ = add_years(h, years)
            delta = (occ - today).days
            if 0 <= delta <= window:
                out.append((e, occ, years, delta))
    return sorted(out, key=lambda x: x[3])


def upcoming_probations(emps, today, window=WINDOW_LIST_DAYS):
    out = []
    for e in _active(emps):
        end = parse_date(e.probation_end)
        if not end:
            continue
        delta = (end - today).days
        if 0 <= delta <= window:
            out.append((e, end, delta))
    return sorted(out, key=lambda x: x[2])


def recent_dismissals(emps, today, days=WINDOW_LIST_DAYS):
    out = []
    for e in emps:
        fd = parse_date(e.fire_date)
        if not fd:
            continue
        delta = (today - fd).days
        if 0 <= delta <= days:
            out.append((e, fd))
    return sorted(out, key=lambda x: x[1], reverse=True)


def recent_hires(emps, today, days=WINDOW_LIST_DAYS):
    out = []
    for e in _active(emps):
        h = e.hire()
        if not h:
            continue
        delta = (today - h).days
        if 0 <= delta <= days:
            out.append((e, h))
    return sorted(out, key=lambda x: x[1], reverse=True)



def birthday_notifications(emps, today) -> list[Notification]:
    result = []
    for e, occ, delta in upcoming_birthdays(emps, today, window=3):
        if delta == 3:
            text = (
                f"🎂 День рождения через 3 дня\n\n"
                f"Сотрудник: {e.fio}\n"
                f"Отдел: {e.dept or '—'}\n"
                f"Филиал: {e.branch or '—'}\n"
                f"Дата: {fmt_short(occ)}"
            )
            result.append(Notification(_key(e.eid, EV_BIRTHDAY_PRE, occ), EV_BIRTHDAY_PRE, e.eid, e.fio, text))
        elif delta == 0:
            text = (
                f"🎉 Сегодня день рождения!\n\n"
                f"{e.fio}\n"
                f"Отдел: {e.dept or '—'}\n"
                f"Филиал: {e.branch or '—'}"
            )
            result.append(Notification(_key(e.eid, EV_BIRTHDAY, occ), EV_BIRTHDAY, e.eid, e.fio, text))
    return result


def anniversary_notifications(emps, today) -> list[Notification]:
    result = []
    for e, occ, years, delta in upcoming_anniversaries(emps, today, window=7):
        if delta == 7:
            text = (
                f"🏆 Через 7 дней годовщина работы\n\n"
                f"{e.fio}\n"
                f"Стаж: {years_word(years)}\n"
                f"Дата годовщины: {fmt_date(occ)}"
            )
            result.append(Notification(_key(e.eid, EV_ANNIV_PRE, occ), EV_ANNIV_PRE, e.eid, e.fio, text))
        elif delta == 0:
            text = (
                f"🏆 Сегодня годовщина работы в компании!\n\n"
                f"{e.fio}\n"
                f"🎉 {years_word(years)} в компании."
            )
            result.append(Notification(_key(e.eid, EV_ANNIV, occ), EV_ANNIV, e.eid, e.fio, text))
    return result


def probation_notifications(emps, today) -> list[Notification]:
    result = []
    for e, end, delta in upcoming_probations(emps, today, window=7):
        base = f"Сотрудник: {e.fio}\nДолжность: {e.pos or '—'}\nДата окончания: {fmt_date(end)}"
        if delta == 7:
            text = f"⚠ Испытательный срок заканчивается через 7 дней.\n\n{base}"
            result.append(Notification(_key(e.eid, EV_PROBATION_PRE7, end), EV_PROBATION_PRE7, e.eid, e.fio, text))
        elif delta == 3:
            text = f"⚠ Испытательный срок заканчивается через 3 дня.\n\n{base}"
            result.append(Notification(_key(e.eid, EV_PROBATION_PRE3, end), EV_PROBATION_PRE3, e.eid, e.fio, text))
        elif delta == 0:
            text = f"⚠ Сегодня заканчивается испытательный срок.\n\n{base}"
            result.append(Notification(_key(e.eid, EV_PROBATION, end), EV_PROBATION, e.eid, e.fio, text))
    return result


def all_due_notifications(emps, today) -> list[Notification]:
    return (
        birthday_notifications(emps, today)
        + anniversary_notifications(emps, today)
        + probation_notifications(emps, today)
    )


def digest_counts(emps, today) -> dict[str, int]:
    """Category counters for the daily digest."""
    bdays = sum(1 for _, _, d in upcoming_birthdays(emps, today, window=3) if d in (0, 3))
    annivs = sum(1 for *_, d in upcoming_anniversaries(emps, today, window=7) if d in (0, 7))
    proba = sum(1 for *_, d in upcoming_probations(emps, today, window=7) if d in (0, 3, 7))
    fired_today = sum(1 for e in emps if parse_date(e.fire_date) == today)
    hired_today = sum(1 for e in _active(emps) if e.hire() == today)
    return {
        "birthdays": bdays,
        "anniversaries": annivs,
        "probation": proba,
        "vacations": 0,  # vacations: future feature
        "dismissals": fired_today,
        "new_hires": hired_today,
    }


def _key(eid: str, kind: str, occurrence: date) -> str:
    return f"{kind}|{eid}|{occurrence.isoformat()}"


EMP_ID_RE = re.compile(r"^EMP-(\d{4,})$")
