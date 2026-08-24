"""Команды /start, /help, /id и возврат в главное меню."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import CB_MENU, main_menu
from bot.models import ROLE_TITLES, User

router = Router()

WELCOME = "👋 Добро пожаловать в HR-бот!\nВыберите раздел:"


def menu_text() -> str:
    return WELCOME


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message, state: FSMContext, user: User):
    await state.clear()
    await message.answer(menu_text(), reply_markup=main_menu(user.is_full_access))


@router.message(Command("id"))
async def cmd_id(message: Message, user: User):
    await message.answer(
        f"Ваш Telegram ID: <code>{user.uid}</code>\n"
        f"Роль: {ROLE_TITLES.get(user.role, user.role)}"
    )


@router.callback_query(F.data == CB_MENU)
async def cb_menu(cb: CallbackQuery, state: FSMContext, user: User):
    await state.clear()
    await cb.answer()
    await cb.message.answer(menu_text(), reply_markup=main_menu(user.is_full_access))


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()
