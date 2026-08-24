"""Репозиторий Google Sheets: единственное место, которое ходит в таблицу.

gspread синхронный, поэтому все публичные методы асинхронные и выполняют
блокирующие вызовы через asyncio.to_thread. Доступ сериализуется локом,
чтобы не ловить гонки при одновременных нажатиях кнопок.
"""

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime

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

CACHE_TTL = 20.0  # секунд жизни кэша списка сотрудников


class SheetsUnavailable(Exception):
    """Google Sheets недоступен (сеть, права и т.п.)."""


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
        self._sh: gspread.Spreadsheet | None = None
        self._ws: dict[str, gspread.Worksheet] = {}
        self._emp_cache: tuple[float, list[Employee]] | None = None

    # ------------------------------------------------------------------
    # Подключение и инициализация структуры
    # ------------------------------------------------------------------

    def _retry_sync(self, fn, attempts: int = 7):
        """Повторы при квотах/сбоях Google API (429/5xx) с экспоненциальной паузой."""
        delay = 1.5
        for i in range(attempts):
            try:
                return fn()
            except APIError as e:
                code = getattr(e, "code", None)
                if code in RETRYABLE_CODES and i < attempts - 1:
                    log.warning("Sheets API %s, повтор #%d через %.1fs", code, i + 1, delay)
                    time.sleep(delay)
                    delay = min(delay * 2, 45)
                else:
                    raise

    def _connect_sync(self):
        try:
            self._gc = gspread.service_account(filename=self._cfg.credentials_file)
            self._sh = self._gc.open_by_key(self._cfg.spreadsheet_id)
        except Exception as e:  # noqa: BLE001
            raise SheetsUnavailable(f"Не удалось подключиться к Google Sheets: {e}") from e

    async def ensure_structure(self) -> None:
        await asyncio.to_thread(self._ensure_structure_sync)

    def _ensure_structure_sync(self):
        with self._lock:
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
                    self._retry_sync(lambda: ws.update(values=[headers], range_name="A1"))
                elif [c.strip() for c in values[0][: len(headers)]] != headers:
                    log.warning("Лист «%s»: заголовки отличаются от ожидаемых", title)
            self._seed_defaults_sync()

    def _seed_defaults_sync(self):
        # Причины увольнения по умолчанию
        d_ws = self._ws[SH_DICTS]
        col_values = self._retry_sync(d_ws.get_all_values)
        col_values = [r[4].strip() if len(r) > 4 else "" for r in col_values]
        if not any(col_values[1:]):
            rows = [[reason] for reason in DEFAULT_REASONS]
            self._retry_sync(lambda: d_ws.update(values=rows, range_name=f"E2:E{1 + len(rows)}"))
        # Настройка времени дайджеста по умолчанию
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

    # ------------------------------------------------------------------
    # Сотрудники
    # ------------------------------------------------------------------

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

    def _append_employee_sync(self, emp: Employee):
        self._retry_sync(lambda: self._ws_of(SH_EMPLOYEES).append_row(
            emp.to_row(), value_input_option="RAW"))
        self._invalidate_cache()

    async def update_employee(self, emp: Employee) -> None:
        if not emp.row:
            raise ValueError("Номер строки сотрудника неизвестен")
        await asyncio.to_thread(self._update_employee_sync, emp)

    def _update_employee_sync(self, emp: Employee):
        last = _col_letter(len(EMPLOYEE_COLUMNS))

        def _do():
            with self._lock:
                self._ws_of(SH_EMPLOYEES).update(
                    values=[emp.to_row()], range_name=f"A{emp.row}:{last}{emp.row}"
                )
        self._retry_sync(_do)
        self._invalidate_cache()

    async def find_employee_by_id(self, eid: str) -> Employee | None:
        eid = eid.strip().upper()
        for e in await self.get_employees():
            if e.eid.upper() == eid:
                return e
        return None

    async def next_emp_id(self) -> str:
        emps = await self.get_employees()
        max_num = 0
        for e in emps:
            m = EMP_ID_RE.match(e.eid.strip())
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"EMP-{max_num + 1:04d}"

    # ------------------------------------------------------------------
    # История изменений
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Увольнения
    # ------------------------------------------------------------------

    async def add_dismissal(self, row_vals: list[str]) -> None:
        await asyncio.to_thread(self._append_row_sync, SH_DISMISSALS, row_vals)

    async def get_dismissals(self) -> list[list[str]]:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_DISMISSALS)
        return rows[1:]

    # ------------------------------------------------------------------
    # События (журнал отправленных уведомлений = защита от дублей)
    # ------------------------------------------------------------------

    async def log_event(self, key: str, kind: str, eid: str, fio: str, desc: str, recipients: str,
                       sent_day: str, sent_time: str) -> None:
        row = [sent_day, kind, key, eid, fio, desc, recipients, sent_time]
        await asyncio.to_thread(self._append_row_sync, SH_EVENTS, row)

    async def sent_event_keys(self) -> set[str]:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_EVENTS)
        return {r[2].strip() for r in rows[1:] if len(r) > 2 and r[2].strip()}

    # ------------------------------------------------------------------
    # Справочники
    # ------------------------------------------------------------------

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
        """Дописывает список значений в колонку справочника одной пачкой."""
        if not values:
            return
        await asyncio.to_thread(self._dict_append_many_sync, dict_index, values)

    def _dict_append_many_sync(self, dict_index: int, values: list[str]):
        existing = len(self._retry_sync(lambda: self._ws_of(SH_DICTS).get_all_values()))
        start = max(existing, 1) + 1
        col = _col_letter(dict_index + 1)
        payload = [[v] for v in values]

        def _do():
            with self._lock:
                self._ws_of(SH_DICTS).update(
                    values=payload,
                    range_name=f"{col}{start}:{col}{start + len(values) - 1}")
        self._retry_sync(_do)

    def _dict_append_sync(self, dict_index: int, value: str):
        def _do():
            with self._lock:
                self._ws_of(SH_DICTS).append_row(
                    [""] * dict_index + [value], value_input_option="RAW")
        self._retry_sync(_do)

    # ------------------------------------------------------------------
    # Пользователи (авторизация и роли)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Настройки (key-value)
    # ------------------------------------------------------------------

    async def setting_get(self, key: str, default: str = "") -> str:
        rows = await asyncio.to_thread(self._get_rows_sync, SH_SETTINGS)
        for r in rows[1:]:
            if r and r[0].strip() == key:
                return r[1].strip() if len(r) > 1 else ""
        return default

    async def setting_set(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._setting_set_sync, key, value)

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

    # ------------------------------------------------------------------
    # Общие низкоуровневые операции
    # ------------------------------------------------------------------

    def _append_row_sync(self, title: str, row: list[str]):
        self._retry_sync(lambda: self._ws_of(title).append_row(row, value_input_option="RAW"))

    def _append_rows_sync(self, title: str, rows: list[list[str]]):
        self._retry_sync(
            lambda: self._ws_of(title).append_rows(rows, value_input_option="RAW"))

    def _get_rows_sync(self, title: str) -> list[list[str]]:
        return self._retry_sync(lambda: self._ws_of(title).get_all_values())

    async def clear_sheet_data(self, title: str) -> None:
        """Удаляет все строки кроме заголовка."""
        await asyncio.to_thread(self._clear_sheet_data_sync, title)

    def _clear_sheet_data_sync(self, title: str):
        ws = self._ws_of(title)

        def _do():
            ws.clear()
            ws.update(values=[ALL_SHEETS[title]], range_name="A1")
        self._retry_sync(_do)
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # Резервная копия всех листов в JSON
    # ------------------------------------------------------------------

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
