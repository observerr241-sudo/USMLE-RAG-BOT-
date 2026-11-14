"""Admin commands and the 1-click approve / reject callbacks."""
from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot import config, database as dbm

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _notify_active(bot, user_id: int, expires) -> None:
    try:
        await bot.send_message(
            user_id,
            f"🎉 <b>Your subscription is active!</b>\nValid until <b>{dbm.fmt_date(expires)}</b>.\n\nSend /start to begin practicing.",
        )
    except Exception as exc:
        logger.warning("Could not notify user %s: %s", user_id, exc)


# --------------------------------------------------------------------------- commands
@router.message(Command("grant"))
async def cmd_grant(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (command.args or "").split()
    try:
        uid = int(parts[0])
        days = int(parts[1]) if len(parts) > 1 else 30
        if not 1 <= days <= 3650:
            raise ValueError
    except (IndexError, ValueError):
        await message.answer("Usage: <code>/grant &lt;telegram_id&gt; [days]</code>")
        return
    expires = await dbm.grant_user(uid, days, admin_id=message.from_user.id)
    await _notify_active(message.bot, uid, expires)
    await message.answer(f"✅ Granted <code>{uid}</code> for {days} days (until {dbm.fmt_date(expires)}).")


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    try:
        uid = int((command.args or "").split()[0])
    except (IndexError, ValueError):
        await message.answer("Usage: <code>/revoke &lt;telegram_id&gt;</code>")
        return
    found = await dbm.revoke_user(uid)
    await message.answer(f"🚫 Revoked <code>{uid}</code>." if found else f"User <code>{uid}</code> is not in the database.")


@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    active = await dbm.list_active_users()
    if not active:
        await message.answer("No active subscribers.")
        return
    lines = []
    for u in active:
        who = f"@{html.escape(u['username'])}" if u.get("username") else html.escape(u.get("full_name") or "—")
        lines.append(f"• <code>{u['telegram_id']}</code> {who} — until {dbm.fmt_date(u['subscription_expires_at'])}")
    header = f"👥 <b>Active subscribers: {len(active)}</b>\n"
    buf = header
    for line in lines:
        if len(buf) + len(line) + 1 > 3900:
            await message.answer(buf)
            buf = ""
        buf += line + "\n"
    if buf:
        await message.answer(buf)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    s = await dbm.get_stats()
    try:
        from bot.gemini_router import get_rotator
        keys = html.escape(get_rotator().summary())
    except Exception:
        keys = "n/a"
    await message.answer(
        "📊 <b>Stats</b>\n"
        f"📚 Textbook chunks in DB: <b>{s['chunks']}</b>\n"
        f"👥 Authorized users: <b>{s['authorized_users']}</b>\n"
        f"📝 Quizzes generated: <b>{s['quizzes']}</b>\n"
        f"🔑 Gemini keys: {keys}"
    )


# --------------------------------------------------------------------------- 1-click approval
@router.callback_query(F.data.startswith("adm_ok:"))
async def cb_approve(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True)
        return
    try:
        _, uid_s, days_s = cb.data.split(":")
        uid, days = int(uid_s), int(days_s)
    except ValueError:
        await cb.answer("Bad request", show_alert=True)
        return
    username = full_name = ""
    try:
        chat = await cb.bot.get_chat(uid)
        username = chat.username or ""
        full_name = " ".join(p for p in (chat.first_name, chat.last_name) if p)
    except Exception:
        pass
    expires = await dbm.grant_user(uid, days, admin_id=cb.from_user.id, username=username, full_name=full_name)
    await _notify_active(cb.bot, uid, expires)
    await cb.answer("Approved ✅")
    if cb.message:
        base = cb.message.html_text or ""
        await cb.message.edit_text(
            f"{base}\n\n✅ <b>Approved {days} days</b> by {html.escape(cb.from_user.full_name)} (until {dbm.fmt_date(expires)})",
            reply_markup=None,
        )


@router.callback_query(F.data.startswith("adm_no:"))
async def cb_reject(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Admins only.", show_alert=True)
        return
    try:
        uid = int(cb.data.split(":")[1])
    except (IndexError, ValueError):
        await cb.answer("Bad request", show_alert=True)
        return
    try:
        await cb.bot.send_message(
            uid,
            "❌ Your payment request could not be verified. Please check your TrxID and send it again, or contact the Admin.",
        )
    except Exception as exc:
        logger.warning("Could not notify rejected user %s: %s", uid, exc)
    await cb.answer("Rejected")
    if cb.message:
        base = cb.message.html_text or ""
        await cb.message.edit_text(f"{base}\n\n❌ <b>Rejected</b> by {html.escape(cb.from_user.full_name)}", reply_markup=None)
