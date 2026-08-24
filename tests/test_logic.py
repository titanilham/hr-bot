"""Юнит-тесты чистой логики (без сети и Google Sheets). Запуск: pytest tests/"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.models import STATUS_ACTIVE, Employee
from bot.services import events_calc as ev
from bot.utils.dates import (
    add_months,
    add_years,
    birthday_occurrence,
    diff_ymd,
    fmt_date,
    parse_date,
    plural,
    tenure_str,
)


# ---------------------------------------------------------------- parse/format

def test_parse_date_basic():
    assert parse_date("15.09.2002") == date(2002, 9, 15)
    assert parse_date("01.08.2023") == date(2023, 8, 1)
    assert parse_date("2026-08-21") == date(2026, 8, 21)


def test_parse_date_invalid():
    assert parse_date("") is None
    assert parse_date("32.13.2020") is None
    assert parse_date("abc") is None


def test_fmt_date():
    assert fmt_date(date(2026, 8, 21)) == "21.08.2026"


# ---------------------------------------------------------------- стаж

def test_diff_ymd_tz_example():
    # Пример из ТЗ: 01.08.2023 -> 21.08.2026 = 3 года 20 дней
    y, m, d = diff_ymd(date(2023, 8, 1), date(2026, 8, 21))
    assert (y, m, d) == (3, 0, 20)


def test_tenure_str_examples():
    today = date(2026, 8, 21)
    assert tenure_str(date(2023, 8, 1), today) == "3 года 20 дней"
    assert tenure_str(today, today) == "0 дней"
    assert tenure_str(date(2026, 7, 1), today) == "1 месяц 20 дней"
    assert tenure_str(date(2025, 1, 15), today) in (
        "1 год 7 месяцев 6 дней", "1 год 7 месяцев 5 дней", "1 год 7 месяцев 7 дней")


def test_plural():
    assert plural(1, "год", "года", "лет") == "год"
    assert plural(2, "год", "года", "лет") == "года"
    assert plural(5, "год", "года", "лет") == "лет"
    assert plural(11, "день", "дня", "дней") == "дней"
    assert plural(21, "день", "дня", "дней") == "день"
    assert plural(22, "день", "дня", "дней") == "дня"


def test_add_months_clamp():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 8, 1), 3) == date(2026, 11, 1)
    assert add_months(date(2026, 10, 31), 2) == date(2026, 12, 31)


def test_add_years_leap():
    assert add_years(date(2024, 2, 29), 1) == date(2025, 3, 1)
    assert add_years(date(2024, 2, 29), 4) == date(2028, 2, 29)


def test_birthday_occurrence():
    bd = date(1990, 9, 15)
    assert birthday_occurrence(bd, date(2026, 9, 10)) == date(2026, 9, 15)
    assert birthday_occurrence(bd, date(2026, 9, 15)) == date(2026, 9, 15)
    assert birthday_occurrence(bd, date(2026, 9, 16)) == date(2027, 9, 15)
    leap = date(2000, 2, 29)
    assert birthday_occurrence(leap, date(2026, 2, 20)) == date(2026, 3, 1)


# ---------------------------------------------------------------- события

def _emp(**kw):
    base = dict(eid="EMP-0001", fio="Иванова Алина", dept="Розница", branch="Магазин №7",
                pos="Бариста", hire_date="01.08.2024", status=STATUS_ACTIVE)
    base.update(kw)
    return Employee(**base)


def test_birthday_notifications_offsets():
    today = date(2026, 8, 24)
    e = _emp(birthday="27.08.1995")
    notifs = {n.kind for n in ev.birthday_notifications([e], today)}
    assert notifs == {"birthday_pre"}  # за 3 дня

    today2 = date(2026, 8, 27)
    notifs2 = {n.kind for n in ev.birthday_notifications([e], today2)}
    assert notifs2 == {"birthday"}

    today3 = date(2026, 8, 25)
    assert ev.birthday_notifications([e], today3) == []


def test_fired_employee_no_notifications():
    e = _emp(birthday="27.08.1995", status="Уволен", fire_date="01.08.2026")
    assert ev.birthday_notifications([e], date(2026, 8, 24)) == []
    assert ev.anniversary_notifications([e], date(2026, 8, 21)) == []


def test_anniversary_notifications():
    # Принята 28.08.2024 -> годовщина 28.08.2026 (2 года): pre за 7 дней = 21.08.2026
    e = _emp(hire_date="28.08.2024")
    today = date(2026, 8, 21)
    kinds = {n.kind for n in ev.anniversary_notifications([e], today)}
    assert kinds == {"anniversary_pre"}
    day = date(2026, 8, 28)
    kinds_day = {n.kind for n in ev.anniversary_notifications([e], day)}
    assert kinds_day == {"anniversary"}
    # Первая годовщина (1 год) тоже приходит
    first_year = date(2025, 8, 28)
    kinds_first = {n.kind for n in ev.anniversary_notifications([e], first_year)}
    assert kinds_first == {"anniversary"}
    # А до первой годовщины их нет
    before = date(2025, 8, 20)
    assert ev.anniversary_notifications([e], before) == []


def test_probation_notifications():
    # Испытательный срок до 01.09.2026
    e = _emp(hire_date="01.08.2026", probation_end="01.09.2026")
    kinds = {}
    for offset, expected in ((7, "probation_pre7"), (3, "probation_pre3"), (0, "probation_end")):
        d = date(2026, 9, 1)
        from datetime import timedelta
        target = d - timedelta(days=offset)
        got = {n.kind for n in ev.probation_notifications([e], target)}
        assert got == {expected}, f"offset={offset}"
    # После окончания ИС уведомлений нет
    from datetime import timedelta
    late = date(2026, 9, 1) + timedelta(days=1)
    assert ev.probation_notifications([e], late) == []


def test_keys_unique_per_occurrence():
    e = _emp(birthday="27.08.1995")
    n1 = ev.birthday_notifications([e], date(2026, 8, 24))
    n2 = ev.birthday_notifications([e], date(2027, 8, 24))
    assert n1[0].key != n2[0].key


def test_digest_counts():
    today = date(2026, 8, 24)
    bday_emp = _emp(eid="EMP-0002", birthday="24.08.1990")
    hired_today = _emp(eid="EMP-0003", hire_date="24.08.2026", probation_end="24.09.2026")
    counts = ev.digest_counts([bday_emp, hired_today], today)
    assert counts["birthdays"] >= 1
    assert counts["new_hires"] == 1
