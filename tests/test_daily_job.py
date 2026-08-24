"""Интеграционный тест ежедневного джоба: уведомления, дайджест, дедуп, бэкап."""

import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import Config
from bot.models import Employee
from bot.services.auth import AuthService
from bot.services.notifications import run_daily_job
from bot.utils.dates import fmt_date

from tests.fakes import FakeBot, FakeSpreadsheet


def make_cfg() -> Config:
    return Config(bot_token="t", spreadsheet_id="fake", credentials_file="none.json",
                  admin_ids=(111,), timezone="Asia/Almaty", default_digest_time="09:00")


def make_db():
    from bot.services.sheets import SheetsDB

    db = SheetsDB(make_cfg())
    db._sh = FakeSpreadsheet()
    db._ensure_structure_sync()
    return db


def test_daily_job_notifications_digest_dedup_backup(tmp_path, monkeypatch):
    from bot.services import backup as backup_mod

    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_path / "backups")

    async def scenario():
        db = make_db()
        cfg = make_cfg()
        auth = AuthService(db, cfg)

        await db.user_upsert(111, "Ада", "admin", True, "test")
        await db.user_upsert(222, "Боря", "manager", True, "test")

        today = date.today()
        bday = fmt_date(today.replace(year=today.year - 30))
        hire_yesterday = fmt_date(today.replace(day=max(today.day - 1, 1)))
        emp = Employee(eid="EMP-0001", fio="Тест Тестов", dept="Розница", branch="Магазин №7",
                       pos="Бариста", birthday=bday, hire_date=hire_yesterday,
                       status="Работает")
        await db.append_employee(emp)

        bot = FakeBot()
        await run_daily_job(bot, db, auth, cfg)

        texts = [t for _, t in bot.sent]
        # Персональное ДР-уведомление ушло обоим пользователям
        assert sum("Сегодня день рождения" in t for t in texts) == 2
        # Дайджест тоже обоим
        assert sum("HR-ДАЙДЖЕСТ" in t for t in texts) == 2
        # Ключ события записан в журнал (защита от дублей)
        keys = await db.sent_event_keys()
        assert len(keys) == 1 and keys.pop().startswith("birthday|EMP-0001|")

        # Повторный запуск в тот же день: дублей ДР больше нет
        before = len(bot.sent)
        await run_daily_job(bot, db, auth, cfg)
        new_texts = [t for _, t in bot.sent[before:]]
        assert all("Сегодня день рождения" not in t for t in new_texts)

        # Бэкап создан в подмененную папку
        backups = list(backup_mod.BACKUP_DIR.glob("*.json"))
        assert len(backups) == 1

    asyncio.run(scenario())
