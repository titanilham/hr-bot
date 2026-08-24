"""Диагностика окружения HR-бота (без запуска самого бота).

Проверяет по шагам:
 1. наличие .env и корректность значений
 2. валидность токена Telegram (getMe)
 3. файл сервисного аккаунта Google
 4. доступ к таблице Google Sheets (чтение + создание листов при необходимости)

Запуск: python scripts/check_setup.py
"""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK = "  [OK] "
FAIL = "  [FAIL] "
WARN = "  [--] "

failed = False


def step(cond_ok: bool, msg_ok: str, msg_fail: str, warn_only=False) -> bool:
    global failed
    if cond_ok:
        print(OK + msg_ok)
        return True
    if warn_only:
        print(WARN + msg_fail)
    else:
        print(FAIL + msg_fail)
        failed = True
    return False


def main() -> int:
    print("Проверка окружения HR-бота\n")

    # 1. .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    step(env_path.exists(), ".env найден",
         ".env не найден. Скопируйте .env.example в .env и заполните.")

    from bot.config import BASE_DIR, load_config

    try:
        cfg = load_config()
        print(OK + f"Конфигурация загружена: таблица {cfg.spreadsheet_id[:12]}..., "
                   f"таймзона {cfg.timezone}, админов из .env: {len(cfg.admin_ids) or 'нет'}")
    except RuntimeError as e:
        print(FAIL + str(e))
        return 1

    # 2. Токен Telegram
    try:
        url = f"https://api.telegram.org/bot{cfg.bot_token}/getMe"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
        if data.get("ok"):
            me = data["result"]
            print(OK + f"Токен Telegram валиден: @{me['username']}")
        else:
            step(False, "", f"Telegram вернул ошибку: {data}")
    except Exception as e:  # noqa: BLE001
        step(False, "", f"Токен Telegram не работает: {e}")

    # 3. Сервисный аккаунт
    creds = Path(cfg.credentials_file)
    email_hint = ""
    if creds.exists():
        try:
            with open(creds, encoding="utf-8") as f:
                info = json.load(f)
            email_hint = info.get("client_email", "")
            print(OK + f"Сервисный аккаунт: {email_hint or '(email не найден в JSON)'}")
        except Exception as e:  # noqa: BLE001
            step(False, "", f"Файл ключа поврежден ({e}). Скачайте JSON заново.")
    else:
        step(False, "",
             f"Файл сервисного аккаунта не найден: {creds}\n"
             "       Получите его за 5 минут — инструкция в README.md, раздел «Подключение Google Sheets».")

    # 4. Доступ к таблице
    if creds.exists():
        try:
            import gspread

            gc = gspread.service_account(filename=cfg.credentials_file)
            sh = gc.open_by_key(cfg.spreadsheet_id)
            print(OK + f"Таблица открыта: «{sh.title}»")
            sheets = sh.worksheets()
            if not sheets:
                print(WARN + "В таблице пока нет листов — бот создаст их при первом запуске.")
            for ws in sheets:
                rows = len(ws.get_all_values())
                print(f"       лист «{ws.title}»: строк {max(rows - 1, 0)}")
            missing = {"Сотрудники", "История", "Увольнения", "События", "Справочники"} - {
                ws.title for ws in sheets}
            if missing:
                print(WARN + "Нет листов: " + ", ".join(sorted(missing))
                      + " — бот создаст их сам при первом запуске.")
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            hint = ""
            if "PERMISSION_DENIED" in msg or "403" in msg:
                hint = ("\n       Похоже, таблица не расшарена сервисному аккаунту."
                        + (f"\n       Поделитесь ею с адресом: {email_hint}" if email_hint else "")
                        + "\n       Право: Редактор.")
            elif "404" in msg or "NOT_FOUND" in msg:
                hint = "\n       Проверьте SPREADSHEET_ID в .env."
            step(False, "", f"Нет доступа к таблице: {msg}{hint}")

    # 5. Админы
    if not cfg.admin_ids:
        print(WARN + "ADMIN_IDS пуст. Первый запуск: напишите боту /start — "
                     "он покажет ваш Telegram ID, внесите его в ADMIN_IDS.")

    print()
    if failed:
        print("Есть проблемы — исправьте их и запустите проверку снова.")
        return 1
    print("Всё готово. Запуск бота: python main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
