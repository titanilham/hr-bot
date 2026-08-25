"""Daily notifications and digest scheduler."""

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

CHECK_INTERVAL = 20  # seconds between time checks


def now_local(cfg: Config) -> datetime:
    try:
        tz = ZoneInfo(cfg.timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("Europe/Moscow")
    return datetime.now(tz)


def now_in_tz(tz_name: str, fallback: str = "Europe/Moscow") -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        return datetime.now(ZoneInfo(fallback))


def digest_due(now_hhmm: str, target: str, enabled: bool, already_sent: bool) -> bool:
    """Catch-up semantics: run once the target time has passed, not only on exact match."""
    return bool(enabled and not already_sent and now_hhmm >= target)


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
                        events_kb=None, today=None, now_dt=None) -> None:
    """Personal notifications + digest + backup."""
    if today is None or now_dt is None:
        local_now = now_local(cfg)
        today = today or local_now.date()
        now_dt = now_dt or local_now
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
        await _send(bot, u.uid, digest_text(now_dt, counts), reply_markup=kb)

    await make_daily_backup(db)

    # keep the event log bounded so daily reads stay fast
    try:
        await db.prune_events()
    except Exception:  # noqa: BLE001
        log.exception("Не удалось обрезать лист «События»")

    log.info("Ежедневный джоб выполнен: уведомлений=%s, получателей=%s",
             len(pending), len(recipients))


async def scheduler_loop(bot: Bot, db: SheetsDB, auth: AuthService, cfg: Config,
                         events_kb=None) -> None:
    while True:
        try:
            tz_name = await db.setting_get("timezone", cfg.timezone)
            now = now_in_tz(tz_name, cfg.timezone)
            hhmm = now.strftime("%H:%M")
            target = await db.setting_get("digest_time", cfg.default_digest_time)
            enabled = await db.setting_get("notifications_enabled", "1") != "0"
            today_iso = now.date().isoformat()
            already_sent = await db.setting_get("last_digest_date", "") == today_iso
            if digest_due(hhmm, target, enabled, already_sent):
                # mark date BEFORE sending so restart won't resend
                await db.setting_set("last_digest_date", today_iso)
                await run_daily_job(bot, db, auth, cfg, events_kb,
                                    today=now.date(), now_dt=now)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в цикле планировщика")
        await asyncio.sleep(CHECK_INTERVAL)
