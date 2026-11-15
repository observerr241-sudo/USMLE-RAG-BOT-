"""Student flow: /start -> auth gate -> topic -> subtopic -> 10/15/20 -> quiz with Explain."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot import config, database as dbm, gemini_router
from bot.catalog import FIRST_AID_CATALOG, get_subtopic_name, get_topic
from bot.keyboards import (
    LETTERS, access_request_kb, admin_decision_kb, after_answer_kb, count_kb, final_kb,
    main_menu_kb, question_kb, subtopics_kb, topics_kb,
)

logger = logging.getLogger(__name__)
router = Router(name="user_quiz")

_generating: set[int] = set()          # users with a generation in flight
_last_request: dict[int, float] = {}   # payment-request cooldown


class PaymentFlow(StatesGroup):
    waiting_for_payment_note = State()


# --------------------------------------------------------------------------- helpers
def _plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


async def safe_edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """edit_text that tolerates 'not modified' and falls back to plain text on HTML/length problems."""
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        logger.warning("edit_text failed (%s); falling back to plain text", exc)
        try:
            await cb.message.edit_text(_plain(text)[:4000], reply_markup=kb, parse_mode=None)
        except TelegramBadRequest as exc2:
            if "not modified" not in str(exc2).lower():
                raise


async def safe_send(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Send a brand-new message so previous MCQs stay visible in chat history."""
    if cb.message is None:
        return
    try:
        await cb.message.answer(text, reply_markup=kb)
    except TelegramBadRequest as exc:
        logger.warning("answer failed (%s); falling back to plain text", exc)
        await cb.message.answer(_plain(text)[:4000], reply_markup=kb, parse_mode=None)


def gate_text(telegram_id: int, reason: str) -> str:
    text = (
        "\U0001f512 <b>Access Restricted \u2014 Paid Subscribers Only</b>\n\n"
        f"\U0001f194 Your Telegram ID: <code>{telegram_id}</code>\n"
        f"\U0001f4cc Status: <b>{html.escape(reason)}</b>\n\n"
        f"To unlock full USMLE Step 1 Practice ({html.escape(config.PRICE_TEXT)}), complete your payment and tap the "
        "button below to send your Transaction ID (TrxID) or payment details to the Admin."
    )
    if config.PAYMENT_INSTRUCTIONS:
        text += f"\n\n\U0001f4b3 <b>Pay to:</b> {html.escape(config.PAYMENT_INSTRUCTIONS)}"
    return text


async def deny(event: Message | CallbackQuery, reason: str) -> None:
    text = gate_text(event.from_user.id, reason)
    if isinstance(event, CallbackQuery):
        await event.answer()
        await safe_edit(event, text, access_request_kb())
    else:
        await event.answer(text, reply_markup=access_request_kb())


async def check_auth(event: Message | CallbackQuery) -> tuple[bool, str]:
    ok, info = await dbm.is_user_authorized(event.from_user.id)
    if not ok:
        await deny(event, info)
    return ok, info


# --------------------------------------------------------------------------- question rendering
def render_question(session: dict, i: int) -> str:
    q = session["questions"][i]
    opts = "\n".join(f"<b>{LETTERS[k]}.</b> {html.escape(o)}" for k, o in enumerate(q["options"]))
    return (
        f"<b>Question {i + 1}/{session['total_questions']} \u2022 "
        f"{html.escape(session['topic'])}: {html.escape(session['subtopic'])}</b>\n\n"
        f"{html.escape(q['question_description'])}\n\n{opts}"
    )


def render_result(session: dict, i: int) -> str:
    q = session["questions"][i]
    chosen = int(session["chosen"][str(i)])
    ci = q["correct_answer_index"]
    if chosen == ci:
        return f"\n\n\u2705 <b>Correct! (You chose {q['correct_option']}: {html.escape(q['options'][ci])})</b>"
    return (
        f"\n\n\u274c <b>Incorrect. You chose {LETTERS[chosen]} ({html.escape(q['options'][chosen])}) | "
        f"Correct Answer: {q['correct_option']} ({html.escape(q['options'][ci])})</b>"
    )


def render_explanation(session: dict, i: int) -> str:
    return f"\n\n\U0001f4d6 <b>Explanation:</b>\n{html.escape(session['questions'][i]['explanation'])}"


# --------------------------------------------------------------------------- /start + subscription request
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    ok, info = await check_auth(message)
    if not ok:
        return
    name = html.escape(message.from_user.first_name or "Doctor")
    status = "Admin access" if info == "Admin Access" else f"Active until <b>{info}</b>"
    await message.answer(
        f"\U0001f44b Welcome, <b>{name}</b>!\n\n"
        "This bot writes fresh NBME-style USMLE Step 1 questions from First Aid content, with a high-yield "
        f"explanation for every question.\n\n\u2705 Subscription: {status}",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "req_access")
async def cb_req_access(cb: CallbackQuery, state: FSMContext) -> None:
    ok, info = await dbm.is_user_authorized(cb.from_user.id)
    if ok:
        await cb.answer("Your subscription is already active \u2705", show_alert=True)
        return
    await cb.answer()
    await state.set_state(PaymentFlow.waiting_for_payment_note)
    await cb.message.answer(
        "\U0001f4e9 Send your <b>Transaction ID (TrxID)</b> or bKash number in <b>one message</b>.\n"
        "Send /cancel to abort."
    )


@router.message(Command("cancel"), PaymentFlow.waiting_for_payment_note)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled. Tap /start whenever you're ready.")


@router.message(PaymentFlow.waiting_for_payment_note, F.text)
async def got_payment_note(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id
    note = message.text.strip().splitlines()[0][:300] if message.text.strip() else ""
    if not note or note.startswith("/"):
        await message.answer("Please send your TrxID / bKash number as plain text (or /cancel).")
        return
    if time.monotonic() - _last_request.get(uid, 0) < 60:
        await message.answer("\u23f3 You just sent a request. Please wait a minute before sending another.")
        return
    _last_request[uid] = time.monotonic()

    u = message.from_user
    alert = (
        "\U0001f4b3 <b>New Payment / Access Request</b>\n\n"
        f"\U0001f464 {html.escape(u.full_name)}" + (f" (@{html.escape(u.username)})" if u.username else "") + "\n"
        f"\U0001f194 <code>{uid}</code>\n"
        f"\U0001f4dd Note: <code>{html.escape(note)}</code>"
    )
    delivered = 0
    for admin_id in config.ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, alert, reply_markup=admin_decision_kb(uid))
            delivered += 1
        except Exception as exc:
            logger.warning("Could not alert admin %s: %s", admin_id, exc)
    await state.clear()
    if delivered:
        await message.answer("\u2705 Sent to the Admin. You'll get a message here as soon as your access is approved.")
    else:
        await message.answer("\u26a0\ufe0f I couldn't reach the Admin automatically. Please contact them directly with your Telegram ID.")


# --------------------------------------------------------------------------- menu navigation
@router.callback_query(F.data == "menu:topics")
async def cb_topics(cb: CallbackQuery) -> None:
    ok, _ = await check_auth(cb)
    if not ok:
        return
    await cb.answer()
    await safe_edit(cb, "\U0001f4da <b>Select a USMLE Part 1 Topic:</b>", topics_kb())


def _parse(data: str, n: int) -> list[int] | None:
    parts = data.split(":")[1:]
    if len(parts) != n:
        return None
    try:
        return [int(p) for p in parts]
    except ValueError:
        return None


@router.callback_query(F.data.startswith("top:"))
async def cb_topic(cb: CallbackQuery) -> None:
    ok, _ = await check_auth(cb)
    if not ok:
        return
    p = _parse(cb.data, 1)
    topic = get_topic(p[0]) if p else None
    if not topic:
        await cb.answer("Unknown topic", show_alert=True)
        return
    await cb.answer()
    await safe_edit(cb, f"\U0001f4c2 Topic: <b>{html.escape(topic['name'])}</b>\nSelect a Subtopic:", subtopics_kb(p[0]))


@router.callback_query(F.data.startswith("sub:"))
async def cb_subtopic(cb: CallbackQuery) -> None:
    ok, _ = await check_auth(cb)
    if not ok:
        return
    p = _parse(cb.data, 2)
    topic = get_topic(p[0]) if p else None
    sub = get_subtopic_name(p[0], p[1]) if p else None
    if not topic or not sub:
        await cb.answer("Unknown subtopic", show_alert=True)
        return
    await cb.answer()
    await safe_edit(
        cb,
        f"\U0001f3af <b>{html.escape(topic['name'])} \u2014 {html.escape(sub)}</b>\n\nHow many MCQ you wanna practice?",
        count_kb(p[0], p[1]),
    )


# --------------------------------------------------------------------------- generation
@router.callback_query(F.data.startswith("cnt:"))
async def cb_count(cb: CallbackQuery) -> None:
    ok, _ = await check_auth(cb)
    if not ok:
        return
    p = _parse(cb.data, 3)
    if not p or p[2] not in (10, 15, 20) or not get_topic(p[0]) or not get_subtopic_name(p[0], p[1]):
        await cb.answer("Invalid selection", show_alert=True)
        return
    t_id, s_id, count = p
    uid = cb.from_user.id
    if uid in _generating:
        await cb.answer("Already generating your quiz \u2014 one moment \u23f3", show_alert=True)
        return

    await cb.answer()
    _generating.add(uid)
    topic = FIRST_AID_CATALOG[t_id]
    sub = topic["subtopics"][s_id]
    await safe_edit(
        cb,
        f"\u23f3 Generating {count} NBME-style USMLE Step 1 MCQs for <b>{html.escape(topic['name'])} ({html.escape(sub)})</b>...\n"
        "<i>Analyzing First Aid textbook chunks (~8\u201312 seconds)...</i>",
    )
    try:
        try:
            query = f"High-yield USMLE Step 1 testable facts, mechanisms and clinical associations: {topic['name']} \u2014 {sub}"
            q_emb: list[float] | None = await gemini_router.embed_query(query)
        except Exception as exc:
            logger.warning("Query embedding failed, using unranked chunks: %s", exc)
            q_emb = None

        context = await dbm.get_relevant_chunks(t_id, s_id, q_emb, limit=10)
        if not context:
            await safe_edit(
                cb,
                "\U0001f4ed No textbook content has been ingested for this topic yet. Please tell the Admin.",
                subtopics_kb(t_id),
            )
            return

        questions = await gemini_router.generate_mcqs(topic["name"], sub, count, context, topic["segment_group"])
        session = await dbm.create_session(uid, t_id, topic["name"], s_id, sub, questions)
        await dbm.increment_quizzes(uid)
        await safe_edit(cb, render_question(session, 0), question_kb(0))
    except Exception:
        logger.exception("Quiz generation failed for user %s", uid)
        await safe_edit(
            cb,
            "\u26a0\ufe0f Couldn't generate the quiz right now (the AI service is busy). Please try again in a minute.",
            count_kb(t_id, s_id),
        )
    finally:
        _generating.discard(uid)


# --------------------------------------------------------------------------- answering
async def _session_or_expired(cb: CallbackQuery) -> dict | None:
    session = await dbm.get_session(cb.from_user.id)
    if not session:
        await cb.answer("This quiz has expired. Start a new one.", show_alert=True)
        await safe_edit(cb, "\u231b This quiz has expired.", final_kb())
    return session


@router.callback_query(F.data.startswith("ans:"))
async def cb_answer(cb: CallbackQuery) -> None:
    ok, _ = await check_auth(cb)
    if not ok:
        return
    await cb.answer()
    p = _parse(cb.data, 2)
    session = await _session_or_expired(cb)
    if not p or not session:
        return
    i, choice = p
    total = session["total_questions"]
    if not (0 <= i < total and 0 <= choice <= 4):
        return
    q = session["questions"][i]
    first = await dbm.record_answer(cb.from_user.id, i, choice, choice == q["correct_answer_index"])
    if not first:
        session = await dbm.get_session(cb.from_user.id) or session
    else:
        session.setdefault("chosen", {})[str(i)] = choice
    if str(i) not in session.get("chosen", {}):
        return
    await safe_edit(cb, render_question(session, i) + render_result(session, i), after_answer_kb(i, total))


@router.callback_query(F.data.startswith("exp:"))
async def cb_explain(cb: CallbackQuery) -> None:
    ok, _ = await check_auth(cb)
    if not ok:
        return
    await cb.answer()
    p = _parse(cb.data, 1)
    session = await _session_or_expired(cb)
    if not p or not session:
        return
    i = p[0]
    total = session["total_questions"]
    if not (0 <= i < total) or str(i) not in session.get("chosen", {}):
        await cb.answer("Answer the question first.", show_alert=True)
        return
    base = render_question(session, i) + render_result(session, i)
    full = base + render_explanation(session, i)
    kb = after_answer_kb(i, total, show_explain=False)
    if len(full) <= 4000:
        await safe_edit(cb, full, kb)
    else:
        await cb.message.answer(render_explanation(session, i).strip())
        try:
            await cb.message.edit_reply_markup(reply_markup=kb)
        except TelegramBadRequest:
            pass


@router.callback_query(F.data.startswith("nxt:"))
async def cb_next(cb: CallbackQuery) -> None:
    ok, _ = await check_auth(cb)
    if not ok:
        return
    await cb.answer()
    p = _parse(cb.data, 1)
    session = await _session_or_expired(cb)
    if not p or not session:
        return
    n = p[0]
    if not 0 <= n < session["total_questions"]:
        return

    # Remove the inline buttons from the completed question so it stays permanently in chat history
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    await dbm.set_current_index(cb.from_user.id, n)
    # Send the next question as a brand-new message below the previous one
    await safe_send(cb, render_question(session, n), question_kb(n))


@router.callback_query(F.data == "finish")
async def cb_finish(cb: CallbackQuery) -> None:
    ok, _ = await check_auth(cb)
    if not ok:
        return
    await cb.answer()
    session = await _session_or_expired(cb)
    if not session:
        return

    # Keep the final question visible in chat history by only clearing its buttons
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    total, score = session["total_questions"], session["score"]
    pct = round(100 * score / total) if total else 0
    medal = "\U0001f3c6" if pct >= 80 else "\U0001f44d" if pct >= 60 else "\U0001f4d6"
    await safe_send(
        cb,
        f"\U0001f3c1 <b>Quiz Complete!</b>\n\n"
        f"{html.escape(session['topic'])}: {html.escape(session['subtopic'])}\n\n"
        f"{medal} Score: <b>{score}/{total}</b>\n\U0001f3af Accuracy: <b>{pct}%</b>",
        final_kb(),
    )
