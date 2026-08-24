"""Регистрация всех роутеров. Порядок важен: start первым."""

from aiogram import Router

from . import (
    add_employee,
    dismissal,
    employees,
    events,
    report,
    search,
    settings,
    start,
    transfer,
)


def all_routers() -> list[Router]:
    return [
        start.router,
        settings.router,
        report.router,
        events.router,
        search.router,
        transfer.router,
        dismissal.router,
        add_employee.router,
        employees.router,
    ]
