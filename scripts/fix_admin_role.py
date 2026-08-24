# Восстановление/проверка ролей пользователей. Одноразовый скрипт.
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()
from bot.config import load_config  # noqa: E402
from bot.services.sheets import SheetsDB  # noqa: E402

ADMIN_UID = 1456945518


async def main() -> None:
    db = SheetsDB(load_config())
    await db.ensure_structure()
    print("--- before ---")
    for u in await db.users_all():
        print(u.uid, u.name, u.role)
    target = await db.user_find(ADMIN_UID)
    if target is None:
        await db.user_upsert(ADMIN_UID, "Admin", "admin")
        print(f"restored missing admin {ADMIN_UID}")
    elif target.role != "admin":
        await db.user_upsert(ADMIN_UID, target.name, "admin",
                             notifications=target.notifications)
        print(f"fixed role {target.role} -> admin for {ADMIN_UID}")
    else:
        print("already admin, nothing to do")
    print("--- after ---")
    for u in await db.users_all():
        print(u.uid, u.name, u.role)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
