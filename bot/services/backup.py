"""Daily backup of all sheets into backups/."""

import logging
import time
from pathlib import Path

from bot.config import BASE_DIR

BACKUP_DIR = BASE_DIR / "backups"
KEEP_DAYS = 30


async def make_daily_backup(db) -> Path | None:
    BACKUP_DIR.mkdir(exist_ok=True)
    name = time.strftime("%Y-%m-%d") + ".json"
    path = BACKUP_DIR / name
    try:
        await db.dump_backup(path)
        _prune_old()
        return path
    except Exception:  # noqa: BLE001
        log.exception("Резервное копирование не удалось")
        return None


def _prune_old() -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for p in BACKUP_DIR.glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass
