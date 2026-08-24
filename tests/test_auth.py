"""Тесты бутстрапа первого администратора."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import Config
from bot.services.auth import AuthService
from bot.services.sheets import SheetsDB

from tests.fakes import FakeSpreadsheet


def make_auth(admin_ids=()) -> AuthService:
    cfg = Config(bot_token="t", spreadsheet_id="fake", credentials_file="none.json",
                 admin_ids=tuple(admin_ids), timezone="Asia/Almaty",
                 default_digest_time="09:00")
    db = SheetsDB(cfg)
    db._sh = FakeSpreadsheet()
    db._ensure_structure_sync()
    return AuthService(db, cfg)


def test_first_user_becomes_admin():
    auth = make_auth()
    claimed = asyncio.run(auth.try_claim_first_admin(777, "Тест Юзер"))
    assert claimed is True

    # Второй раз уже нельзя — пользователь существует
    claimed2 = asyncio.run(auth.try_claim_first_admin(888, "Второй"))
    assert claimed2 is False

    user = asyncio.run(auth.get_user(777, refresh=True))
    assert user is not None and user.role == "admin"


def test_no_bootstrap_when_env_admins_set():
    auth = make_auth(admin_ids=(111,))
    claimed = asyncio.run(auth.try_claim_first_admin(777, "Тест Юзер"))
    assert claimed is False


def test_no_bootstrap_when_users_exist():
    async def scenario():
        auth = make_auth()
        await auth.db.user_upsert(1, "Существующий", "manager")
        return await auth.try_claim_first_admin(777, "Новичок")

    assert asyncio.run(scenario()) is False


def test_bootstrap_seeds_env_admins():
    auth = make_auth(admin_ids=(42,))
    asyncio.run(auth.bootstrap())
    user = asyncio.run(auth.get_user(42))
    assert user is not None and user.role == "admin"
