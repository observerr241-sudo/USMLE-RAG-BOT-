#!/usr/bin/env python3
"""Offline: split the First Aid Step 1 PDF into the catalog's Topics / Subtopics.

    pip install -r requirements-ingest.txt
    python scripts/split_first_aid.py --pdf "First_Aid_Step1.pdf" [--offset N] [--out first_aid_split_preview]

Outputs  <out>/NN_Topic/NN_Subtopic.md  (human-checkable previews)  and  <out>/all_chunks_ready.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf  # noqa: E402  (installed with pymupdf4llm)
import pymupdf4llm  # noqa: E402
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter  # noqa: E402

from bot.catalog import FIRST_AID_CATALOG, section_label, subtopic_count, topic_count  # noqa: E402

CHUNK_SIZE = 1800
CHUNK_OVERLAP = 200


# --------------------------------------------------------------------------- page offset
def detect_offset(doc: "pymupdf.Document", scan_from: int = 20, scan_to: int = 140) -> int:
    """offset = pdf_page_number(1-based) - printed_page_number. Majority vote over body pages.

    Handles the roman-numeral front matter: only plain integers at the top/bottom of a page vote.
    """
    votes: Counter[int] = Counter()
    for idx in range(scan_from, min(scan_to, doc.page_count)):
        lines = [ln.strip() for ln in doc[idx].get_text().splitlines() if ln.strip()]
        for cand in lines[:3] + lines[-3:]:
            if re.fullmatch(r"\d{1,3}", cand):
                printed = int(cand)
                if 1 <= printed <= 800:
                    votes[(idx + 1) - printed] += 1
    if not votes:
        raise SystemExit("Could not auto-detect the page offset. Pass --offset (pdf_page_number - printed_page_number).")
    offset, n = votes.most_common(1)[0]
    print(f"Detected page offset {offset} ({n} votes; runner-up: {votes.most_common(2)[1:] or 'none'})")
    return offset


# --------------------------------------------------------------------------- subtopic detection
def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def subtopic_keys(name: str) -> list[str]:
    """'Anatomy & Physiology' -> ['anatomy and physiology', 'anatomy', 'physiology']."""
    full = _norm(name)
    keys = {full}
    for part in re.split(r"\band\b", full):
        part = part.strip()
        if part:
            keys.add(part)
    out = set(keys)
    for k in keys:  # singular/plural tolerance (Systems/System, Antimicrobials/Antimicrobial)
        out.add(k[:-1] if k.endswith("s") else k + "s")
    return sorted(out, key=len, reverse=True)


def match_subtopic(header: str, key_map: dict[int, list[str]]) -> int | None:
    h = _norm(header)
    if not h or len(h) > 60:
        return None
    for s_id, keys in key_map.items():
        for k in keys:
            if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", h):
                return s_id
    return None


# --------------------------------------------------------------------------- splitting
def split_topic(markdown: str, t_id: int) -> dict[int, list[dict]]:
    topic = FIRST_AID_CATALOG[t_id]
    key_map = {s: subtopic_keys(n) for s, n in topic["subtopics"].items()}
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")], strip_headers=False
    )
    rec = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    label = section_label(t_id)
    by_sub: dict[int, list[dict]] = {s: [] for s in topic["subtopics"]}
    current = 0
    for doc in md_splitter.split_text(markdown):
        headers = [doc.metadata.get(k) for k in ("h1", "h2", "h3", "h4") if doc.metadata.get(k)]
        for h in headers:  # a heading that names a subtopic switches the running subtopic
            hit = match_subtopic(h, key_map)
            if hit is not None:
                current = hit
        heading = headers[-1] if headers else topic["name"]
        sub_name = topic["subtopics"][current]
        for piece in rec.split_text(doc.page_content):
            piece = piece.strip()
            if len(piece) < 80:
                continue
            by_sub[current].append({
                "t_id": t_id,
                "topic": topic["name"],
                "s_id": current,
                "subtopic": sub_name,
                "segment_group": topic["segment_group"],
                "heading": heading,
                "content": f"[Section: {label} | Topic: {topic['name']} | Subtopic: {sub_name} | Heading: {heading}]\n{piece}",
            })
    return by_sub


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default="first_aid_split_preview")
    ap.add_argument("--offset", type=int, default=None, help="pdf_page_number - printed_page_number (auto-detected if omitted)")
    args = ap.parse_args()

    doc = pymupdf.open(args.pdf)
    print(f"{args.pdf}: {doc.page_count} pages | catalog: {topic_count()} topics / {subtopic_count()} subtopics")
    offset = args.offset if args.offset is not None else detect_offset(doc)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    all_chunks: list[dict] = []
    empty: list[str] = []

    for t_id, topic in FIRST_AID_CATALOG.items():
        first, last = topic["pages"]
        pages = [p for p in range(first + offset - 1, last + offset) if 0 <= p < doc.page_count]  # 0-based indices
        if not pages:
            print(f"!! {topic['name']}: printed pages {first}-{last} fall outside the PDF; skipping")
            continue
        md = pymupdf4llm.to_markdown(doc, pages=pages, show_progress=False)
        by_sub = split_topic(md, t_id)
        tdir = out / f"{t_id:02d}_{safe(topic['name'])}"
        tdir.mkdir(parents=True, exist_ok=True)
        print(f"[{t_id:02d}] {topic['name']} (printed {first}-{last}, {len(pages)} pages)")
        for s_id, items in by_sub.items():
            name = topic["subtopics"][s_id]
            (tdir / f"{s_id:02d}_{safe(name)}.md").write_text("\n\n---\n\n".join(c["content"] for c in items), encoding="utf-8")
            print(f"      {s_id}: {name:<38} {len(items):>4} chunks")
            if not items:
                empty.append(f"{topic['name']} / {name}")
            all_chunks.extend(items)

    (out / "all_chunks_ready.json").write_text(json.dumps(all_chunks, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(all_chunks)} chunks -> {out / 'all_chunks_ready.json'}")
    if empty:
        print(f"Note: {len(empty)} subtopic(s) got no chunks (the bot falls back to the whole topic for them):")
        for e in empty:
            print("   -", e)
        print("Open the preview .md files to check the heading matches; use --offset if pages look shifted.")


if __name__ == "__main__":
    main()
