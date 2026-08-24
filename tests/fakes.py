"""Fake gspread/aiogram objects for network-free tests."""

import re


def _letters_to_num(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


class FakeWorksheet:
    """Минимальная имитация gspread.Worksheet поверх списка строк."""

    def __init__(self, title: str):
        self.title = title
        self.values: list[list[str]] = []

    def get_all_values(self) -> list[list[str]]:
        return [list(r) for r in self.values]

    def append_row(self, vals, value_input_option=None):
        self.values.append([str(v) for v in vals])

    def update(self, values, range_name=None):
        range_name = range_name or "A1"
        m = re.search(r"(\d+)", range_name)
        start_row = int(m.group(1)) if m else 1
        m_letters = re.match(r"[A-Za-z]+", range_name)
        col_start = _letters_to_num(m_letters.group(0)) if m_letters else 1
        for i, row in enumerate(values):
            r_i = start_row - 1 + i
            while len(self.values) <= r_i:
                self.values.append([])
            row_vals = [str(v) for v in row]
            target = self.values[r_i]
            need = col_start - 1 + len(row_vals)
            while len(target) < need:
                target.append("")
            target[col_start - 1: col_start - 1 + len(row_vals)] = row_vals

    def update_cell(self, row, col, val):
        while len(self.values) < row:
            self.values.append([])
        t = self.values[row - 1]
        while len(t) < col:
            t.append("")
        t[col - 1] = str(val)

    def delete_rows(self, idx):
        if 1 <= idx <= len(self.values):
            del self.values[idx - 1]


class FakeSpreadsheet:
    def __init__(self):
        self._sheets: dict[str, FakeWorksheet] = {}

    def worksheets(self):
        return list(self._sheets.values())

    def add_worksheet(self, title, rows=0, cols=0):
        ws = FakeWorksheet(title)
        self._sheets[title] = ws
        return ws


class FakeBot:
    """Ловит отправленные сообщения вместо Telegram API."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.sent.append((chat_id, text))
        return True
