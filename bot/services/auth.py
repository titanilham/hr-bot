"""Сервис авторизации: роли, сидирование админов из .env."""

import logging

from bot.config import Config
from bot.models import ROLE_ADMIN, User
from bot.services.sheets import SheetsDB

log = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: SheetsDB, cfg: Config):
        self.db = db
        self.cfg = cfg
        self._cache: dict[int, User] = {}

    async def bootstrap(self) -> None:
        """Добавляет админов из ADMIN_IDS (идемпотентно)."""
        for uid in self.cfg.admin_ids:
            existing = await self.db.user_find(uid)
            if existing is None:
                await self.db.user_upsert(uid, name="admin", role=ROLE_ADMIN, added_by=".env")
                log.info("Администратор %s добавлен из ADMIN_IDS", uid)

    async def get_user(self, uid: int, refresh: bool = False) -> User | None:
        if not refresh and uid in self._cache:
            return self._cache[uid]
        user = await self.db.user_find(uid)
        self._cache[uid] = user  # кэшируем и None — чтобы не дергать таблицу каждый раз
        return user

    def invalidate(self, uid: int | None = None) -> None:
        if uid is None:
            self._cache.clear()
        else:
            self._cache.pop(uid, None)

    async def recipients(self) -> list[User]:
        """Все пользователи с включенными уведомлениями."""
        users = await self.db.users_all()
        return [u for u in users if u.notifications]
