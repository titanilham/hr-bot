"""Юнит-тесты часовых поясов и раскладок клавиатур."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_normalize_timezone():
    from bot.utils.dates import normalize_timezone as ntz

    assert ntz("Europe/Moscow") == "Europe/Moscow"
    assert ntz("мск") == "Europe/Moscow"
    assert ntz("МСК") == "Europe/Moscow"
    assert ntz("+3") == "Etc/GMT-3"
    assert ntz("UTC+5") == "Etc/GMT-5"
    assert ntz("-8") == "Etc/GMT+8"
    assert ntz("Asia/Almaty") == "Asia/Almaty"
    assert ntz("ерунда") is None
    assert ntz("") is None


def test_employees_page_grid_two_per_row():
    from bot.keyboards import employees_page

    class _E:
        fio = "Иванов Иван"
        eid = "EMP-0001"

    markup = employees_page([(1, _E()), (2, _E()), (3, _E())], 0, 1, "all")
    rows = markup.inline_keyboard
    # первая строка: две крупные кнопки с именами, третья переносится
    assert len(rows[0]) == 2
    assert len(rows[1]) == 1
    assert "card:EMP-0001" in rows[0][0].callback_data


def test_dict_picker_has_none_supervisor():
    from bot.keyboards import dict_picker

    markup = dict_picker("addd:supervisor", ["Ким Ольга"],
                         none_cb="addd:supervisor:none")
    flat = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "addd:supervisor:none" in flat
    assert any(b.text == "🚫 Нет руководителя"
               for row in markup.inline_keyboard for b in row)


def test_settings_keyboard_has_tz():
    from bot.keyboards import settings_keyboard

    markup = settings_keyboard("09:00", True, "Europe/Moscow")
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert any("Часовой пояс" in t for t in texts)
    # без пояса кнопка не добавляется (обратная совместимость)
    markup2 = settings_keyboard("09:00", True)
    texts2 = [b.text for row in markup2.inline_keyboard for b in row]
    assert not any("Часовой пояс" in t for t in texts2)
