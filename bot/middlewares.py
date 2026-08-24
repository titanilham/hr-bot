"""Middleware авторизации: пропускает только пользователей из листа «Пользователи»."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from bot.models import ROLE_ADMIN, User
from bot.services.auth import AuthService

log = logging.getLogger(__name__)

DENY_TEXT = "⛔ У вас нет доступа к HR-боту.\nДоступ предоставляет администратор."

FIRST_ADMIN_TEXT = ("👑 Вы первый пользователь — назначены администратором.\n"
                    "Добавьте коллег: ⚙ Настройки → Пользователи и доступы.")


class AccessMiddleware(BaseMiddleware):
    def __init__(self, auth: AuthService):
        self.auth = auth

    async def __call__(
        self,
        handler: Callable[..., Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        aiogram_user = data.get("event_from_user")
        if aiogram_user is None or aiogram_user.is_bot:
            return
        user = await self.auth.get_user(aiogram_user.id)
        if user is None:
            # Бутстрап: пустая система -> первый вошедший становится админом
            if await self.auth.try_claim_first_admin(aiogram_user.id, aiogram_user.full_name):
                user = User(uid=aiogram_user.id, name=aiogram_user.full_name,
                            role=ROLE_ADMIN, notifications=True)
                data["user"] = user
                if isinstance(event, CallbackQuery):
                    await event.answer()
                await event.message.answer(FIRST_ADMIN_TEXT)
                return await handler(event, data)

            log.info("Отказано в доступе: %s (%s)", aiogram_user.full_name, aiogram_user.id)
            text = DENY_TEXT + f"\n\nВаш Telegram ID: <code>{aiogram_user.id}</code>\nПередайте его администратору."
            if isinstance(event, CallbackQuery):
                await event.answer()
                await event.message.answer(text)
            else:
                await event.answer(text)
            return  # не вызываем хендлер
        data["user"] = user
        return await handler(event, data)
