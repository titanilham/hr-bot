"""Смоук-тест: конфиг, роутеры и клавиатуры собираются без сети."""

import logging

logging.basicConfig(level=logging.ERROR)

from aiogram import Dispatcher  # noqa: E402

from bot.config import load_config  # noqa: E402
from bot.handlers import all_routers  # noqa: E402
from bot.keyboards import (  # noqa: E402
    employees_filters,
    events_menu,
    main_menu,
    report_periods,
)
from bot.models import ROLE_HR, User  # noqa: E402

cfg = load_config()
print("CONFIG_OK", cfg.spreadsheet_id[:8], "admins=", len(cfg.admin_ids), cfg.timezone)

dp = Dispatcher()
dp.include_routers(*all_routers())
n = sum(len(r.message.handlers) + len(r.callback_query.handlers) for r in all_routers())
print("ROUTERS_OK handlers~", n)

u = User(uid=1, role=ROLE_HR)
assert main_menu(True).inline_keyboard
assert main_menu(False).inline_keyboard
employees_filters()
events_menu()
report_periods()
print("KEYBOARDS_OK")
