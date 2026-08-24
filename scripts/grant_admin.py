"""Разовая выдача роли администратора пользователю из ADMIN_IDS."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from bot.config import load_config  # noqa: E402
from bot.models import ROLE_ADMIN  # noqa: E402
from bot.services.sheets import SheetsDB  # noqa: E402


async def main() -> None:
    cfg = load_config()
    db = SheetsDB(cfg)
    await db.ensure_structure()
    for uid in cfg.admin_ids:
        await db.user_upsert(uid, name="HR", role=ROLE_ADMIN,
                             notifications=True, added_by="setup")
        print(f"OK: {uid} -> admin")
    users = await db.users_all()
    for u in users:
        print(f"   пользователь: {u.uid} роль={u.role} уведомления={u.notifications}")


if __name__ == "__main__":
    asyncio.run(main())
