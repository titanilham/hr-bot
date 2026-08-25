"""Persistent FSM storage: survives bot restarts (JSON file on disk)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from aiogram.fsm.storage.base import BaseStorage, StorageKey

log = logging.getLogger(__name__)


def _state_value(state: Any) -> Optional[str]:
    """aiogram passes State objects or plain strings; store strings."""
    if state is None:
        return None
    return str(getattr(state, "state", state))


class JSONFileStorage(BaseStorage):
    """Minimal JSON-backed FSM storage.

    Keeps all FSM states/data in memory and atomically persists every change,
    so unfinished wizards survive a bot restart.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    # --- persistence helpers -------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                self._data = json.loads(raw) if raw.strip() else {}
            except Exception:  # noqa: BLE001
                log.exception("Не удалось прочитать %s, начинаю с пустого хранилища",
                              self._path)
                self._data = {}
        self._loaded = True

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    @staticmethod
    def _key(key: StorageKey) -> str:
        thread = getattr(key, "thread_id", None) or ""
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{thread}"

    def _record(self, key_str: str) -> Dict[str, Any]:
        return self._data.setdefault(key_str, {"state": None, "data": {}})

    # --- BaseStorage API ------------------------------------------------------

    async def close(self) -> None:
        async with self._lock:
            try:
                self._save()
            except Exception:  # noqa: BLE001
                log.exception("Не удалось сохранить FSM-хранилище при закрытии")

    async def wait_closed(self) -> None:
        return None

    async def set_state(self, key: StorageKey, state: Any = None) -> None:
        async with self._lock:
            self._load()
            self._record(self._key(key))["state"] = _state_value(state)
            self._save()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        async with self._lock:
            self._load()
            rec = self._data.get(self._key(key))
            return rec.get("state") if rec else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        async with self._lock:
            self._load()
            self._record(self._key(key))["data"] = json.loads(json.dumps(data, default=str))
            self._save()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        async with self._lock:
            self._load()
            rec = self._data.get(self._key(key))
            return dict(rec["data"]) if rec and "data" in rec else {}

    async def update_data(self, key: StorageKey, data: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            self._load()
            rec = self._record(self._key(key))
            rec["data"].update(json.loads(json.dumps(data, default=str)))
            self._save()
            return dict(rec["data"])
