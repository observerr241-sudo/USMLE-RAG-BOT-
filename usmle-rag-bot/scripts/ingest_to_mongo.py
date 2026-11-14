#!/usr/bin/env python3
"""Embed first_aid_split_preview/all_chunks_ready.json (gemini-embedding-001 @ 768d, rotating keys)
and upsert into MongoDB usmle_rag_db.book_chunks.

    python scripts/ingest_to_mongo.py [--json first_aid_split_preview/all_chunks_ready.json] [--reset] [--batch 40]

Safe to re-run: chunk _id is a content hash, so already-embedded chunks are skipped.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient, ReplaceOne  # noqa: E402

from bot import config  # noqa: E402
from bot.gemini_router import embed_texts, get_rotator  # noqa: E402


def chunk_id(c: dict) -> str:
    return hashlib.sha1(f"{c['t_id']}|{c['s_id']}|{c['content']}".encode("utf-8")).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="first_aid_split_preview/all_chunks_ready.json")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--reset", action="store_true", help="delete all existing book_chunks first")
    args = ap.parse_args()

    config.validate(require_bot=False)
    chunks = json.loads(Path(args.json).read_text(encoding="utf-8"))
    for c in chunks:
        c["_id"] = chunk_id(c)

    client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=20000)
    coll = client[config.MONGODB_DB]["book_chunks"]
    coll.create_index([("t_id", 1), ("s_id", 1)])
    if args.reset:
        print(f"Deleted {coll.delete_many({}).deleted_count} existing chunks")

    have = {d["_id"] for d in coll.find({"embedding": {"$exists": True}}, {"_id": 1})}
    todo = [c for c in chunks if c["_id"] not in have]
    print(f"{len(chunks)} chunks in file | {len(have)} already in DB | {len(todo)} to embed")
    get_rotator()  # logs key summary

    done = 0
    for i in range(0, len(todo), args.batch):
        batch = todo[i:i + args.batch]
        t0 = time.time()
        vectors = asyncio.run(embed_texts([c["content"] for c in batch], task_type="RETRIEVAL_DOCUMENT"))
        ops = [ReplaceOne({"_id": c["_id"]}, {**{k: v for k, v in c.items() if k != "_id"}, "embedding": v}, upsert=True)
               for c, v in zip(batch, vectors)]
        coll.bulk_write(ops, ordered=False)
        done += len(batch)
        print(f"  embedded + stored {done}/{len(todo)}  ({time.time() - t0:.1f}s)")

    print(f"Done. book_chunks now holds {coll.estimated_document_count()} documents.")
    print(get_rotator().summary())


if __name__ == "__main__":
    main()
