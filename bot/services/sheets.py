"""Google Sheets repository: the only IO layer.

v1.1: request throttling (anti rate-limit), race-free employee-ID allocation,
short-lived settings cache, events pruning; locks are never held while
sleeping between API retries.
"""

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta

import gspread
from gspread.exceptions import APIError

from bot.config import Config
from bot.models import (
    DEFAULT_REASONS,
    DISMISSAL_COLUMNS,
    DICT_COLUMNS,
    EMPLOYEE_COLUMNS,
    EVENT_COLUMNS,
    HISTORY_COLUMNS,
    SETTINGS_COLUMNS,
    USER_COLUMNS,
    Dicts,
    Employee,
    User,
)

log = logging.getLogger(__name__)

SH_EMPLOYEES = "Сотрудники"
SH_HISTORY = "История"
SH_DISMISSALS = "Увольнения"
SH_EVENTS = "События"
SH_DICTS = "Справочники"
SH_USERS = "Пользователи"
SH_SETTINGS = "Настройки"

ALL_SHEETS = {
    SH_EMPLOYEES: EMPLOYEE_COLUMNS,
    SH_HISTORY: HISTORY_COLUMNS,
    SH_DISMISSALS: DISMISSAL_COLUMNS,
    SH_EVENTS: EVENT_COLUMNS,
    SH_DICTS: DICT_COLUMNS,
    SH_USERS: USER_COLUMNS,
    SH_SETTINGS: SETTINGS_COLUMNS,
}

EMP_ID_RE = re.compile(r"^EMP-(\d+)\b", re.IGNORECASE)

CACHE_TTL = 20.0       # employees cache TTL, seconds
SETTINGS_TTL = 90.0    # settings cache TTL, seconds (cuts periodic sheet reads)
MIN_API_INTERVAL = 0.25  # min seconds between Google API calls (anti spam-block)
EVENTS_KEEP_DAYS = 120   # events older than this are pruned


class SheetsUnavailable(Exception):
    """Google Sheets unavailable (network, permissions, etc.)."""


RETRYABLE_CODES = {429, 500, 502, 503}


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class SheetsDB:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._sh: gspread.Spreadsheet | None = None
        self._ws: dict[str, gspread.Worksheet] = {}
        self._emp_cache: tuple[float, list[Employee]] | None = None
        self._settings_cache: tuple[float, dict[str, str]] | None = None
        self._last_api_call = 0.0

    def _throttle(self) -> None:
        """Keep a short gap between Google API calls to avoid quota bans."""
        with self._rate_lock:
            wait = self._last_api_call + MIN_API_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_api_call = time.monotonic()

    def _retry_sync(self, fn, attempts: int = 7):
        """Retry Google API quota/5xx errors with exponential backoff."""
        delay = 1.5
        for i in range(attempts):
            self._throttle()
            try:
                return fn()
            except APIError as e:
                code = getattr(e, "code", None)
                if code in RETRYABLE_CODES and i < attempts - 1:
                    log.warning("Sheets API %s, retry #%d in %.1fs", code, i + 1, delay)
                    time.sleep(delay)
                    delay = min(delay * 2, 45)
                else:
                    raise

    @staticmethod
    def _backoff_sleep(attempt: int) -> float:
        """Sleep used by lock-scoped retry loops; called WITHOUT holding locks."""
        return min(1.5 * (2 ** attempt), 45)

    def _connect_sync(self):
        try:
            self._gc = gspread.service_account(filename=self._cfg.credentials_file)
            self._sh = self._gc.open_by_key(self._cfg.spreadsheet_id)
        except Exception as e:  # noqa: BLE001
            raise SheetsUnavailable(f"Не удалось подключиться к Google Sheets: {e}") from e

    async def ensure_structure(self) -> None:
        await asyncio.to_thread(self._ensure_structure_sync)

    def _ensure_structure_sync(self):
        # NOTE: no global lock here — network calls must never run under it.
        if self._sh is None:
            self._connect_sync()
        existing = {ws.title: ws for ws in self._sh.worksheets()}
        for title, headers in ALL_SHEETS.items():
            ws = existing.get(title)
            if ws is None:
                log.info("Создаю лист «%s»", title)
                ws = self._sh.add_worksheet(title=title, rows=2000, cols=len(headers) + 4)
            self._ws[title] = ws
            values = self._retry_sync(ws.get_all_values)
            if not values or not any(cell.strip() for cell in values[0]):
                self._retry_sync(lambda ws=ws, headers=headers: ws.update(
                    values=[headers], range_name="A1"))
            elif [c.strip() for c in values[0][: len(headers)]] != headers:
                log.warning("Лист «%s»: заголовки отличаются от ожидаемых", title)
        self._seed_defaults_sync()

    def _seed_defaults_sync(self):
        d_ws = self._ws[SH_DICTS]
        col_values = self._retry_sync(d_ws.get_all_values)
        col_values = [r[4].strip() if len(r) > 4 else "" for r in col_values]
        if not any(col_values[1:]):
            rows = [[reason] for reason in DEFAULT_REASONS]
            self._retry_sync(lambda: d_ws.update(values=rows, range_name=f"E2:E{1 + len(rows)}"))
        s_ws = self._ws[SH_SETTINGS]
        values = self._retry_sync(s_ws.get_all_values)
        keys = {r[0].strip() for r in values}
        if "digest_time" not in keys:
            self._retry_sync(
                lambda: s_ws.append_row(["digest_time", self._cfg.default_digest_time],
                                        value_input_option="RAW"))

    def _ws_of(self, title: str) -> gspread.Worksheet:
        ws = self._ws.get(title)
        if ws is None:
            raise SheetsUnavailable(f"Лист «{title}» не инициализирован")
        return ws


    async def get_employees(self, fresh: bool = False) -> list[Employee]:
        if not fresh and self._emp_cache and time.monotonic() - self._emp_cache[0] < CACHE_TTL:
            return self._emp_cache[1]
        emps = await asyncio.to_thread(self._get_employees_sync)
        self._emp_cache = (time.monotonic(), emps)
        return emps

    def _get_employees_sync(self) -> list[Employee]:
        values = self._retry_sync(lambda: self._ws_of(SH_EMPLOYEES).get_all_values())
        return [
            Employee.from_row(r, i)
            for i, r in enumerate(values, start=1)
            if i > 1 and (r and r[0].strip())
        ]

    def _invalidate_cache(self):
        self._emp_cache = None

    async def append_employee(self, emp: Employee) -> None:
        await asyncio.to_thread(self._append_employee_sync, emp)

    @staticmethod
    def _pick_emp_id(values: list[list[str]], preferred: str) -> str:
        """Race-free ID choice: honor preferred if free, else first free number."""
        taken: set[str] = set()
        max_num = 0
        for r in values:
            eid = r[0].strip() if r else ""
            m = EMP_ID_RE.match(eid)
            if m:
                taken.add(eid.upper())
                max_num = max(max_num, int(m.group(1)))
        pref = (preferred or "").strip().upper()
        if pref and EMP_ID_RE.match(pref) and pref not in taken:
            return pref
        n = max_num + 1
        while f"EMP-{n:04d}" in taken:
            n += 1
        return f"EMP-{n:04d}"

    def _append_employee_sync(self, emp: Employee):
        """Append with unique-ID guarantee.

        The read-allocate-append sequence is serialized by ``self._lock`` so two
        concurrent saves can never get the same ID. On retryable API errors the
        lock is released BEFORE sleeping, so parallel writes are never blocked
        by backoff waits.
        """
        last_exc: APIError | None = None
        for attempt in range(7):
            try:
                with self._lock:
                    ws = self._ws_of(SH_EMPLOYEES)
                    self._throttle()
                    values = ws.get_all_values()
                    emp.eid = self._pick_emp_id(values, emp.eid)
                    self._throttle()
                    ws.append_row(emp.to_row(), value_input_option="RAW")
                self._invalidate_cache()
                return
            except APIError as e:
                if getattr(e, "code", None) in RETRYABLE_CODES:
                    last_exc = e
                    log.warning("append_employee: Sheets API %s, retry #%d in %.1fs",
                                getattr(e, "code", None), attempt + 1,
                                self._backoff_sleep(attempt))
                    time.sleep(self._backoff_sleep(attempt))  # lock released here
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    async def update_employee(self, emp: Employee) -> None:
        if not emp.row:
            raise ValueError("Номер строки сотрудника неизвестен")
        await asyncio.to_thread(self._update_employee_sync, emp)

    def _update_employee_sync(self, emp: Employee):
        last = _col_letter(len(EMPLOYEE_COLUMNS))
        range_name = f"A{emp.row}:{last}{emp.row}"
        last_exc: APIError | None = None
        for attempt in range(7):
            try:
                with self._lock:
                    self._throttle()
                    self._ws_of(SH_EMPLOYEES).update(values=[emp.to_row()],
                                                     range_name=range_name)
                self._invalidate_cache()
                return
            except APIError as e:
                if getattr(e, "code", None) in RETRYABLE_CODES:
                    last_exc = e
                    time.sleep(self._backoff_sleep(attempt))  # lock released here
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    async def find_employee_by_id(self, eid: str) -> Employee | None:
        eid = eid.strip().upper()
        for e in await self.get_employees():
            if e.eid.upper() == eid:
                return e
        return None

    async def next_emp_id(self) -> str:
        emps = await self.get_employees(fresh=True)
        max_num = 0
        for e in emps:
            m = EMP_ID_RE.match(e.eid.strip())
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"EMP-{max_num + 1:04d}"


    async def add_history(self, eid, fio, change_date, change_type, old_val, new_val, comment, who) -> None:
        row = [eid, fio, change_date, change_type, old_val, new_val, comment, who]
        await asyncio.to_thread(self._append_row_sync, SH_HISTORY, row)

    async def add_history_bulk(self, rows: list[list[str]]) -> None:
        if rows:
            await asyncio.to_thread(self._append_rows_sync, SH_HISTORY, rows)

    async def get_history(self, eid: str) -> list[list[str]]:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_HISTORY)
        return [r for r in rows[1:] if r and r[0].strip().upper() == eid.upper()]

    async def get_history_all(self) -> list[list[str]]:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_HISTORY)
        return rows[1:]


    async def add_dismissal(self, row_vals: list[str]) -> None:
        await asyncio.to_thread(self._append_row_sync, SH_DISMISSALS, row_vals)

    async def get_dismissals(self) -> list[list[str]]:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_DISMISSALS)
        return rows[1:]


    async def log_event(self, key: str, kind: str, eid: str, fio: str, desc: str, recipients: str,
                       sent_day: str, sent_time: str) -> None:
        row = [sent_day, kind, key, eid, fio, desc, recipients, sent_time]
        await asyncio.to_thread(self._append_row_sync, SH_EVENTS, row)

    async def sent_event_keys(self) -> set[str]:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_EVENTS)
        return {r[2].strip() for r in rows[1:] if len(r) > 2 and r[2].strip()}

    async def prune_events(self, keep_days: int = EVENTS_KEEP_DAYS) -> int:
        """Delete event-log rows older than keep_days; returns removed count."""
        return await asyncio.to_thread(self._prune_events_sync, keep_days)

    def _prune_events_sync(self, keep_days: int) -> int:
        ws = self._ws_of(SH_EVENTS)
        values = self._retry_sync(ws.get_all_values)
        cutoff = datetime.now() - timedelta(days=keep_days)
        doomed: list[int] = []
        for i, r in enumerate(values, start=1):
            if i == 1 or not r or not r[0].strip():
                continue
            try:
                sent_day = datetime.strptime(r[0].strip(), "%d.%m.%Y")
            except ValueError:
                continue  # unparsable date: leave the row alone
            if sent_day < cutoff:
                doomed.append(i)
        for idx in sorted(doomed, reverse=True):
            self._retry_sync(lambda idx=idx: ws.delete_rows(idx))
        if doomed:
            log.info("События: удалено устаревших записей: %d", len(doomed))
        return len(doomed)


    async def dicts(self) -> Dicts:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_DICTS)

        def col(i: int) -> list[str]:
            seen = []
            for r in rows[1:]:
                v = r[i].strip() if i < len(r) else ""
                if v and v not in seen:
                    seen.append(v)
            return seen

        return Dicts(departments=col(0), positions=col(1), branches=col(2),
                     supervisors=col(3), reasons=col(4))

    async def dict_append(self, dict_index: int, value: str) -> None:
        await asyncio.to_thread(self._dict_append_sync, dict_index, value)

    async def dict_append_many(self, dict_index: int, values: list[str]) -> None:
        """Append a batch of values into a dictionary column."""
        if not values:
            return
        await asyncio.to_thread(self._dict_append_many_sync, dict_index, values)

    def _dict_append_many_sync(self, dict_index: int, values: list[str]):
        existing = len(self._retry_sync(lambda: self._ws_of(SH_DICTS).get_all_values()))
        start = max(existing, 1) + 1
        col = _col_letter(dict_index + 1)
        payload = [[v] for v in values]
        range_name = f"{col}{start}:{col}{start + len(values) - 1}"
        last_exc: APIError | None = None
        for attempt in range(7):
            try:
                with self._lock:
                    self._throttle()
                    self._ws_of(SH_DICTS).update(values=payload, range_name=range_name)
                return
            except APIError as e:
                if getattr(e, "code", None) in RETRYABLE_CODES:
                    last_exc = e
                    time.sleep(self._backoff_sleep(attempt))  # lock released here
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    def _dict_append_sync(self, dict_index: int, value: str):
        self._retry_sync(lambda: self._ws_of(SH_DICTS).append_row(
            [""] * dict_index + [value], value_input_option="RAW"))


    async def users_all(self) -> list[User]:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_USERS)
        out = []
        for r in rows[1:]:
            if not r or not r[0].strip():
                continue
            out.append(User(
                uid=int(float(r[0].strip())),
                name=r[1].strip() if len(r) > 1 else "",
                role=(r[2].strip() if len(r) > 2 else "") or "manager",
                notifications=(r[3].strip() if len(r) > 3 else "1") != "0",
            ))
        return out

    async def user_find(self, uid: int) -> User | None:
        for u in await self.users_all():
            if u.uid == uid:
                return u
        return None

    async def user_upsert(self, uid: int, name: str, role: str, notifications: bool = True,
                          added_by: str = "") -> None:
        await asyncio.to_thread(self._user_upsert_sync, uid, name, role, notifications, added_by)

    def _user_upsert_sync(self, uid, name, role, notifications, added_by):
        ws = self._ws_of(SH_USERS)

        def _find_row() -> int | None:
            values = self._retry_sync(ws.get_all_values)
            uid_s = str(uid)
            for i, r in enumerate(values, start=1):
                if i > 1 and r and r[0].strip() == uid_s:
                    return i
            return None

        row_num = self._retry_sync(_find_row)
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        if row_num:
            for col, val in ((2, name), (3, role), (4, "1" if notifications else "0")):
                self._retry_sync(lambda c=col, v=val: ws.update_cell(row_num, c, v))
        else:
            self._retry_sync(lambda: ws.append_row(
                [str(uid), name, role, "1" if notifications else "0", now, added_by],
                value_input_option="RAW"))

    async def user_delete(self, uid: int) -> bool:
        return await asyncio.to_thread(self._user_delete_sync, uid)

    def _user_delete_sync(self, uid) -> bool:
        ws = self._ws_of(SH_USERS)

        def _find_row() -> int | None:
            values = self._retry_sync(ws.get_all_values)
            uid_s = str(uid)
            for i, r in enumerate(values, start=1):
                if i > 1 and r and r[0].strip() == uid_s:
                    return i
            return None

        row_num = self._retry_sync(_find_row)
        if row_num is None:
            return False
        self._retry_sync(lambda: ws.delete_rows(row_num))
        return True


    async def setting_get(self, key: str, default: str = "") -> str:
        if (self._settings_cache is None
                or time.monotonic() - self._settings_cache[0] > SETTINGS_TTL):
            rows = await asyncio.to_thread(self._get_rows_sync, SH_SETTINGS)
            kv = {}
            for r in rows[1:]:
                if r and r[0].strip():
                    kv[r[0].strip()] = r[1].strip() if len(r) > 1 else ""
            self._settings_cache = (time.monotonic(), kv)
        return self._settings_cache[1].get(key, default)

    async def setting_set(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._setting_set_sync, key, value)
        self._settings_cache = None  # invalidate so readers see the new value

    def _setting_set_sync(self, key, value):
        ws = self._ws_of(SH_SETTINGS)

        def _find_row() -> int | None:
            values = self._retry_sync(ws.get_all_values)
            for i, r in enumerate(values, start=1):
                if i > 1 and r and r[0].strip() == key:
                    return i
            return None

        row_num = self._retry_sync(_find_row)
        if row_num is not None:
            self._retry_sync(lambda: ws.update_cell(row_num, 2, value))
        else:
            self._retry_sync(lambda: ws.append_row([key, value], value_input_option="RAW"))


    def _append_row_sync(self, title: str, row: list[str]):
        self._retry_sync(lambda: self._ws_of(title).append_row(row, value_input_option="RAW"))

    def _append_rows_sync(self, title: str, rows: list[list[str]]):
        self._retry_sync(
            lambda: self._ws_of(title).append_rows(rows, value_input_option="RAW"))

    def _get_rows_sync(self, title: str) -> list[list[str]]:
        return self._retry_sync(lambda: self._ws_of(title).get_all_values())

    async def clear_sheet_data(self, title: str) -> None:
        """Delete all rows except header."""
        await asyncio.to_thread(self._clear_sheet_data_sync, title)

    def _clear_sheet_data_sync(self, title: str):
        ws = self._ws_of(title)

        def _do():
            ws.clear()
            ws.update(values=[ALL_SHEETS[title]], range_name="A1")
        self._retry_sync(_do)
        self._invalidate_cache()


    async def dump_backup(self, path) -> None:
        await asyncio.to_thread(self._dump_backup_sync, path)

    def _dump_backup_sync(self, path):
        data = {}
        for title in ALL_SHEETS:
            try:
                data[title] = self._get_rows_sync(title)
            except Exception:  # noqa: BLE001
                log.exception("Бэкап листа «%s» не удался", title)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
