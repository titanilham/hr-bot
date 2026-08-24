"""Add-employee wizard with preview."""

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import bot.keyboards as kb
from bot.handlers.employees import card_text, find_emp
from bot.models import STATUS_ACTIVE, Employee, User
from bot.services.sheets import SheetsDB, SheetsUnavailable
from bot.texts import SAVE_FAILED
from bot.utils.dates import add_months, fmt_date, parse_date

log = logging.getLogger(__name__)
router = Router()

STEPS_TOTAL = 11


class AddEmp(StatesGroup):
    fio = State()
    phone = State()
    dept = State()
    pos = State()
    branch = State()
    supervisor = State()
    birthday = State()
    hire_date = State()
    probation = State()
    gender = State()
    comment = State()
    draft_edit = State()
    preview = State()


DICT_STEPS = {"dept": "Отдел", "pos": "Должность", "branch": "Филиал", "supervisor": "Руководитель"}


def _norm_phone(raw: str) -> str | None:
    digits = "".join(ch for ch in raw if ch.isdigit())
    raw2 = raw.strip().replace("(", "").replace(")", "").replace("-", "").replace(" ", "")
    if len(digits) < 10 or len(digits) > 13:
        return None
    return raw2


def preview_text(d: dict) -> str:
    proba = f"до {d.get('probation_end')}" if d.get("probation_end") else "без испытательного срока"
    lines = [
        "Проверьте данные:",
        "",
        f"ФИО: {d.get('fio', '—')}",
        f"Телефон: {d.get('phone', '—')}",
        f"Отдел: {d.get('dept', '—')}",
        f"Должность: {d.get('pos', '—')}",
        f"Филиал: {d.get('branch', '—')}",
        f"Руководитель: {d.get('supervisor') or '—'}",
        f"Дата рождения: {d.get('birthday', '—')}",
        f"Дата приема: {d.get('hire_date', '—')}",
        f"Испытательный срок: {proba}",
        f"Пол: {({'M': 'Мужской', 'F': 'Женский'}.get(d.get('gender'), '—'))}",
        f"Комментарий: {d.get('comment') or '—'}",
    ]
    return "\n".join(lines)


async def ask_step(cb_or_msg, state: FSMContext, step: str, db: SheetsDB, edit_mode=False):
    """Ask the next wizard question."""
    send = (lambda text, kb_=None: cb_or_msg.answer(text, reply_markup=kb_))
    prefix = "✏ Правим: " if edit_mode else f"Шаг {STEP_NUM[step]}/{STEPS_TOTAL} — "
    await state.set_state(STEP_STATES[step])

    if step in DICT_STEPS:
        dicts = await db.dicts()
        values = {
            "dept": dicts.departments,
            "pos": dicts.positions,
            "branch": dicts.branches,
            "supervisor": dicts.supervisors,
        }[step]
        title = DICT_STEPS[step]
        none_cb = "addd:supervisor:none" if step == "supervisor" else None
        markup = kb.dict_picker(f"addd:{step}", values, none_cb=none_cb)
        hint = "" if values else "\nСправочник пуст — напишите значение текстом."
        await send(f"{prefix}{title}:{hint}\nВыберите или введите:", markup)
    elif step == "probation":
        await send(f"{prefix}Испытательный срок:",
                   kb.choice_keyboard("addp", kb.PROBATION_OPTIONS))
    elif step == "gender":
        await send(f"{prefix}Пол:", kb.choice_keyboard("addg", kb.GENDER_OPTIONS))
    elif step == "comment":
        await send(f"{prefix}Комментарий (или нажмите «Пропустить»):",
                   kb.simple_cancel_keyboard("addskip_comment", "⏭ Пропустить"))
    elif step in ("birthday", "hire_date"):
        title = "Дата рождения" if step == "birthday" else "Дата приема"
        await send(f"{prefix}{title}\nФормат: ДД.ММ.ГГГГ",
                   kb.simple_cancel_keyboard("addcancel"))
    elif step == "fio":
        await send(f"{prefix}ФИО сотрудника:", kb.simple_cancel_keyboard("addcancel"))
    elif step == "phone":
        await send(f"{prefix}Телефон (например +7 XXX XXX XX XX):",
                   kb.simple_cancel_keyboard("addcancel"))


STEP_ORDER = ["fio", "phone", "dept", "pos", "branch", "supervisor",
              "birthday", "hire_date", "probation", "gender", "comment"]
STEP_NUM = {s: i + 1 for i, s in enumerate(STEP_ORDER)}
STEP_STATES = {
    "fio": AddEmp.fio,
    "phone": AddEmp.phone,
    "dept": AddEmp.dept,
    "pos": AddEmp.pos,
    "branch": AddEmp.branch,
    "supervisor": AddEmp.supervisor,
    "birthday": AddEmp.birthday,
    "hire_date": AddEmp.hire_date,
    "probation": AddEmp.probation,
    "gender": AddEmp.gender,
    "comment": AddEmp.comment,
}


async def advance(message: Message, state: FSMContext, db: SheetsDB, done_from: str):
    data = await state.get_data()
    draft = data.get("draft", {})
    idx = STEP_ORDER.index(done_from)
    nxt = STEP_ORDER[idx + 1]
    await state.update_data(draft=draft)
    await ask_step(message, state, nxt, db)



@router.callback_query(F.data == "add")
async def cb_add(cb: CallbackQuery, state: FSMContext, db: SheetsDB, user: User):
    if not user.is_full_access:
        await cb.answer("⛔ Недостаточно прав", show_alert=True)
        return
    await cb.answer()
    await state.clear()
    await state.update_data(draft={})
    await ask_step(cb.message, state, "fio", db)


@router.callback_query(F.data == "addcancel")
async def cb_add_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Отменено")
    await cb.message.answer("❌ Добавление отменено.")



def _save_and_next(cb: CallbackQuery, state: FSMContext, db, key: str, value: str):
    async def run():
        data = await state.get_data()
        draft = data.get("draft", {})
        draft[key] = value
        await state.update_data(draft=draft)
        await cb.answer()
        await advance(cb.message, state, db, key)
    return run()


@router.callback_query(StateFilter(AddEmp.dept, AddEmp.pos, AddEmp.branch, AddEmp.supervisor),
                       F.data.startswith("addd:"))
async def cb_add_dict_pick(cb: CallbackQuery, state: FSMContext, db: SheetsDB):
    _, key, val = cb.data.split(":")
    if val == "manual":
        await cb.message.answer("✍️ Введите значение текстом:")
        await cb.answer()
        return
    if key == "supervisor" and val == "none":
        await _save_and_next(cb, state, db, "supervisor", "")
        return
    dicts = await db.dicts()
    values = {"dept": dicts.departments, "pos": dicts.positions,
              "branch": dicts.branches, "supervisor": dicts.supervisors}[key]
    value = values[int(val)]
    await _save_and_next(cb, state, db, key, value)


@router.callback_query(StateFilter(AddEmp.probation), F.data.startswith("addp:"))
async def cb_add_probation(cb: CallbackQuery, state: FSMContext, db: SheetsDB):
    _, opt = cb.data.split(":")
    data = await state.get_data()
    draft = data.get("draft", {})
    hire = parse_date(draft.get("hire_date", "")) or date.today()
    mapping = {"m1": add_months(hire, 1), "m2": add_months(hire, 2), "m3": add_months(hire, 3)}
    if opt == "manual":
        await cb.message.answer("Введите дату окончания ДД.ММ.ГГГГ:")
        await cb.answer()
        return
    if opt == "none":
        draft["probation_end"] = ""
        await state.update_data(draft=draft)
        await cb.answer()
        await advance(cb.message, state, db, "probation")
        return
    draft["probation_end"] = fmt_date(mapping[opt])
    await state.update_data(draft=draft)
    await cb.answer()
    await advance(cb.message, state, db, "probation")


@router.callback_query(StateFilter(AddEmp.gender), F.data.startswith("addg:"))
async def cb_add_gender(cb: CallbackQuery, state: FSMContext, db: SheetsDB):
    _, val = cb.data.split(":")
    await _save_and_next(cb, state, db, "gender", val)


@router.callback_query(F.data == "addskip_comment")
async def cb_add_skip_comment(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await goto_preview(cb.message, state)



@router.message(StateFilter(AddEmp.fio), F.text)
async def msg_fio(message: Message, state: FSMContext, db: SheetsDB):
    raw = message.text.strip()
    if len(raw) < 3 or len(raw.split()) < 2:
        await message.answer("Введите ФИО полностью (минимум имя и фамилию):")
        return
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["fio"] = raw.title()
    await state.update_data(draft=draft)
    await advance(message, state, db, "fio")


@router.message(StateFilter(AddEmp.phone), F.text)
async def msg_phone(message: Message, state: FSMContext, db: SheetsDB):
    phone = _norm_phone(message.text.strip())
    if not phone:
        await message.answer("Телефон должен содержать минимум 10 цифр. Попробуйте еще раз:")
        return
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["phone"] = phone
    await state.update_data(draft=draft)
    await advance(message, state, db, "phone")


@router.message(StateFilter(AddEmp.birthday), F.text)
async def msg_bday(message: Message, state: FSMContext, db: SheetsDB):
    d = parse_date(message.text.strip())
    today = date.today()
    if not d or not (date(1930, 1, 1) <= d <= today):
        await message.answer("Некорректная дата. Введите ДД.ММ.ГГГГ (не в будущем):")
        return
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["birthday"] = fmt_date(d)
    await state.update_data(draft=draft)
    await advance(message, state, db, "birthday")


@router.message(StateFilter(AddEmp.hire_date), F.text)
async def msg_hire(message: Message, state: FSMContext, db: SheetsDB):
    d = parse_date(message.text.strip())
    if not d or d > date.today():
        await message.answer("Дата приема не может быть в будущем. Введите ДД.ММ.ГГГГ:")
        return
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["hire_date"] = fmt_date(d)
    await state.update_data(draft=draft)
    await advance(message, state, db, "hire_date")


@router.message(StateFilter(AddEmp.probation), F.text)
async def msg_proba(message: Message, state: FSMContext, db: SheetsDB):
    d = parse_date(message.text.strip())
    data = await state.get_data(); draft = data.setdefault("draft", {})
    hire = parse_date(draft.get("hire_date", ""))
    if not d or (hire and d < hire):
        await message.answer("Дата окончания должна быть не раньше даты приема. Введите ДД.ММ.ГГГГ:")
        return
    draft["probation_end"] = fmt_date(d)
    await state.update_data(draft=draft)
    await advance(message, state, db, "probation")


@router.message(StateFilter(AddEmp.comment), F.text)
async def msg_comment(message: Message, state: FSMContext):
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["comment"] = message.text.strip()
    await state.update_data(draft=draft)
    await goto_preview(message, state)


# manual input fallback for dict steps
@router.message(StateFilter(AddEmp.dept), F.text)
async def msg_dept(message: Message, state: FSMContext, db: SheetsDB):
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["dept"] = message.text.strip()
    await state.update_data(draft=draft)
    await advance(message, state, db, "dept")


@router.message(StateFilter(AddEmp.pos), F.text)
async def msg_pos(message: Message, state: FSMContext, db: SheetsDB):
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["pos"] = message.text.strip()
    await state.update_data(draft=draft)
    await advance(message, state, db, "pos")


@router.message(StateFilter(AddEmp.branch), F.text)
async def msg_branch(message: Message, state: FSMContext, db: SheetsDB):
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["branch"] = message.text.strip()
    await state.update_data(draft=draft)
    await advance(message, state, db, "branch")


@router.message(StateFilter(AddEmp.supervisor), F.text)
async def msg_sup(message: Message, state: FSMContext, db: SheetsDB):
    data = await state.get_data(); draft = data.setdefault("draft", {})
    draft["supervisor"] = message.text.strip()
    await state.update_data(draft=draft)
    await advance(message, state, db, "supervisor")



async def goto_preview(message: Message, state: FSMContext):
    data = await state.get_data()
    draft = data.get("draft", {})
    missing = [t for k, t in (("fio", "ФИО"), ("phone", "Телефон"),
                              ("birthday", "Дата рождения"), ("hire_date", "Дата приема"))
               if not draft.get(k)]
    if missing:
        await message.answer("Не заполнены обязательные поля: " + ", ".join(missing))
        return
    await state.set_state(AddEmp.preview)
    await message.answer(preview_text(draft), reply_markup=kb.preview_keyboard())


@router.callback_query(StateFilter(AddEmp.preview), F.data == "addedit")
async def cb_preview_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("Какое поле изменить?", reply_markup=kb.draft_edit_keyboard())


@router.callback_query(F.data.startswith("dft:"))
async def cb_draft_edit_field(cb: CallbackQuery, state: FSMContext):
    _, field = cb.data.split(":")
    if field not in kb.ADD_DRAFT_FIELDS:
        await cb.answer()
        return
    await state.set_state(AddEmp.draft_edit)
    await state.update_data(edit_field=field)
    await cb.answer()
    title = kb.ADD_DRAFT_FIELDS[field]
    hint = "\nФормат: ДД.ММ.ГГГГ" if field in ("birthday", "hire_date", "probation_end") else ""
    await cb.message.answer(f"✏ {title}. Введите новое значение{hint}:",
                            reply_markup=kb.simple_cancel_keyboard("addedit_back"))


@router.callback_query(F.data == "addedit_back")
async def cb_draft_edit_back(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await goto_preview(cb.message, state)


@router.message(StateFilter(AddEmp.draft_edit), F.text)
async def msg_draft_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field, raw = data["edit_field"], message.text.strip()
    draft = data.get("draft", {})
    if field in ("birthday", "hire_date", "probation_end"):
        if raw == "-":
            raw = ""
        else:
            d = parse_date(raw)
            if not d:
                await message.answer("Не понял дату. Введите ДД.ММ.ГГГГ:")
                return
            raw = fmt_date(d)
    draft[field] = raw
    await state.update_data(draft=draft)
    await goto_preview(message, state)


@router.callback_query(StateFilter(AddEmp.preview), F.data == "addsave")
async def cb_preview_save(cb: CallbackQuery, state: FSMContext, db: SheetsDB, user: User):
    data = await state.get_data()
    draft = data.get("draft", {})
    try:
        eid = await db.next_emp_id()
        emp = Employee(
            eid=eid,
            fio=draft.get("fio", ""), phone=draft.get("phone", ""),
            gender={"M": "М", "F": "Ж"}.get(draft.get("gender"), ""),
            dept=draft.get("dept", ""), pos=draft.get("pos", ""),
            branch=draft.get("branch", ""), supervisor=draft.get("supervisor", ""),
            birthday=draft.get("birthday", ""), hire_date=draft.get("hire_date", ""),
            probation_end=draft.get("probation_end", ""),
            status=STATUS_ACTIVE, comment=draft.get("comment", ""),
            created_at=fmt_date(date.today()), created_by=user.name,
        )
        await db.append_employee(emp)
        await db.add_history(eid, emp.fio, fmt_date(date.today()), "принятие на работу",
                             "", f"{emp.pos} / {emp.dept}", "", user.name)
    except SheetsUnavailable:
        log.exception("Sheets unavailable on save employee")
        await cb.message.answer(SAVE_FAILED)
        return
    await state.clear()
    await cb.answer("Сохранено ✅")
    saved = await find_emp(db, eid)
    await cb.message.answer(
        f"✅ Сотрудник сохранен.\nПрисвоен ID: <code>{eid}</code>",
    )
    if saved:
        await cb.message.answer(card_text(saved, date.today()),
                                reply_markup=kb.card_keyboard(eid, user.is_full_access))
