"""Интеграционные тесты SheetsDB на фейковом gspread (без сети)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fakes import FakeSpreadsheet  # noqa: F401

from bot.config import Config
from bot.models import STATUS_FIRED, Employee
from bot.services.sheets import ALL_SHEETS, SheetsDB


def make_cfg() -> Config:
    return Config(
        bot_token="test-token",
        spreadsheet_id="fake-id",
        credentials_file="no-file.json",
        admin_ids=(111,),
        timezone="Asia/Almaty",
        default_digest_time="09:00",
    )


def make_db():
    cfg = make_cfg()
    db = SheetsDB(cfg)
    db._sh = FakeSpreadsheet()
    db._ensure_structure_sync()
    return db


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- структура

def test_structure_created_with_headers():
    db = make_db()
    for title in ALL_SHEETS:
        ws = db._ws[title]
        rows = ws.get_all_values()
        assert rows and [c.strip() for c in rows[0][:len(ALL_SHEETS[title])]] == ALL_SHEETS[title], title


def test_reasons_seeded_and_digest_default():
    db = make_db()
    dicts = run(db.dicts())
    assert "По собственному желанию" in dicts.reasons
    assert run(db.setting_get("digest_time", "")) == "09:00"


# ---------------------------------------------------------------- сотрудники

def _emp(**kw) -> Employee:
    base = dict(eid="EMP-0001", fio="Иванова Алина", phone="+77777777777", dept="Розница",
                pos="Бариста", branch="Магазин №7", supervisor="Петрова Анна",
                birthday="15.09.2002", hire_date="01.08.2026",
                status="Работает", created_by="hr")
    base.update(kw)
    return Employee(**base)


def test_employee_crud_cycle():
    db = make_db()

    assert run(db.next_emp_id()) == "EMP-0001"
    run(db.append_employee(_emp()))
    emps = run(db.get_employees())
    assert len(emps) == 1 and emps[0].eid == "EMP-0001" and emps[0].row == 2
    assert run(db.next_emp_id()) == "EMP-0002"

    found = run(db.find_employee_by_id("emp-0001"))
    assert found is not None and found.fio == "Иванова Алина"

    # Обновление статуса (увольнение) сохраняется в таблице
    found.status = STATUS_FIRED
    found.fire_date = "24.08.2026"
    run(db.update_employee(found))
    again = run(db.find_employee_by_id("EMP-0001"))
    assert again.status == STATUS_FIRED and again.fire_date == "24.08.2026"


def test_history_filtering_by_eid():
    db = make_db()
    run(db.add_history("EMP-0001", "Иванова Алина", "01.08.2026", "принятие на работу",
                       "", "Бариста / Розница", "", "hr"))
    run(db.add_history("EMP-0002", "Другой Сотрудник", "02.08.2026", "принятие на работу",
                       "", "Кассир / Розница", "", "hr"))
    mine = run(db.get_history("EMP-0001"))
    assert len(mine) == 1 and mine[0][5] == "Бариста / Розница"
    allh = run(db.get_history_all())
    assert len(allh) == 2


def test_dismissals_and_events_log():
    db = make_db()
    run(db.add_dismissal(["EMP-0001", "Иванова Алина", "Бариста", "Розница", "Магазин №7",
                          "01.08.2026", "24.08.2026", "По собственному желанию", "", "hr"]))
    dis = run(db.get_dismissals())
    assert dis and dis[0][7] == "По собственному желанию"

    assert run(db.sent_event_keys()) == set()
    run(db.log_event("birthday|EMP-0001|2026-08-24", "birthday", "EMP-0001",
                     "Иванова Алина", "текст", "111", "24.08.2026", "09:00"))
    assert run(db.sent_event_keys()) == {"birthday|EMP-0001|2026-08-24"}


# ---------------------------------------------------------------- справочники/пользователи/настройки

def test_dicts_append_visible():
    db = make_db()
    run(db.dict_append(0, "IT-отдел"))
    d = run(db.dicts())
    assert "IT-отдел" in d.departments


def test_users_upsert_update_delete():
    db = make_db()
    run(db.user_upsert(222, "Боря", "manager"))
    u = run(db.user_find(222))
    assert u is not None and u.role == "manager" and u.notifications is True

    run(db.user_upsert(222, "Боря", "hr"))  # апдейт роли
    u = run(db.user_find(222))
    assert u.role == "hr"
    users = run(db.users_all())
    assert len(users) == 1  # не задублился

    assert run(db.user_delete(222)) is True
    assert run(db.user_find(222)) is None
    assert run(db.user_delete(222)) is False


def test_settings_roundtrip_and_overwrite():
    db = make_db()
    run(db.setting_set("custom", "v1"))
    assert run(db.setting_get("custom", "")) == "v1"
    run(db.setting_set("custom", "v2"))
    assert run(db.setting_get("custom", "")) == "v2"  # перезапись, не дубль
    rows = db._get_rows_sync("Настройки")
    assert sum(1 for r in rows if r and r[0] == "custom") == 1
