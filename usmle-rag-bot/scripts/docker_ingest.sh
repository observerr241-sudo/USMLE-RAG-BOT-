#!/bin/sh
# Container entrypoint: split the First Aid PDF found in $BOOK_DIR, then embed + load MongoDB.
#
# Env (all optional):
#   PDF_PATH      full path to the PDF (default: first *.pdf in $BOOK_DIR)
#   PDF_OFFSET    pdf_page_number - printed_page_number (default: auto-detect)
#   SPLIT_ONLY=1  stop after splitting so you can inspect the preview (no Gemini calls, no DB writes)
#   SKIP_SPLIT=1  reuse an existing all_chunks_ready.json in $OUT_DIR
#   INGEST_RESET=1  wipe book_chunks before loading
set -eu

BOOK_DIR="${BOOK_DIR:-/book}"
OUT_DIR="${OUT_DIR:-/out}"
JSON="$OUT_DIR/all_chunks_ready.json"

if [ "${SKIP_SPLIT:-0}" != "1" ]; then
  PDF="${PDF_PATH:-}"
  if [ -z "$PDF" ]; then
    PDF="$(ls "$BOOK_DIR"/*.pdf 2>/dev/null | head -n 1 || true)"
  fi
  if [ -z "$PDF" ] || [ ! -f "$PDF" ]; then
    echo "ERROR: no PDF found. Put the First Aid PDF in ./book/ on the host (mounted at $BOOK_DIR)." >&2
    exit 1
  fi
  echo "==> Splitting: $PDF"
  if [ -n "${PDF_OFFSET:-}" ]; then
    python scripts/split_first_aid.py --pdf "$PDF" --out "$OUT_DIR" --offset "$PDF_OFFSET"
  else
    python scripts/split_first_aid.py --pdf "$PDF" --out "$OUT_DIR"
  fi
fi

if [ "${SPLIT_ONLY:-0}" = "1" ]; then
  echo "==> SPLIT_ONLY=1: stopping before embedding. Inspect ./first_aid_split_preview/ on the host."
  exit 0
fi

if [ ! -f "$JSON" ]; then
  echo "ERROR: $JSON not found (run without SKIP_SPLIT)." >&2
  exit 1
fi

echo "==> Embedding + loading MongoDB"
if [ "${INGEST_RESET:-0}" = "1" ]; then
  python scripts/ingest_to_mongo.py --json "$JSON" --reset
else
  python scripts/ingest_to_mongo.py --json "$JSON"
fi
echo "==> Ingest finished."
