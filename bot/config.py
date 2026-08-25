"""App config; secrets come from .env only."""

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
    fsm_file: str = "fsm_state.json"


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    ids = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return tuple(ids)


def _resolve_path(value: str, default: str) -> str:
    p = Path((value or default).strip())
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p)


def load_config() -> Config:
    token = (os.getenv("BOT_TOKEN") or "").strip()
    sheet_id = (os.getenv("SPREADSHEET_ID") or "").strip()
    missing = [name for name, val in (("BOT_TOKEN", token), ("SPREADSHEET_ID", sheet_id)) if not val]
    if missing:
        raise RuntimeError(
            "Не заполнены переменные в .env: " + ", ".join(missing)
            + ". Скопируйте .env.example в .env и заполните значения."
        )

    return Config(
        bot_token=token,
        spreadsheet_id=sheet_id,
        credentials_file=_resolve_path(os.getenv("GOOGLE_CREDENTIALS_FILE"), "service_account.json"),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS") or ""),
        timezone=(os.getenv("TIMEZONE") or "Europe/Moscow").strip(),
        default_digest_time=(os.getenv("DEFAULT_DIGEST_TIME") or "09:00").strip(),
        fsm_file=_resolve_path(os.getenv("FSM_FILE"), "fsm_state.json"),
    )
