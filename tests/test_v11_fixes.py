"""Regression tests: FSM persistence, ID race, digest catch-up,
events pruning, API throttling, settings cache."""

import asyncio
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram.fsm.storage.base import StorageKey

from bot.config import Config
from bot.models import Employee
from bot.services.fsm_storage import JSONFileStorage
from bot.services.notifications import digest_due
from bot.services.sheets import EVENTS_KEEP_DAYS, MIN_API_INTERVAL, SheetsDB

from tests.fakes import FakeSpreadsheet


def make_db() -> SheetsDB:
    cfg = Config(bot_token="t", spreadsheet_id="fake", credentials_file="none.json",
                 admin_ids=(), timezone="Asia/Almaty", default_digest_time="09:00")
    db = SheetsDB(cfg)
    db._sh = FakeSpreadsheet()
    db._ensure_structure_sync()
    return db


# ---------------------------------------------------------------- FSM storage

KEY = StorageKey(bot_id=42, chat_id=100, user_id=200)


def test_fsm_storage_roundtrip(tmp_path):
    async def scenario():
        path = tmp_path / "fsm.json"
        st = JSONFileStorage(path)
        await st.set_state(KEY, "AddEmp:fio")
        await st.update_data(KEY, {"draft": {"fio": "Тест"}})
        # update_data merges top-level keys only (same as MemoryStorage):
        # wizards read-modify-write the whole draft themselves
        await st.update_data(KEY, {"draft": {"fio": "Тест", "phone": "+7 900"}, "step": 2})

        data = await st.get_data(KEY)
        assert data["draft"] == {"fio": "Тест", "phone": "+7 900"}
        assert data["step"] == 2
        assert await st.get_state(KEY) == "AddEmp:fio"

        # set_data replaces, set_state(None) resets
        await st.set_data(KEY, {"x": "1"})
        assert await st.get_data(KEY) == {"x": "1"}
        await st.set_state(KEY, None)
        assert await st.get_state(KEY) is None

        # unknown key reads as empty
        other = StorageKey(bot_id=42, chat_id=1, user_id=2)
        assert await st.get_state(other) is None
        assert await st.get_data(other) == {}
        await st.close()

    asyncio.run(scenario())


def test_fsm_storage_survives_restart(tmp_path):
    async def scenario():
        path = tmp_path / "fsm.json"
        st1 = JSONFileStorage(path)
        await st1.set_state(KEY, "AddEmp:preview")
        await st1.set_data(KEY, {"draft": {"fio": "Иван Иванов"}})

        # simulate process restart: brand-new instance over the same file
        st2 = JSONFileStorage(path)
        assert await st2.get_state(KEY) == "AddEmp:preview"
        assert (await st2.get_data(KEY))["draft"]["fio"] == "Иван Иванов"
        await st1.close()

    asyncio.run(scenario())


# ------------------------------------------------------------ EMP-ID race fix

def test_pick_emp_id_prefers_free_and_skips_taken():
    values = [["ID"], ["EMP-0001"], ["EMP-0003"]]
    assert SheetsDB._pick_emp_id(values, "") == "EMP-0004"
    # preferred free number wins even if not max+1... only when equal pattern and free
    assert SheetsDB._pick_emp_id(values, "EMP-0009") == "EMP-0009"
    # taken or malformed preferred falls back to next free
    assert SheetsDB._pick_emp_id(values, "EMP-0003") == "EMP-0004"
    assert SheetsDB._pick_emp_id(values, "мусор") == "EMP-0004"


def test_concurrent_appends_get_unique_ids():
    async def scenario():
        db = make_db()
        seed = Employee(eid="EMP-0001", fio="Сид Сидоров")
        await db.append_employee(seed)

        emps = [Employee(eid="EMP-0005", fio=f"Сотрудник Номер {i}") for i in range(8)]
        await asyncio.gather(*(db.append_employee(e) for e in emps))

        fresh = await db.get_employees(fresh=True)
        ids = [e.eid for e in fresh]
        assert len(ids) == len(set(ids)) == 9  # all unique, none lost

    asyncio.run(scenario())


# ------------------------------------------------------------- digest catch-up

def test_digest_due_semantics():
    # exact minute: fires once
    assert digest_due("09:00", "09:00", True, False)
    # before target: waits
    assert not digest_due("08:59", "09:00", True, False)
    # after target: catches up (was skipped on restart/downtime)
    assert digest_due("14:37", "09:00", True, False)
    # already sent today: never repeats
    assert not digest_due("09:00", "09:00", True, True)
    assert not digest_due("23:59", "09:00", True, True)
    # notifications disabled
    assert not digest_due("09:00", "09:00", False, False)


# --------------------------------------------------------------- events prune

def test_prune_events_keeps_recent_only():
    async def scenario():
        db = make_db()
        old_day = (datetime.now() - timedelta(days=EVENTS_KEEP_DAYS + 1)).strftime("%d.%m.%Y")
        new_day = date.today().strftime("%d.%m.%Y")
        await db.log_event("k1", "birthday", "EMP-0001", "А", "d", "111", old_day, "09:00")
        await db.log_event("k2", "birthday", "EMP-0002", "Б", "d", "111", new_day, "09:00")
        await db.log_event("bad-date-row", "birthday", "EMP-0003", "В", "d", "111", "", "09:00")

        removed = await db.prune_events()
        assert removed == 1

        keys = await db.sent_event_keys()
        assert keys == {"k2", "bad-date-row"}

    asyncio.run(scenario())


# ---------------------------------------------------------------- throttling

def test_api_calls_are_throttled():
    async def scenario():
        db = make_db()
        start = time.monotonic()
        await db.setting_get("nope", "")
        await db.setting_get("nope", "")  # cached, no extra API call
        db._settings_cache = None         # force a second real read
        await db.setting_get("nope", "")
        elapsed = time.monotonic() - start
        assert elapsed >= MIN_API_INTERVAL * 0.9

    asyncio.run(scenario())


def test_settings_cache_invalidation_on_set():
    async def scenario():
        db = make_db()
        assert await db.setting_get("digest_time") == "09:00"  # seeded default
        await db.setting_set("digest_time", "10:30")
        # cache invalidated by setting_set: new value visible at once
        assert await db.setting_get("digest_time") == "10:30"

    asyncio.run(scenario())
