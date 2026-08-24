"""Employee search; also picks employees for transfer/dismissal."""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()

MODE_PROMPTS = {
    "search": "🔎 Введите ФИО, телефон, должность или отдел:",
    "transfer": "🔄 Введите ФИО сотрудника для перевода:",
    "fire": "👋 Введите ФИО сотрудника, которого нужно уволить:",
}
LIMIT = 25


class Search(StatesGroup):
    waiting_query = State()


def _start_search(cb: CallbackQuery, state: FSMContext, mode: str):
    from bot.keyboards import simple_cancel_keyboard
    cb_data = {"search": "emp", "transfer": "menu", "fire": "menu"}[mode]
    return _do_start(cb, state, mode, cb_data)


async def _do_start(cb: CallbackQuery, state: FSMContext, mode: str, back_cb: str):
    from bot.keyboards import simple_cancel_keyboard
    await state.set_state(Search.waiting_query)
    await state.update_data(mode=mode)
    await cb.answer()
    await cb.message.answer(MODE_PROMPTS[mode],
                            reply_markup=simple_cancel_keyboard(back_cb, "⬅ Назад"))


@router.callback_query(F.data == "srch")
async def cb_srch(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await _start_search(cb, state, "search")


@router.callback_query(F.data == "srchagain")
async def cb_srch_again(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await _start_search(cb, state, data.get("mode", "search"), data.get("back", "emp"))


@router.message(StateFilter(Search.waiting_query), F.text)
async def msg_search(message: Message, state: FSMContext, db):
    from bot.keyboards import CB_MENU, employees_filters

    query = message.text.strip().lower()
    if len(query) < 2:
        await message.answer("Слишком короткий запрос. Введите минимум 2 символа:")
        return
    data = await state.get_data()
    mode = data.get("mode", "search")

    emps = await db.get_employees(fresh=True)
    if mode in ("transfer", "fire"):
        emps = [e for e in emps if e.is_active]

    fields = ("fio", "phone", "pos", "dept")
    hits = [e for e in emps
            if any(query in (getattr(e, f) or "").lower() for f in fields)]
    hits.sort(key=lambda e: e.fio.lower())
    truncated = len(hits) > LIMIT
    hits = hits[:LIMIT]

    if not hits:
        kb_b = InlineKeyboardBuilder()
        kb_b.button(text="🔁 Искать еще раз", callback_data="srchagain")
        kb_b.button(text="⬅ В меню", callback_data=CB_MENU)
        kb_b.adjust(1)
        await message.answer("Никого не найдено.", reply_markup=kb_b.as_markup())
        return

    lines = [f"Найдено: {len(hits)}" + (" (показаны первые)" if truncated else ""), ""]
    ikb = InlineKeyboardBuilder()
    for i, e in enumerate(hits, 1):
        place = e.branch or e.dept
        lines.append(f"{i}. {e.fio} — {e.pos or '—'}" + (f" — {place}" if place else ""))
        target = {"search": f"card:{e.eid}", "transfer": f"xfer:{e.eid}", "fire": f"fire:{e.eid}"}[mode]
        ikb.button(text=f"{i}. {e.fio}", callback_data=target)
    ikb.adjust(1)

    await message.answer("\n".join(lines), reply_markup=ikb.as_markup())
    await state.clear()


# entry points from transfer/dismissal menus override these
@router.callback_query(F.data == "xferpick")
async def cb_xfer_pick(cb: CallbackQuery, state: FSMContext):
    from bot.keyboards import CB_MENU
    await state.clear()
    await _do_start(cb, state, "transfer", CB_MENU)


@router.callback_query(F.data == "firepick")
async def cb_fire_pick(cb: CallbackQuery, state: FSMContext):
    from bot.keyboards import CB_MENU
    await state.clear()
    await _do_start(cb, state, "fire", CB_MENU)
