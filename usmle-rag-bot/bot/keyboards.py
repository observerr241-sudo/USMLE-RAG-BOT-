"""All InlineKeyboardMarkup builders. Every callback_data is well under Telegram's 64-byte limit."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

from bot.catalog import FIRST_AID_CATALOG

LETTERS = "ABCDE"


def main_menu_kb() -> Kb:
    return Kb(inline_keyboard=[[Btn(text="🩺 USMLE Part 1 Practice", callback_data="menu:topics")]])


def access_request_kb() -> Kb:
    return Kb(inline_keyboard=[[Btn(text="📩 Submit Payment / Request Access", callback_data="req_access")]])


def topics_kb() -> Kb:
    rows: list[list[Btn]] = []
    row: list[Btn] = []
    for t_id, t in FIRST_AID_CATALOG.items():
        row.append(Btn(text=t["short"], callback_data=f"top:{t_id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return Kb(inline_keyboard=rows)


def subtopics_kb(t_id: int) -> Kb:
    rows = [
        [Btn(text=name, callback_data=f"sub:{t_id}:{s_id}")]
        for s_id, name in FIRST_AID_CATALOG[t_id]["subtopics"].items()
    ]
    rows.append([Btn(text="⬅️ Back to Topics", callback_data="menu:topics")])
    return Kb(inline_keyboard=rows)


def count_kb(t_id: int, s_id: int) -> Kb:
    return Kb(inline_keyboard=[
        [Btn(text=str(n), callback_data=f"cnt:{t_id}:{s_id}:{n}") for n in (10, 15, 20)],
        [Btn(text="⬅️ Back to Subtopics", callback_data=f"top:{t_id}")],
    ])


def question_kb(i: int) -> Kb:
    return Kb(inline_keyboard=[[Btn(text=L, callback_data=f"ans:{i}:{idx}") for idx, L in enumerate(LETTERS)]])


def after_answer_kb(i: int, total: int, show_explain: bool = True) -> Kb:
    nxt = (
        Btn(text="🏁 View Final Score", callback_data="finish")
        if i + 1 >= total
        else Btn(text="Next Question ➡️", callback_data=f"nxt:{i + 1}")
    )
    row = ([Btn(text="Explain", callback_data=f"exp:{i}")] if show_explain else []) + [nxt]
    return Kb(inline_keyboard=[row])


def final_kb() -> Kb:
    return Kb(inline_keyboard=[[Btn(text="🔄 Practice Another Subtopic", callback_data="menu:topics")]])


def admin_decision_kb(user_id: int) -> Kb:
    return Kb(inline_keyboard=[[
        Btn(text="✅ Approve 30 Days", callback_data=f"adm_ok:{user_id}:30"),
        Btn(text="❌ Reject", callback_data=f"adm_no:{user_id}"),
    ]])
