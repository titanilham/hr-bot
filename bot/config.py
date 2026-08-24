"""Конфигурация приложения.

Все секреты и ссылки хранятся в файле .env (не попадает в git).
config.py только читает переменные окружения — это безопаснее,
чем хранить токены прямо в коде.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Config:
    bot_token: str
    spreadsheet_id: str
    credentials_file: str
    admin_ids: tuple[int, ...]
    timezone: str
    default_digest_time: str


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    ids = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return tuple(ids)


def load_config() -> Config:
    token = (os.getenv("BOT_TOKEN") or "").strip()
    sheet_id = (os.getenv("SPREADSHEET_ID") or "").strip()
    missing = [name for name, val in (("BOT_TOKEN", token), ("SPREADSHEET_ID", sheet_id)) if not val]
    if missing:
        raise RuntimeError(
            "Не заполнены переменные в .env: " + ", ".join(missing)
            + ". Скопируйте .env.example в .env и заполните значения."
        )

    creds = (os.getenv("GOOGLE_CREDENTIALS_FILE") or "service_account.json").strip()
    creds_path = Path(creds)
    if not creds_path.is_absolute():
        creds_path = BASE_DIR / creds_path

    return Config(
        bot_token=token,
        spreadsheet_id=sheet_id,
        credentials_file=str(creds_path),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS") or ""),
        timezone=(os.getenv("TIMEZONE") or "Asia/Almaty").strip(),
        default_digest_time=(os.getenv("DEFAULT_DIGEST_TIME") or "09:00").strip(),
    )
