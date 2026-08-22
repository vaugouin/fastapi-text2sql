#!/usr/bin/env python3
"""Off-production bench for the split entity-extraction prompt (FASTAPI-TEXT2SQL-200).

The ticket's gate, before anything is deployed: build the two prompts, run them over
the questions already measured, and keep the split only if it matches the single
prompt on the controls and beats it on the hard titles. This script is that gate.

It calls `entity.f_entity_extraction` (one 779-line prompt) and
`entity.f_entity_extraction_split` (two concurrent prompts, merged) on the same
questions, in the same process, and scores both against the same gold assertions with
the evaluator's own `ee_eval_two_layer`. Nothing is written anywhere: no API server, no
evaluation table, no cache.

Question sources, in order of preference:
  --questions-file PATH   one question per line, no scoring (works with no database)
  (default)               the evaluation bank, scored against ASSERTIONS_ENTITY_EXTRACTION

Usage:
  uv run eval/bench-entity-extraction-split.py --limit 20
  uv run eval/bench-entity-extraction-split.py --lang fr --workers 4 --out /tmp/bench.json
  uv run eval/bench-entity-extraction-split.py --questions-file /tmp/hard-titles.txt

Reads DB_* and the LLM keys from the repository .env, like the rest of the stack.
"""
import argparse
import contextlib
import html
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
import pymysql.cursors

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import entity_extraction_eval_functions as ee_eval  # noqa: E402
import entity  # noqa: E402

load_dotenv()


def get_db_connection():
    """Open the shared MariaDB connection, same environment variables as the API."""
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=15,
    )


def load_bank(lang: str, limit: int):
    """Return the scored question bank: id, question and its gold assertion.

    Same filter as the evaluator's run phase, restricted to the rows that actually
    carry an entity-extraction assertion, since those are the only ones this bench
    can score.
    """
    column = "QUESTION_FR" if lang == "fr" else "QUESTION"
    strsql = (
        f"SELECT ID_T2S_EVALUATION AS id, {column} AS question, ASSERTIONS_ENTITY_EXTRACTION AS assertion "
        "FROM T_WC_T2S_EVALUATION "
        "WHERE IS_EVAL = 1 AND DELETED = 0 "
        "AND ASSERTIONS_ENTITY_EXTRACTION IS NOT NULL AND ASSERTIONS_ENTITY_EXTRACTION <> '' "
        f"AND {column} IS NOT NULL AND {column} <> '' "
        "ORDER BY ID_T2S_EVALUATION"
    )
    if limit:
        strsql += f" LIMIT {int(limit)}"

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(strsql)
            rows = cursor.fetchall()
    finally:
        connection.close()

    return [
        {
            "id": row["id"],
            "question": html.unescape((row["question"] or "").strip()),
            "assertion": html.unescape((row["assertion"] or "").strip()),
        }
        for row in rows
        if (row["question"] or "").strip()
    ]


def load_questions_file(path: str, limit: int):
    """Return questions read one per line, with no gold assertion to score against."""
    questions = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text and not text.startswith("#"):
                questions.append({"id": None, "question": text, "assertion": ""})
    return questions[:limit] if limit else questions


def score(payload, assertion: str):
    """Return 1 / 0 for a scored question, or None when there is nothing to score."""
    if not assertion or not isinstance(payload, dict) or "error" in payload:
        return None
    try:
        return 1 if ee_eval.ee_eval_two_layer(payload, assertion) else 0
    except Exception:
        return 0


def measure(function, *args):
    """Run one extraction and return its payload plus its wall-clock cost."""
    started = time.time()
    try:
        payload = function(*args)
    except Exception as e:
        payload = {"error": f"{type(e).__name__}: {e}"}
    return payload, time.time() - started


_progress_lock = threading.Lock()
_progress_done = 0


def _tick(total: int) -> None:
    """Report progress on stderr, so it survives the stdout muting."""
    global _progress_done
    with _progress_lock:
        _progress_done += 1
        print(f"\r  {_progress_done}/{total} questions", end="", file=sys.stderr, flush=True)


def bench_one(item, model, total):
    """Run both extraction shapes on one question and score each."""
    question = item["question"]
    single, single_seconds = measure(entity.f_entity_extraction, question, model)
    split, split_seconds = measure(entity.f_entity_extraction_split, question, model)
    _tick(total)
    return {
        "id": item["id"],
        "question": question,
        "assertion": item["assertion"],
        "single": single,
        "split": split,
        "single_seconds": single_seconds,
        "split_seconds": split_seconds,
        "single_score": score(single, item["assertion"]),
        "split_score": score(split, item["assertion"]),
    }


def percentile(values, share):
    """Return the value at ``share`` of a sorted sample (nearest rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))
    return ordered[index]


def report(results, elapsed):
    """Print the comparison: scores, disagreements and the timing spread."""
    scored = [r for r in results if r["single_score"] is not None and r["split_score"] is not None]
    single_ok = sum(r["single_score"] for r in scored)
    split_ok = sum(r["split_score"] for r in scored)

    print()
    print("=" * 78)
    print(f"Questions run: {len(results)}   scored: {len(scored)}   wall clock: {elapsed:.1f}s")
    if scored:
        print(f"Single prompt: {single_ok}/{len(scored)} ({100.0 * single_ok / len(scored):.1f}%)")
        print(f"Split prompts: {split_ok}/{len(scored)} ({100.0 * split_ok / len(scored):.1f}%)")
        print(f"Delta:         {split_ok - single_ok:+d}")

    gained = [r for r in scored if r["split_score"] == 1 and r["single_score"] == 0]
    lost = [r for r in scored if r["split_score"] == 0 and r["single_score"] == 1]
    print(f"\nGained by the split: {len(gained)}   lost by the split: {len(lost)}")
    for label, rows in (("GAINED", gained), ("LOST", lost)):
        for row in rows:
            print(f"\n  [{label}] #{row['id']} {row['question']}")
            print(f"      single: {json.dumps(row['single'], ensure_ascii=False)}")
            print(f"      split : {json.dumps(row['split'], ensure_ascii=False)}")
            print(f"      gold  : {row['assertion']}")

    differing = [
        r for r in results
        if (r["single"] or {}).get("question") != (r["split"] or {}).get("question")
        and r not in gained and r not in lost
    ]
    print(f"\nSame score but different output: {len(differing)}")
    for row in differing[:20]:
        print(f"  #{row['id']} {row['question']}")
        print(f"      single: {json.dumps(row['single'], ensure_ascii=False)}")
        print(f"      split : {json.dumps(row['split'], ensure_ascii=False)}")
    if len(differing) > 20:
        print(f"  ... and {len(differing) - 20} more (see --out)")

    errors = [r for r in results if "error" in (r["single"] or {}) or "error" in (r["split"] or {})]
    if errors:
        print(f"\nExtraction errors: {len(errors)}")
        for row in errors[:10]:
            print(f"  #{row['id']} {row['question']}")
            print(f"      single: {(row['single'] or {}).get('error', '-')}")
            print(f"      split : {(row['split'] or {}).get('error', '-')}")

    single_times = [r["single_seconds"] for r in results]
    split_times = [r["split_seconds"] for r in results]
    print("\nPer-question latency (seconds)")
    print(f"  single  median {percentile(single_times, 0.5):.2f}   p90 {percentile(single_times, 0.9):.2f}   max {max(single_times or [0]):.2f}")
    print(f"  split   median {percentile(split_times, 0.5):.2f}   p90 {percentile(split_times, 0.9):.2f}   max {max(split_times or [0]):.2f}")
    print("=" * 78)


def main():
    """Parse the CLI, run both extraction shapes over the bank and report."""
    parser = argparse.ArgumentParser(description="Compare single-prompt and split entity extraction.")
    parser.add_argument("--lang", choices=["en", "fr"], default="en", help="Which question column to read from the bank.")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N questions (0 = all).")
    parser.add_argument("--workers", type=int, default=4, help="Questions processed concurrently.")
    parser.add_argument("--model", default="default", help="Entity-extraction model override.")
    parser.add_argument("--questions-file", default=None, help="Read questions from a file instead of the bank (no scoring).")
    parser.add_argument("--out", default=None, help="Write the full per-question result as JSON.")
    parser.add_argument("--verbose", action="store_true", help="Keep the extraction step's own console output.")
    args = parser.parse_args()

    if args.questions_file:
        items = load_questions_file(args.questions_file, args.limit)
        print(f"Loaded {len(items)} questions from {args.questions_file} (no gold assertions, no scoring)")
    else:
        items = load_bank(args.lang, args.limit)
        print(f"Loaded {len(items)} scored {args.lang} questions from the evaluation bank")

    if not items:
        print("Nothing to run.")
        return 1

    started = time.time()
    # The extraction step narrates every call; muted by default so the comparison is
    # readable, and progress goes to stderr instead.
    muted = io.StringIO()
    with contextlib.nullcontext() if args.verbose else contextlib.redirect_stdout(muted):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda item: bench_one(item, args.model, len(items)), items))
    elapsed = time.time() - started
    print(file=sys.stderr)

    report(results, elapsed)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
        print(f"\nFull results written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
