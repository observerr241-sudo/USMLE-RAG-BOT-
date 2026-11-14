"""Async MongoDB layer (motor): paid-subscriber gate, RAG chunk retrieval, quiz sessions."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from bot import config

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_date(dt: datetime) -> str:
    return _aware(dt).strftime("%d %b %Y")


def db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("init_db() has not been called")
    return _db


def users() -> AsyncIOMotorCollection:
    return db()["authorized_users"]


def chunks() -> AsyncIOMotorCollection:
    return db()["book_chunks"]


def sessions() -> AsyncIOMotorCollection:
    return db()["quiz_sessions"]


async def init_db() -> None:
    global _client, _db
    _client = AsyncIOMotorClient(config.MONGODB_URI, tz_aware=True, serverSelectionTimeoutMS=20000)
    _db = _client[config.MONGODB_DB]
    await _client.admin.command("ping")
    await users().create_index("telegram_id", unique=True)
    await users().create_index("subscription_expires_at")
    await chunks().create_index([("t_id", 1), ("s_id", 1)])
    await sessions().create_index("telegram_id", unique=True)
    await sessions().create_index("created_at", expireAfterSeconds=7 * 24 * 3600)  # stale quizzes vanish after a week


async def close_db() -> None:
    if _client is not None:
        _client.close()


# --------------------------------------------------------------------------- authorization
async def is_user_authorized(telegram_id: int) -> tuple[bool, str]:
    if telegram_id in config.ADMIN_IDS:
        return True, "Admin Access"
    user = await users().find_one({"telegram_id": telegram_id})
    if not user or not user.get("is_authorized"):
        return False, "Not Authorized"
    expires = user.get("subscription_expires_at")
    if not expires or _aware(expires) < utcnow():
        await users().update_one({"telegram_id": telegram_id}, {"$set": {"is_authorized": False}})
        return False, "Subscription Expired"
    return True, fmt_date(expires)


async def grant_user(
    telegram_id: int,
    days: int = 30,
    admin_id: int | None = None,
    username: str = "",
    full_name: str = "",
) -> datetime:
    """Upsert a paid subscriber; expiry = now + days. Returns the expiry."""
    expires = utcnow() + timedelta(days=days)
    set_fields: dict[str, Any] = {"is_authorized": True, "subscription_expires_at": expires, "added_by_admin": admin_id}
    if username:
        set_fields["username"] = username
    if full_name:
        set_fields["full_name"] = full_name
    await users().update_one(
        {"telegram_id": telegram_id},
        {
            "$set": set_fields,
            "$setOnInsert": {"telegram_id": telegram_id, "quizzes_generated": 0, "created_at": utcnow()},
        },
        upsert=True,
    )
    return expires


async def revoke_user(telegram_id: int) -> bool:
    res = await users().update_one({"telegram_id": telegram_id}, {"$set": {"is_authorized": False}})
    return res.matched_count > 0


async def list_active_users() -> list[dict]:
    cur = users().find({"is_authorized": True, "subscription_expires_at": {"$gt": utcnow()}}).sort("subscription_expires_at", 1)
    return [u async for u in cur]


async def get_stats() -> dict[str, int]:
    agg = users().aggregate([{"$group": {"_id": None, "q": {"$sum": "$quizzes_generated"}}}])
    total_quizzes = 0
    async for row in agg:
        total_quizzes = int(row.get("q", 0))
    return {
        "chunks": await chunks().estimated_document_count(),
        "authorized_users": await users().count_documents(
            {"is_authorized": True, "subscription_expires_at": {"$gt": utcnow()}}
        ),
        "quizzes": total_quizzes,
    }


async def increment_quizzes(telegram_id: int) -> None:
    await users().update_one({"telegram_id": telegram_id}, {"$inc": {"quizzes_generated": 1}})


# --------------------------------------------------------------------------- RAG retrieval
async def get_relevant_chunks(
    t_id: int,
    s_id: int,
    query_embedding: list[float] | None,
    limit: int = 10,
    diversify: bool = True,
) -> str:
    """Top `limit` chunks (numpy cosine similarity) for the subtopic, falling back to the whole topic.

    diversify=True ranks the best 2x`limit` and samples `limit` of them, so repeating the same
    subtopic does not always produce the same questions.
    """
    docs = await chunks().find({"t_id": t_id, "s_id": s_id}).to_list(length=None)
    if len(docs) < 3:
        docs = await chunks().find({"t_id": t_id}).to_list(length=None)
    if not docs:
        return ""

    selected: list[dict]
    usable = [d for d in docs if d.get("embedding")]
    if query_embedding and len(usable) >= 1:
        mat = np.asarray([d["embedding"] for d in usable], dtype=np.float32)
        q = np.asarray(query_embedding, dtype=np.float32)
        sims = (mat @ q) / ((np.linalg.norm(mat, axis=1) * np.linalg.norm(q)) + 1e-9)
        order = np.argsort(-sims)
        pool_size = min(len(order), limit * 2 if diversify else limit)
        pool = [usable[i] for i in order[:pool_size]]
        selected = random.sample(pool, min(limit, len(pool))) if diversify and len(pool) > limit else pool[:limit]
    else:
        selected = random.sample(docs, min(limit, len(docs)))

    return "\n\n---\n\n".join(d["content"] for d in selected)


# --------------------------------------------------------------------------- quiz sessions
async def create_session(telegram_id: int, t_id: int, topic: str, s_id: int, subtopic: str, questions: list[dict]) -> dict:
    doc = {
        "telegram_id": telegram_id,
        "t_id": t_id,
        "topic": topic,
        "s_id": s_id,
        "subtopic": subtopic,
        "total_questions": len(questions),
        "current_index": 0,
        "score": 0,
        "answered_indices": [],
        "chosen": {},
        "questions": questions,
        "created_at": utcnow(),
    }
    await sessions().replace_one({"telegram_id": telegram_id}, doc, upsert=True)  # one active quiz per user
    return doc


async def get_session(telegram_id: int) -> dict | None:
    return await sessions().find_one({"telegram_id": telegram_id})


async def record_answer(telegram_id: int, i: int, choice: int, correct: bool) -> bool:
    """Atomically record the first answer for question i. Returns False if it was already answered."""
    res = await sessions().update_one(
        {"telegram_id": telegram_id, "answered_indices": {"$ne": i}},
        {
            "$push": {"answered_indices": i},
            "$inc": {"score": 1 if correct else 0},
            "$set": {f"chosen.{i}": choice, "current_index": i},
        },
    )
    return res.modified_count == 1


async def set_current_index(telegram_id: int, i: int) -> None:
    await sessions().update_one({"telegram_id": telegram_id}, {"$set": {"current_index": i}})
