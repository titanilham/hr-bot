"""Одноразовый живой прогон уведомлений: дайджест через ~2 минуты.

Сдвигает время дайджеста в «Настройках» на пару минут вперед, ждет срабатывания
планировщика, показывает что ушло в Telegram и что записалось в лист «События»,
затем возвращает исходное время и сбрасывает суточную отметку.

Запуск при работающем боте: python scripts/test_notifications.py
"""

import asyncio
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from bot.config import BASE_DIR, load_config  # noqa: E402
from bot.services.notifications import now_local  # noqa: E402
from bot.services.sheets import SheetsDB  # noqa: E402


async def main() -> None:
    cfg = load_config()
    db = SheetsDB(cfg)
    await db.ensure_structure()

    old_time = await db.setting_get("digest_time", cfg.default_digest_time)
    now = now_local(cfg)
    target_dt = now + timedelta(minutes=2)
    target = target_dt.strftime("%H:%M")
    await db.setting_set("digest_time", target)
    await db.setting_set("last_digest_date", "")
    print(f"Исходное время дайджеста: {old_time}")
    print(f"Временно установлено: {target} (сейчас {now.strftime('%H:%M:%S')})")
    print("Жду срабатывания планировщика (до 4 минут)...")

    today_iso = now_local(cfg).date().isoformat()
    deadline = time.monotonic() + 240
    fired = False
    while time.monotonic() < deadline:
        await asyncio.sleep(15)
        if await db.setting_get("last_digest_date", "") == today_iso:
            fired = True
            break

    if not fired:
        print("!! Дайджест не сработал за отведенное время.")
    else:
        print("OK: планировщик сработал, сообщения отправлены.")

    # Что записалось в журнал событий
    rows = await asyncio.to_thread(db._get_rows_sync, "События")
    kinds: dict[str, int] = {}
    for r in rows[1:]:
        if r and r[1].strip():
            kinds[r[1].strip()] = kinds.get(r[1].strip(), 0) + 1
    print("Журнал «События»:")
    for kind, n in sorted(kinds.items()):
        print(f"  {kind}: {n}")
    if not kinds:
        print("  (пусто)")

    backup = BASE_DIR / "backups"
    backups = sorted(p.name for p in backup.glob("*.json")) if backup.exists() else []
    print(f"Бэкапы: {backups[-1] if backups else 'нет'}")

    # Возврат настроек: исходное время + сброс отметки, чтобы демо-уведомления
    # пришли еще раз в штатное время
    await db.setting_set("digest_time", old_time)
    await db.setting_set("last_digest_date", "")
    print(f"Настройки возвращены: digest_time={old_time}, отметка дня сброшена.")


if __name__ == "__main__":
    asyncio.run(main())
