"""Все inline-клавиатуры бота."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

PAGE_SIZE = 10

CB_MENU = "menu"


def main_menu(is_full: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Сотрудники", callback_data="emp")
    kb.button(text="➕ Добавить сотрудника", callback_data="add")
    kb.button(text="🔎 Найти сотрудника", callback_data="srch")
    kb.button(text="🔔 События", callback_data="evt")
    if is_full:
        kb.button(text="🔄 Кадровые изменения", callback_data="xfer")
        kb.button(text="👋 Увольнение", callback_data="firemenu")
        kb.button(text="📊 HR-отчет", callback_data="rep")
        kb.button(text="⚙ Настройки", callback_data="set")
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu_row(kb: InlineKeyboardBuilder) -> None:
    kb.row()
    kb.button(text="⬅ В меню", callback_data=CB_MENU)


def employees_filters() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Все сотрудники", callback_data="empl:all:0")
    kb.button(text="✅ Работающие", callback_data="empl:act:0")
    kb.button(text="👋 Уволенные", callback_data="empl:fired:0")
    kb.button(text="⏳ На испытательном сроке", callback_data="empl:proba:0")
    kb.button(text="🏬 По отделам", callback_data="fdep")
    kb.button(text="📍 По филиалам", callback_data="fbr")
    kb.button(text="⬅ В меню", callback_data=CB_MENU)
    kb.adjust(1)
    return kb.as_markup()


def dict_list_keyboard(prefix: str, values: list[str], back_cb: str,
                       back_text: str = "⬅ Назад") -> InlineKeyboardMarkup:
    """Список значений справочника как кнопок-фильтров."""
    kb = InlineKeyboardBuilder()
    for i, v in enumerate(values):
        kb.button(text=v[:40], callback_data=f"{prefix}{i}")
    kb.button(text=back_text, callback_data=back_cb)
    kb.adjust(1)
    return kb.as_markup()


def employees_page(items: list[tuple[int, object]], page: int, total_pages: int,
                   filter_key: str) -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardButton  # noqa: PLC0415

    def name_btn(num: int, e):
        label = f"{num}. {e.fio}"
        if len(label) > 60:
            label = label[:57] + "…"
        return InlineKeyboardButton(text=label, callback_data=f"card:{e.eid}")

    kb = InlineKeyboardBuilder()
    # Сетка 2 в ряд — крупные кнопки вместо полной ширины
    names = [name_btn(num, e) for num, e in items]
    for i in range(0, len(names), 2):
        kb.row(*names[i:i + 2])
    # пагинация
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ Предыдущая",
                                        callback_data=f"empl:{filter_key}:{page - 1}"))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}",
                                        callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Следующая ▶",
                                        callback_data=f"empl:{filter_key}:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅ Фильтры", callback_data="emp"),
           InlineKeyboardButton(text="🏠 Меню", callback_data=CB_MENU))
    return kb.as_markup()


def card_keyboard(eid: str, is_full: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if is_full:
        kb.button(text="✏ Редактировать", callback_data=f"edit:{eid}")
        kb.button(text="🔄 Перевести", callback_data=f"xfer:{eid}")
    kb.button(text="📜 История", callback_data=f"hist:{eid}")
    if is_full:
        kb.button(text="👋 Уволить", callback_data=f"fire:{eid}")
    kb.row()
    kb.button(text="◀ Назад", callback_data="emp")
    kb.adjust(2, 1)
    return kb.as_markup()


def edit_fields_keyboard(eid: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, title in EDITABLE_FIELDS.items():
        kb.button(text=title, callback_data=f"edf:{eid}:{key}")
    kb.row()
    kb.button(text="◀ К карточке", callback_data=f"card:{eid}")
    kb.adjust(2)
    return kb.as_markup()


EDITABLE_FIELDS = {
    "fio": "ФИО",
    "phone": "Телефон",
    "gender": "Пол",
    "dept": "Отдел",
    "pos": "Должность",
    "branch": "Филиал",
    "supervisor": "Руководитель",
    "birthday": "Дата рождения",
    "hire_date": "Дата приема",
    "probation_end": "Испытательный срок",
    "comment": "Комментарий",
}


def dict_picker(prefix: str, values: list[str], cancel_cb: str = "addcancel",
                cancel_text: str = "❌ Отменить",
                none_cb: str | None = None,
                none_text: str = "🚫 Нет руководителя") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, v in enumerate(values):
        kb.button(text=v[:40], callback_data=f"{prefix}:{i}")
    kb.row()
    kb.button(text="✍️ Своё значение", callback_data=f"{prefix}:manual")
    if none_cb:
        kb.button(text=none_text, callback_data=none_cb)
    kb.row()
    kb.button(text=cancel_text, callback_data=cancel_cb)
    kb.adjust(2, 2, 1)
    return kb.as_markup()


PROBATION_OPTIONS = [("m1", "1 месяц"), ("m2", "2 месяца"), ("m3", "3 месяца"),
                     ("none", "Без испытательного срока"), ("manual", "✍️ Своя дата")]

GENDER_OPTIONS = [("M", "Мужской"), ("F", "Женский"), ("-", "Не указан")]


def choice_keyboard(prefix: str, options: list[tuple[str, str]],
                    cancel_cb: str = "addcancel",
                    cancel_text: str = "❌ Отменить") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for val, label in options:
        kb.button(text=label, callback_data=f"{prefix}:{val}")
    kb.row()
    kb.button(text=cancel_text, callback_data=cancel_cb)
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def preview_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сохранить", callback_data="addsave")
    kb.button(text="✏ Изменить", callback_data="addedit")
    kb.button(text="❌ Отменить", callback_data="addcancel")
    kb.adjust(1)
    return kb.as_markup()


def draft_edit_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, title in ADD_DRAFT_FIELDS.items():
        kb.button(text=title, callback_data=f"dft:{key}")
    kb.row()
    kb.button(text="❌ Отменить добавление", callback_data="addcancel")
    kb.adjust(2)
    return kb.as_markup()


ADD_DRAFT_FIELDS = EDITABLE_FIELDS


def skip_confirm_keyboard(skip_text: str, skip_cb: str, confirm_cb: str, cancel_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=skip_text, callback_data=skip_cb)
    kb.button(text="✅ Подтвердить", callback_data=confirm_cb)
    kb.button(text="❌ Отмена", callback_data=cancel_cb)
    kb.adjust(1)
    return kb.as_markup()


def today_or_input_keyboard(today_cb: str, cancel_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Сегодня", callback_data=today_cb)
    kb.row()
    kb.button(text="❌ Отмена", callback_data=cancel_cb)
    return kb.as_markup()


def simple_cancel_keyboard(cancel_cb: str, text: str = "❌ Отмена") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=text, callback_data=cancel_cb)
    return kb.as_markup()


def events_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎂 Дни рождения", callback_data="evt:bdy")
    kb.button(text="🏆 Годовщины", callback_data="evt:anniv")
    kb.button(text="⏳ Испытательный срок", callback_data="evt:proba")
    kb.button(text="🏖 Отпуска — в будущем", callback_data="evt:vac")
    kb.button(text="👋 Увольнения", callback_data="evt:dis")
    kb.button(text="👤 Новые сотрудники", callback_data="evt:new")
    kb.button(text="⬅ В меню", callback_data=CB_MENU)
    kb.adjust(1)
    return kb.as_markup()


def report_periods() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data="rep:t")
    kb.button(text="Эта неделя", callback_data="rep:w")
    kb.row()
    kb.button(text="Этот месяц", callback_data="rep:m")
    kb.button(text="Прошлый месяц", callback_data="rep:pm")
    kb.row()
    kb.button(text="⬅ В меню", callback_data=CB_MENU)
    return kb.as_markup()


def settings_keyboard(digest_time: str, notif_on: bool,
                      tz: str | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Пользователи и доступы", callback_data="set:users")
    kb.button(text=f"⏰ Время дайджеста: {digest_time}", callback_data="set:dtime")
    kb.button(text=f"🔔 Уведомления: {'вкл' if notif_on else 'выкл'}", callback_data="set:notif")
    if tz:
        kb.button(text=f"🌍 Часовой пояс: {tz}", callback_data="set:tz")
    kb.button(text="📚 Справочники", callback_data="set:dicts")
    kb.button(text="⬅ В меню", callback_data=CB_MENU)
    kb.adjust(1)
    return kb.as_markup()


def timezone_keyboard(current: str) -> InlineKeyboardMarkup:
    from bot.utils.dates import COMMON_TIMEZONES
    kb = InlineKeyboardBuilder()
    for i, (name, label) in enumerate(COMMON_TIMEZONES):
        mark = "✅ " if name == current else ""
        kb.button(text=f"{mark}{label}", callback_data=f"tzp:{i}")
    kb.row()
    kb.button(text="✍️ Свой вариант (IANA или UTC+N)", callback_data="set:tzt")
    kb.row()
    kb.button(text="⬅ К настройкам", callback_data="set")
    kb.adjust(1)
    return kb.as_markup()


def roles_keyboard(role_cb_prefix: str, cancel_cb: str | None = None) -> InlineKeyboardMarkup:
    from bot.models import ROLE_ADMIN, ROLE_HR, ROLE_MANAGER, ROLE_TITLES
    kb = InlineKeyboardBuilder()
    for r in (ROLE_ADMIN, ROLE_HR, ROLE_MANAGER):
        kb.button(text=ROLE_TITLES[r], callback_data=f"{role_cb_prefix}{r}")
    if cancel_cb:
        kb.row()
        kb.button(text="❌ Отмена", callback_data=cancel_cb)
    kb.adjust(1)
    return kb.as_markup()
