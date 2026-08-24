"""⚙ Настройки: пользователи/роли, время дайджеста, уведомления, справочники."""

import logging
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import bot.keyboards as kb
from bot.models import DICT_COLUMNS, ROLE_TITLES, ROLE_MANAGER, User
from bot.services.auth import AuthService
from bot.services.sheets import SheetsDB

log = logging.getLogger(__name__)
router = Router()

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class SetStates(StatesGroup):
    waiting_uid = State()
    waiting_uname = State()
    waiting_role = State()
    waiting_time = State()
    waiting_dict_value = State()


async def _guard(cb: CallbackQuery, user: User) -> bool:
    if not user.is_full_access:
        await cb.answer("⛔ Недостаточно прав", show_alert=True)
        return False
    return True


# --------------------------------------------------------------------------
# Панель настроек
# --------------------------------------------------------------------------

@router.callback_query(F.data == "set")
async def cb_settings(cb: CallbackQuery, state: FSMContext, db: SheetsDB, user: User):
    if not await _guard(cb, user):
        return
    await state.clear()
    await cb.answer()
    digest_time = await db.setting_get("digest_time", "09:00")
    notif_on = await db.setting_get("notifications_enabled", "1") != "0"
    text = (
        "⚙ Настройки\n\n"
        f"⏰ Ежедневный дайджест: {digest_time}\n"
        f"🔔 Уведомления: {'включены' if notif_on else 'выключены'}\n"
        "📚 Справочники: отделы, должности, филиалы, руководители, причины"
    )
    await cb.message.answer(text, reply_markup=kb.settings_keyboard(digest_time, notif_on))


@router.callback_query(F.data == "set:notif")
async def cb_toggle_notif(cb: CallbackQuery, db: SheetsDB, user: User):
    if not await _guard(cb, user):
        return
    cur = await db.setting_get("notifications_enabled", "1")
    new_val = "0" if cur != "0" else "1"
    await db.setting_set("notifications_enabled", new_val)
    await cb.answer(f"Уведомления {'включены' if new_val == '1' else 'выключены'}")
    digest_time = await db.setting_get("digest_time", "09:00")
    await cb.message.answer(
        f"🔔 Уведомления: {'включены' if new_val == '1' else 'выключены'}",
        reply_markup=kb.settings_keyboard(digest_time, new_val != "0"))


@router.callback_query(F.data == "set:dtime")
async def cb_set_time(cb: CallbackQuery, state: FSMContext, user: User):
    if not await _guard(cb, user):
        return
    await cb.answer()
    await state.set_state(SetStates.waiting_time)
    await cb.message.answer(
        "⏰ Отправьте время ежедневного дайджеста в формате ЧЧ:ММ\n(например 09:00). Часовой пояс: UTC+5.",
        reply_markup=kb.simple_cancel_keyboard("set", "⬅ Назад"))


@router.message(StateFilter(SetStates.waiting_time), F.text)
async def msg_set_time(message: Message, state: FSMContext, db: SheetsDB):
    m = TIME_RE.match(message.text.strip())
    if not m:
        await message.answer("Формат ЧЧ:ММ, например 09:30. Попробуйте еще раз:")
        return
    hhmm = f"{int(m.group(1)):02d}:{m.group(2)}"
    try:
        await db.setting_set("digest_time", hhmm)
    except Exception:
        log.exception("setting digest_time failed")
        from bot.texts import SAVE_FAILED
        await message.answer(SAVE_FAILED)
        return
    await state.clear()
    await message.answer(f"✅ Время дайджеста: {hhmm}")


# --------------------------------------------------------------------------
# Пользователи и доступы
# --------------------------------------------------------------------------

def _users_keyboard(users: list[User], me_uid: int):
    b = InlineKeyboardBuilder()
    for u in users:
        role_title = ROLE_TITLES.get(u.role, u.role)
        b.button(text=f"{u.name or u.uid} — {role_title} (сменить роль)",
                 callback_data=f"urole:{u.uid}")
        if u.uid != me_uid:
            b.button(text=f"❌ Удалить {u.name or u.uid}", callback_data=f"udel:{u.uid}")
    b.row()
    b.button(text="➕ Добавить пользователя", callback_data="uadd")
    b.row()
    b.button(text="⬅ К настройкам", callback_data="set")
    b.adjust(1)
    return b.as_markup()


async def _render_users(cb: CallbackQuery, db: SheetsDB, auth: AuthService, user: User):
    users = await db.users_all()
    lines = ["👤 Пользователи бота:", ""]
    for u in users:
        notif = "🔔" if u.notifications else "🔕"
        lines.append(f"• <code>{u.uid}</code> — {u.name or 'без имени'} — "
                     f"{ROLE_TITLES.get(u.role, u.role)} {notif}")
    kb_m = _users_keyboard(users, user.uid)
    await cb.message.answer("\n".join(lines), reply_markup=kb_m)


@router.callback_query(F.data == "set:users")
async def cb_users(cb: CallbackQuery, db: SheetsDB, auth: AuthService, user: User):
    if not await _guard(cb, user):
        return
    await cb.answer()
    await _render_users(cb, db, auth, user)


@router.callback_query(F.data.startswith("urole:"))
async def cb_cycle_role(cb: CallbackQuery, db: SheetsDB, auth: AuthService, user: User):
    if not await _guard(cb, user):
        return
    uid = int(cb.data.split(":")[1])
    target = await db.user_find(uid)
    if not target:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    order = {"admin": "hr", "hr": "manager", "manager": "admin"}
    new_role = order.get(target.role, ROLE_MANAGER)
    await db.user_upsert(uid, target.name, new_role, target.notifications, added_by=user.name)
    auth.invalidate(uid)
    await cb.answer(f"Роль: {ROLE_TITLES[new_role]}")
    await _render_users(cb, db, auth, user)


@router.callback_query(F.data.startswith("udel:"))
async def cb_del_user(cb: CallbackQuery, db: SheetsDB, auth: AuthService, user: User):
    if not await _guard(cb, user):
        return
    uid = int(cb.data.split(":")[1])
    if uid == user.uid:
        await cb.answer("Нельзя удалить самого себя", show_alert=True)
        return
    ok = await db.user_delete(uid)
    auth.invalidate(uid)
    await cb.answer("Удален" if ok else "Не найден")
    await _render_users(cb, db, auth, user)


@router.callback_query(F.data == "uadd")
async def cb_add_user(cb: CallbackQuery, state: FSMContext, user: User):
    if not await _guard(cb, user):
        return
    await cb.answer()
    await state.set_state(SetStates.waiting_uid)
    await cb.message.answer("Отправьте Telegram ID нового пользователя (число):",
                            reply_markup=kb.simple_cancel_keyboard("set"))


@router.message(StateFilter(SetStates.waiting_uid), F.text)
async def msg_add_user_id(message: Message, state: FSMContext, db: SheetsDB):
    raw = message.text.strip().lstrip("+")
    if not raw.isdigit():
        await message.answer("ID должен быть числом. Попробуйте еще раз:")
        return
    uid = int(raw)
    existing = await db.user_find(uid)
    if existing:
        await state.update_data(new_uid=uid, new_name=existing.name)
        await message.answer(
            f"Пользователь {uid} уже есть ({ROLE_TITLES.get(existing.role)}). Выберите роль:",
            reply_markup=kb.roles_keyboard("uar:", "set"))
        await state.set_state(SetStates.waiting_role)
        return
    await state.update_data(new_uid=uid)
    await state.set_state(SetStates.waiting_uname)
    await message.answer("Введите имя пользователя (для списка):")


@router.message(StateFilter(SetStates.waiting_uname), F.text)
async def msg_add_user_name(message: Message, state: FSMContext):
    await state.update_data(new_name=message.text.strip()[:64])
    await state.set_state(SetStates.waiting_role)
    await message.answer("Выберите роль:", reply_markup=kb.roles_keyboard("uar:", "set"))


@router.callback_query(F.data.startswith("uar:"))
async def cb_pick_role(cb: CallbackQuery, state: FSMContext, db: SheetsDB,
                       auth: AuthService, user: User):
    if not await _guard(cb, user):
        return
    data = await state.get_data()
    uid = data.get("new_uid")
    name = data.get("new_name", "")
    if uid is None:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    role = cb.data.split(":")[1]
    await db.user_upsert(uid, name, role, notifications=True, added_by=user.name)
    auth.invalidate(uid)
    await state.clear()
    await cb.answer(f"Добавлен: {ROLE_TITLES[role]}")
    await cb.message.answer(f"✅ Пользователь <code>{uid}</code> добавлен с ролью «{ROLE_TITLES[role]}».")
    await _render_users(cb, db, auth, user)


# --------------------------------------------------------------------------
# Справочники
# --------------------------------------------------------------------------

@router.callback_query(F.data == "set:dicts")
async def cb_dicts(cb: CallbackQuery, user: User):
    if not await _guard(cb, user):
        return
    await cb.answer()
    b = InlineKeyboardBuilder()
    for i, title in enumerate(DICT_COLUMNS):
        b.button(text=title, callback_data=f"dcat:{i}")
    b.row()
    b.button(text="⬅ К настройкам", callback_data="set")
    b.adjust(1)
    await cb.message.answer("📚 Справочники — выберите список:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("dcat:"))
async def cb_dict_view(cb: CallbackQuery, db: SheetsDB, user: User):
    if not await _guard(cb, user):
        return
    idx = int(cb.data.split(":")[1])
    dicts = await db.dicts()
    values = [dicts.departments, dicts.positions, dicts.branches,
              dicts.supervisors, dicts.reasons][idx]
    listing = "\n".join(f"{i}. {v}" for i, v in enumerate(values, 1)) or "(пусто)"
    b = InlineKeyboardBuilder()
    b.button(text="➕ Добавить значение", callback_data=f"dadd:{idx}")
    b.row()
    b.button(text="⬅ К справочникам", callback_data="set:dicts")
    await cb.answer()
    await cb.message.answer(f"<b>{DICT_COLUMNS[idx]}</b>:\n\n{listing}",
                            reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("dadd:"))
async def cb_dict_add(cb: CallbackQuery, state: FSMContext, user: User):
    if not await _guard(cb, user):
        return
    idx = int(cb.data.split(":")[1])
    await state.set_state(SetStates.waiting_dict_value)
    await state.update_data(dict_idx=idx)
    await cb.answer()
    await cb.message.answer(f"Введите новое значение для «{DICT_COLUMNS[idx]}»:",
                            reply_markup=kb.simple_cancel_keyboard("set:dicts"))


@router.message(StateFilter(SetStates.waiting_dict_value), F.text)
async def msg_dict_value(message: Message, state: FSMContext, db: SheetsDB):
    data = await state.get_data()
    idx = data["dict_idx"]
    value = message.text.strip()[:80]
    try:
        await db.dict_append(idx, value)
    except Exception:
        log.exception("dict append failed")
        from bot.texts import SAVE_FAILED
        await message.answer(SAVE_FAILED)
        return
    await state.clear()
    await message.answer(f"✅ Добавлено в «{DICT_COLUMNS[idx]}»: {value}")
