"""Ежедневные уведомления и HR-дайджест.

Один фоновый цикл: раз в минуту сверяет локальное время со временем
дайджеста из листа «Настройки». Отправляет персональные уведомления
(с защитой от повторов через лист «События») и общий дайджест.
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError

from bot.config import Config
from bot.services import events_calc
from bot.services.auth import AuthService
from bot.services.backup import make_daily_backup
from bot.services.sheets import SheetsDB

log = logging.getLogger(__name__)

CHECK_INTERVAL = 20  # секунд между проверками времени


def now_local(cfg: Config) -> datetime:
    try:
        tz = ZoneInfo(cfg.timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("Asia/Almaty")
    return datetime.now(tz)


async def _send(bot: Bot, chat_id: int, text: str, reply_markup=None) -> bool:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(chat_id, text, reply_markup=reply_markup)
            return True
        except TelegramAPIError:
            log.exception("Повторная отправка %s не удалась", chat_id)
    except TelegramAPIError:
        log.exception("Не удалось отправить сообщение %s", chat_id)
    return False


def digest_text(today: datetime, counts: dict[str, int]) -> str:
    return (
        f"☀ HR-ДАЙДЖЕСТ {today.day} {_month_gen(today.month)} {today.year}\n\n"
        f"🎂 Дни рождения — {counts['birthdays']}\n"
        f"🏆 Годовщины — {counts['anniversaries']}\n"
        f"⏳ Испытательный срок — {counts['probation']}\n"
        f"🏖 Отпуска — {counts['vacations']}\n"
        f"👋 Увольнения — {counts['dismissals']}\n"
        f"👤 Новые сотрудники — {counts['new_hires']}"
    )


_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
           "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _month_gen(m: int) -> str:
    return _MONTHS[m - 1]


async def run_daily_job(bot: Bot, db: SheetsDB, auth: AuthService, cfg: Config,
                        events_kb=None) -> None:
    """Персональные уведомления за день + дайджест + бэкап."""
    today = now_local(cfg).date()
    emps = await db.get_employees(fresh=True)
    due = events_calc.all_due_notifications(emps, today)
    sent_keys = await db.sent_event_keys()
    pending = [n for n in due if n.key not in sent_keys]

    recipients = await auth.recipients()

    for n in pending:
        ok_ids = []
        for u in recipients:
            if await _send(bot, u.uid, n.text):
                ok_ids.append(str(u.uid))
        if ok_ids:
            await db.log_event(
                key=n.key, kind=n.kind, eid=n.eid, fio=n.fio, desc=n.text[:200],
                recipients=", ".join(ok_ids), sent_day=today.strftime("%d.%m.%Y"),
                sent_time=datetime.now().strftime("%H:%M"),
            )
            log.info("Событие %s отправлено (%s)", n.key, len(ok_ids))

    counts = events_calc.digest_counts(emps, today)
    kb = events_kb() if events_kb else None
    for u in recipients:
        await _send(bot, u.uid, digest_text(now_local(cfg), counts), reply_markup=kb)

    await make_daily_backup(db)
    log.info("Ежедневный джоб выполнен: уведомлений=%s, получателей=%s", len(pending), len(recipients))


async def scheduler_loop(bot: Bot, db: SheetsDB, auth: AuthService, cfg: Config,
                         events_kb=None) -> None:
    last_run_date = None
    while True:
        try:
            now = now_local(cfg)
            hhmm = now.strftime("%H:%M")
            target = await db.setting_get("digest_time", cfg.default_digest_time)
            enabled = await db.setting_get("notifications_enabled", "1") != "0"
            if enabled and hhmm == target and last_run_date != now.date():
                last_run_date = now.date()
                await run_daily_job(bot, db, auth, cfg, events_kb)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в цикле планировщика")
        await asyncio.sleep(CHECK_INTERVAL)
