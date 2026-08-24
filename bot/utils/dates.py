"""Date helpers and Russian pluralization."""

import calendar
from datetime import date, timedelta

MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def parse_date(value: str) -> date | None:
    """Parse DD.MM.YYYY or YYYY-MM-DD."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return _strptime(value, fmt)
        except ValueError:
            continue
    return None


def _strptime(value: str, fmt: str) -> date:
    from datetime import datetime
    return datetime.strptime(value, fmt).date()


def fmt_date(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def fmt_short(d: date | None) -> str:
    return d.strftime("%d.%m") if d else ""


def fmt_long_ru(d: date) -> str:
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Russian plural form."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def diff_ymd(start: date, end: date) -> tuple[int, int, int]:
    """Calendar difference in years/months/days."""
    if end < start:
        return 0, 0, 0
    y = end.year - start.year
    m = end.month - start.month
    d = end.day - start.day
    if d < 0:
        m -= 1
        prev_month_end = date(end.year, end.month, 1) - timedelta(days=1)
        d += prev_month_end.day
    if m < 0:
        y -= 1
        m += 12
    return max(y, 0), max(m, 0), max(d, 0)


def tenure_str(start: date, ref: date) -> str:
    """Human-readable tenure."""
    y, m, d = diff_ymd(start, ref)
    parts = []
    if y:
        parts.append(f"{y} {plural(y, 'год', 'года', 'лет')}")
    if m:
        parts.append(f"{m} {plural(m, 'месяц', 'месяца', 'месяцев')}")
    if d or not parts:
        parts.append(f"{d} {plural(d, 'день', 'дня', 'дней')}")
    return " ".join(parts)


def years_word(n: int) -> str:
    return f"{n} {plural(n, 'год', 'года', 'лет')}"


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, days_in_month(year, month))
    return date(year, month, day)


def add_years(d: date, years: int) -> date:
    year = d.year + years
    try:
        return d.replace(year=year)
    except ValueError:  # Feb 29 -> Mar 1
        return date(year, 3, 1)


def birthday_occurrence(bday: date, today: date) -> date:
    """Nearest birthday: this year or next."""
    try:
        occ = bday.replace(year=today.year)
    except ValueError:
        occ = date(today.year, 3, 1)
    if occ < today:
        try:
            occ = bday.replace(year=today.year + 1)
        except ValueError:
            occ = date(today.year + 1, 3, 1)
    return occ



COMMON_TIMEZONES = [
    ("Europe/Moscow", "МСК — Москва (UTC+3)"),
    ("Europe/Kaliningrad", "Калининград (UTC+2)"),
    ("Europe/Samara", "Самара (UTC+4)"),
    ("Asia/Yekaterinburg", "Екатеринбург (UTC+5)"),
    ("Asia/Almaty", "Алматы (UTC+5)"),
    ("Asia/Tashkent", "Ташкент (UTC+5)"),
    ("Asia/Novosibirsk", "Новосибирск (UTC+7)"),
    ("Asia/Vladivostok", "Владивосток (UTC+10)"),
]

_TZ_ALIASES = {
    "мск": "Europe/Moscow",
    "msk": "Europe/Moscow",
    "москва": "Europe/Moscow",
    "moscow": "Europe/Moscow",
}


def normalize_timezone(raw: str) -> str | None:
    """Canonical tz name from IANA name, alias or UTC+N offset."""
    import re
    from zoneinfo import ZoneInfo

    value = (raw or "").strip()
    if not value:
        return None
    low = value.lower().replace("ё", "е")
    if low in _TZ_ALIASES:
        return _TZ_ALIASES[low]
    m = re.fullmatch(r"(?:utc)?\s*([+-])?\s*(\d{1,2})(?::00)?", low)
    if m:
        sign, hours = m.group(1) or "+", int(m.group(2))
        if 0 <= hours <= 14:
            # Etc/GMT sign inverted: UTC+3 == Etc/GMT-3
            return f"Etc/GMT{'+' if sign == '-' else '-'}{hours}"
    try:
        ZoneInfo(value)
        return value
    except Exception:  # noqa: BLE001
        return None
