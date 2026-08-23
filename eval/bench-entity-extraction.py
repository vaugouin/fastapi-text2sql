#!/usr/bin/env python3
"""Off-production A/B bench for entity extraction.

Runs two extraction configurations over the same questions, in the same process, and
scores both against the same gold assertions with the evaluator's own
`ee_eval_two_layer`. Nothing is written anywhere: no API server, no evaluation-execution
row, no cache entry. That makes it cheap enough to run before deciding anything, which
is the point.

Two uses, both proven:

  Compare two models.       --model-a gpt-4o --model-b claude-...
      Which one extracts better, on the questions the bank can actually score.

  Measure the noise floor.  --model-a gpt-4o --model-b gpt-4o
      The same configuration against itself. At temperature 0 gpt-4o still disagrees
      with itself on a couple of questions out of 326, and knowing that number is what
      tells a real regression from a coin flip. This is how FASTAPI-TEXT2SQL-200 was
      settled: the candidate lost 11 questions against a noise floor of 2, so the gap
      was real and the change was dropped.

A prompt change has no flag to switch, so compare it across time instead: run the bench
before the edit with `--out before.json`, edit `data/entity_extraction.md`, run it again
with `--out after.json`, and diff the two files. The prompt hot-reloads, so the second
run picks the edit up without a restart.

Question sources, in order of preference:
  --questions-file PATH   one question per line, no scoring (works with no database)
  (default)               the evaluation bank, scored against ASSERTIONS_ENTITY_EXTRACTION

Usage:
  uv run eval/bench-entity-extraction.py --model-a gpt-4o --model-b gpt-4o --limit 20
  uv run eval/bench-entity-extraction.py --lang fr --workers 8 --out /shared/bench.json
  uv run eval/bench-entity-extraction.py --questions-file /tmp/hard-titles.txt

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


def measure(model: str, question: str):
    """Run one extraction and return its payload plus its wall-clock cost."""
    started = time.time()
    try:
        payload = entity.f_entity_extraction(question, model)
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


def bench_one(item, model_a, model_b, total):
    """Run both configurations on one question and score each."""
    question = item["question"]
    payload_a, seconds_a = measure(model_a, question)
    payload_b, seconds_b = measure(model_b, question)
    _tick(total)
    return {
        "id": item["id"],
        "question": question,
        "assertion": item["assertion"],
        "a": payload_a,
        "b": payload_b,
        "a_seconds": seconds_a,
        "b_seconds": seconds_b,
        "a_score": score(payload_a, item["assertion"]),
        "b_score": score(payload_b, item["assertion"]),
    }


def percentile(values, share):
    """Return the value at ``share`` of a sorted sample (nearest rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))
    return ordered[index]


def report(results, elapsed, model_a, model_b):
    """Print the comparison: scores, disagreements and the timing spread."""
    scored = [r for r in results if r["a_score"] is not None and r["b_score"] is not None]
    a_ok = sum(r["a_score"] for r in scored)
    b_ok = sum(r["b_score"] for r in scored)

    print()
    print("=" * 78)
    print(f"Questions run: {len(results)}   scored: {len(scored)}   wall clock: {elapsed:.1f}s")
    print(f"A = {model_a}")
    print(f"B = {model_b}")
    if model_a == model_b:
        print("Same configuration on both sides: what follows is the noise floor, not a comparison.")
    if scored:
        print(f"A: {a_ok}/{len(scored)} ({100.0 * a_ok / len(scored):.1f}%)")
        print(f"B: {b_ok}/{len(scored)} ({100.0 * b_ok / len(scored):.1f}%)")
        print(f"Delta (B - A): {b_ok - a_ok:+d}")

    gained = [r for r in scored if r["b_score"] == 1 and r["a_score"] == 0]
    lost = [r for r in scored if r["b_score"] == 0 and r["a_score"] == 1]
    print(f"\nB wins: {len(gained)}   B loses: {len(lost)}")
    for label, rows in (("B WINS", gained), ("B LOSES", lost)):
        for row in rows:
            print(f"\n  [{label}] #{row['id']} {row['question']}")
            print(f"      A: {json.dumps(row['a'], ensure_ascii=False)}")
            print(f"      B: {json.dumps(row['b'], ensure_ascii=False)}")
            print(f"      gold: {row['assertion']}")

    differing = [
        r for r in results
        if (r["a"] or {}).get("question") != (r["b"] or {}).get("question")
        and r not in gained and r not in lost
    ]
    print(f"\nSame score but different output: {len(differing)}")
    for row in differing[:20]:
        print(f"  #{row['id']} {row['question']}")
        print(f"      A: {json.dumps(row['a'], ensure_ascii=False)}")
        print(f"      B: {json.dumps(row['b'], ensure_ascii=False)}")
    if len(differing) > 20:
        print(f"  ... and {len(differing) - 20} more (see --out)")

    errors = [r for r in results if "error" in (r["a"] or {}) or "error" in (r["b"] or {})]
    if errors:
        print(f"\nExtraction errors: {len(errors)}")
        for row in errors[:10]:
            print(f"  #{row['id']} {row['question']}")
            print(f"      A: {(row['a'] or {}).get('error', '-')}")
            print(f"      B: {(row['b'] or {}).get('error', '-')}")

    a_times = [r["a_seconds"] for r in results]
    b_times = [r["b_seconds"] for r in results]
    print("\nPer-question latency (seconds)")
    print(f"  A  median {percentile(a_times, 0.5):.2f}   p90 {percentile(a_times, 0.9):.2f}   max {max(a_times or [0]):.2f}")
    print(f"  B  median {percentile(b_times, 0.5):.2f}   p90 {percentile(b_times, 0.9):.2f}   max {max(b_times or [0]):.2f}")
    print("=" * 78)


def main():
    """Parse the CLI, run both configurations over the bank and report."""
    parser = argparse.ArgumentParser(description="Compare two entity-extraction configurations, off production.")
    parser.add_argument("--model-a", default="default", help="Side A model; 'default' uses the module default.")
    parser.add_argument("--model-b", default="default", help="Side B model; same value as A measures the noise floor.")
    parser.add_argument("--lang", choices=["en", "fr"], default="en", help="Which question column to read from the bank.")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N questions (0 = all).")
    parser.add_argument("--workers", type=int, default=4, help="Questions processed concurrently.")
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
            results = list(pool.map(lambda item: bench_one(item, args.model_a, args.model_b, len(items)), items))
    elapsed = time.time() - started
    print(file=sys.stderr)

    report(results, elapsed, args.model_a, args.model_b)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
        print(f"\nFull results written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
