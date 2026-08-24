"""Доменная модель: сотрудник, пользователь, справочники."""

from dataclasses import dataclass, field
from datetime import date

from bot.utils.dates import diff_ymd, parse_date, plural

STATUS_ACTIVE = "Работает"
STATUS_FIRED = "Уволен"

ROLE_ADMIN = "admin"
ROLE_HR = "hr"
ROLE_MANAGER = "manager"
ROLE_TITLES = {
    ROLE_ADMIN: "Администратор",
    ROLE_HR: "HR",
    ROLE_MANAGER: "Руководитель",
}

# Порядок колонок листа «Сотрудники» (по ТЗ; добавлена колонка «Филиал»,
# которая нужна для карточки и фильтров по филиалам).
EMPLOYEE_COLUMNS = [
    "ID", "ФИО", "Телефон", "Пол", "Отдел", "Должность", "Филиал",
    "Руководитель", "Дата рождения", "Дата приема",
    "Дата окончания испытательного срока", "Дата увольнения",
    "Статус", "Комментарий", "Дата создания записи", "Кто внес запись",
]

HISTORY_COLUMNS = [
    "ID сотрудника", "ФИО", "Дата изменения", "Тип изменения",
    "Старое значение", "Новое значение", "Комментарий", "Кто внес изменение",
]

DISMISSAL_COLUMNS = [
    "ID", "ФИО", "Должность", "Отдел", "Филиал", "Дата приема",
    "Дата увольнения", "Причина увольнения", "Комментарий", "Кто оформил увольнение",
]

EVENT_COLUMNS = [
    "Дата отправки", "Тип события", "Ключ события", "ID сотрудника",
    "ФИО", "Описание", "Кому отправлено", "Время отправки",
]

DICT_COLUMNS = ["Отделы", "Должности", "Филиалы", "Руководители", "Причины увольнения"]

USER_COLUMNS = ["Telegram ID", "Имя", "Роль", "Уведомления", "Дата добавления", "Кем добавлен"]

SETTINGS_COLUMNS = ["Ключ", "Значение"]

DEFAULT_REASONS = [
    "По собственному желанию",
    "По инициативе компании",
    "Сокращение",
    "Окончание договора",
    "Не прошел испытательный срок",
    "Другая причина",
]


@dataclass
class Employee:
    eid: str = ""
    fio: str = ""
    phone: str = ""
    gender: str = ""
    dept: str = ""
    pos: str = ""
    branch: str = ""
    supervisor: str = ""
    birthday: str = ""   # ДД.ММ.ГГГГ
    hire_date: str = ""
    probation_end: str = ""
    fire_date: str = ""
    status: str = STATUS_ACTIVE
    comment: str = ""
    created_at: str = ""
    created_by: str = ""
    row: int | None = None  # номер строки в таблице

    # -- Парсинг/сериализация -------------------------------------------------

    @classmethod
    def from_row(cls, row: list[str], row_num: int) -> "Employee":
        def g(i: int) -> str:
            return row[i].strip() if i < len(row) else ""

        return cls(
            eid=g(0), fio=g(1), phone=g(2), gender=g(3), dept=g(4), pos=g(5),
            branch=g(6), supervisor=g(7), birthday=g(8), hire_date=g(9),
            probation_end=g(10), fire_date=g(11),
            status=g(12) or STATUS_ACTIVE, comment=g(13),
            created_at=g(14), created_by=g(15), row=row_num,
        )

    def to_row(self) -> list[str]:
        return [
            self.eid, self.fio, self.phone, self.gender, self.dept, self.pos,
            self.branch, self.supervisor, self.birthday, self.hire_date,
            self.probation_end, self.fire_date, self.status, self.comment,
            self.created_at, self.created_by,
        ]

    # -- Производные значения -------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status != STATUS_FIRED

    def on_probation(self, today: date) -> bool:
        end = parse_date(self.probation_end)
        return self.is_active and end is not None and today <= end

    def bday_date(self) -> date | None:
        return parse_date(self.birthday)

    def hire(self) -> date | None:
        return parse_date(self.hire_date)

    def tenure(self, today: date) -> str:
        h = self.hire()
        if not h:
            return ""
        y, m, d = diff_ymd(h, today)
        parts = []
        if y:
            parts.append(f"{y} {plural(y, 'год', 'года', 'лет')}")
        if m:
            parts.append(f"{m} {plural(m, 'месяц', 'месяца', 'месяцев')}")
        if d or not parts:
            parts.append(f"{d} {plural(d, 'день', 'дня', 'дней')}")
        return " ".join(parts)

    def status_label(self, today: date) -> str:
        if not self.is_active:
            return STATUS_FIRED
        return "На испытательном сроке" if self.on_probation(today) else STATUS_ACTIVE


@dataclass
class User:
    uid: int
    name: str = ""
    role: str = ROLE_MANAGER
    notifications: bool = True

    @property
    def is_full_access(self) -> bool:
        return self.role in (ROLE_ADMIN, ROLE_HR)


@dataclass
class Dicts:
    departments: list[str] = field(default_factory=list)
    positions: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    supervisors: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
