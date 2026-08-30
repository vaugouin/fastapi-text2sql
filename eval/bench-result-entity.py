#!/usr/bin/env python3
"""Off-production A/B bench for the answer-entity classifier (`f_classify_result_entity`).

Runs two model configurations over the same questions, in the same process, and scores
both against ground truth harvested from past evaluation runs. Nothing is written
anywhere: no API server, no evaluation-execution row, no cache entry. Sibling of
`bench-entity-extraction.py`, which does the same for task 1.

Why this task needs its own bench rather than a pass-rate comparison
--------------------------------------------------------------------
The classifier decides, from the ORIGINAL question, what kind of thing the rows should
be, and it is AUTHORITATIVE over the text-to-SQL model's own `result_entity`: on
disagreement it triggers one targeted regeneration. So its effect on the end-to-end
answer is conditional. On the questions where it agrees, and that is most of them, it
changes nothing at all. Measuring it through the evaluator would spend a full campaign
to observe a task that is inert on the majority of the bank, and the run would land in
the baseline's own execution folder because this model is not part of the run signature
(FASTAPI-TEXT2SQL-234). This bench sidesteps both problems.

Three outcomes, never one accuracy number
-----------------------------------------
  correct            matches the ground-truth label
  abstained          "" or a word outside the allowed set. The caller then falls back to
                     the text-to-SQL model's own result_entity, which is the pre-existing
                     behaviour, so an abstention costs nothing.
  confidently wrong  a different VALID label. This is the only dangerous outcome: the
                     classifier overrides a query that may well have been correct, and
                     forces a regeneration towards the wrong answer type.

A model that abstains more is not equivalent to one that errs more, and a single
accuracy figure hides exactly that difference. The decision rule below is built on the
confident-error rate alone.

Read the per-class table, not the headline
------------------------------------------
The label distribution is savage: on run 001.001.018, `movie` + `person` + `serie` carry
90 % of the ground truth, so a classifier that answers "movie" every time already scores
about 54 %. The bench prints that majority baseline next to the real score for exactly
that reason, and refuses to print a percentage for any class below --min-decidable,
saying "not decidable at this n" instead. A metric computed on seven examples that
reports "fine" is worse than no metric: it reassures. (This is the lesson of the
ChromaDB `lists` check, which came back OK at 9 % on 23 documents and would have missed
the defect it was written for.)

Two uses, as with the entity-extraction bench
---------------------------------------------
  Compare two models.       --model-a gpt-4o --model-b gpt-5.6-luna
  Measure the noise floor.  --model-a gpt-4o --model-b gpt-4o
      The same configuration against itself. At temperature 0 a model still disagrees
      with itself on a few questions, and knowing that number is what tells a real
      regression from a coin flip. Run this FIRST; the comparison is unreadable without
      it. Feed the number back in with --noise-floor so the verdict line can use it.

Usage:
  uv run eval/bench-result-entity.py --model-a gpt-4o --model-b gpt-4o --limit 100
  uv run eval/bench-result-entity.py --model-a gpt-4o --model-b gpt-5.6-luna --noise-floor 3
  uv run eval/bench-result-entity.py --lang fr --workers 8 --out /shared/bench-re-fr.json

Ground truth comes from the evaluation-execution exports on disk (no database needed):
an execution that PASSED its assertions had the right answer type, so its `result_entity`
is usable as a label.

The one caveat, and it is worth knowing before reading any confident-error line: a passing
execution proves its assertions were satisfied, NOT that its `result_entity` is the label a
human would pick. Evaluation 948 is the single `serie_image` row in the EN set and its
question is `Serie game of thrones`, which asks for nothing about images; the execution
nonetheless ran against T_WC_T2S_SERIE_IMAGE and passed. A model answering `serie` there is
defensible and still scores a confident error. Treat an error on a small class as a prompt
to go read the case, never as a verdict on the model, which is also why --min-decidable
exists: at n=1, one questionable label is the whole class.

Reads the LLM keys from the repository .env, like the rest of the stack.
"""
import argparse
import ast
import contextlib
import glob
import io
import json
import os
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import text2sql as t2s  # noqa: E402

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TRUTH_DIR = os.path.join(REPO_ROOT, "eval", "data", "evaluation_execution")
DEFAULT_RUN_PREFIX = "001.001.018"


def load_allowed_entities():
    """Return the classifier's allowed labels, read out of main.py without importing it.

    `main._RESULT_ENTITY_SOURCES` is the single source of truth, and the classifier is
    called with its keys. Importing main.py here would boot the whole application, so
    the dict literal is parsed from the source instead. Reading the real file rather
    than copying the list is what keeps this bench from drifting when an entity is added.
    """
    source = os.path.join(REPO_ROOT, "main.py")
    with open(source, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "_RESULT_ENTITY_SOURCES" for target in node.targets
        ):
            return [key.value for key in node.value.keys]
    raise RuntimeError("_RESULT_ENTITY_SOURCES not found in main.py")


def load_truth(truth_dir: str, run_prefix: str, lang: str, allowed, limit: int):
    """Return labelled questions harvested from past evaluation-execution exports.

    A row is usable when it passed its assertions (so the answer type it produced was
    right) and carries a label the classifier is actually allowed to return. Labels such
    as `movie_video` or `movie_serie` come from the text-to-SQL model and are outside the
    classifier's vocabulary, so keeping them would count a guaranteed miss against every
    model equally. They are dropped, and the count is reported.
    """
    allowed_set = set(allowed)
    pattern = os.path.join(truth_dir, f"{run_prefix}_{lang}_*", "*.json")
    items, seen_questions = [], set()
    skipped_unscored = skipped_failed = skipped_out_of_vocab = duplicates = 0

    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        output = payload.get("api_output") or {}
        scoring = payload.get("scoring") or {}
        question = (output.get("question") or "").strip()
        label = (output.get("result_entity") or "").strip().lower()
        total = scoring.get("assertions_total_score")

        if not question or total is None:
            skipped_unscored += 1
            continue
        try:
            if float(total) < 1.0:
                skipped_failed += 1
                continue
        except (TypeError, ValueError):
            skipped_unscored += 1
            continue
        if label not in allowed_set:
            skipped_out_of_vocab += 1
            continue
        # The same question appears once per evaluation id; classifying it twice would
        # weight it twice in the score without adding information.
        if question in seen_questions:
            duplicates += 1
            continue
        seen_questions.add(question)
        items.append({"id": payload.get("evaluation_id"), "question": question, "truth": label})

    items.sort(key=lambda item: (item["id"] is None, item["id"]))
    if limit:
        items = stratified_sample(items, limit)
    stats = {
        "skipped_unscored": skipped_unscored,
        "skipped_failed": skipped_failed,
        "skipped_out_of_vocab": skipped_out_of_vocab,
        "duplicates": duplicates,
    }
    return items, stats


def stratified_sample(items, limit: int):
    """Take ``limit`` items round-robin across classes, not off the top of the list.

    The exports are ordered by evaluation id and the bank opens on a run of `movie`
    questions, so a plain head slice of 12 is twelve movies: the run reports a perfect
    score having tested one class out of nineteen. Round-robin keeps a small smoke run
    representative and keeps the tail visible, which is the part a weaker model breaks.
    """
    by_class = defaultdict(list)
    for item in items:
        by_class[item["truth"]].append(item)
    # Rarest class first, so the tail is served before the budget runs out.
    queues = sorted(by_class.values(), key=len)
    picked, exhausted = [], False
    while len(picked) < limit and not exhausted:
        exhausted = True
        for queue in queues:
            if queue:
                picked.append(queue.pop(0))
                exhausted = False
                if len(picked) >= limit:
                    break
    picked.sort(key=lambda item: (item["id"] is None, item["id"]))
    return picked


def load_questions_file(path: str, limit: int):
    """Return questions read one per line, with no label, so nothing is scored."""
    items = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text and not text.startswith("#"):
                items.append({"id": None, "question": text, "truth": ""})
    return items[:limit] if limit else items


def classify_outcome(predicted: str, truth: str, allowed_set) -> str:
    """Return 'correct', 'abstained' or 'wrong' for one prediction."""
    if not truth:
        return "unscored"
    if predicted == truth:
        return "correct"
    if not predicted or predicted not in allowed_set:
        return "abstained"
    return "wrong"


def measure(model: str, question: str, allowed):
    """Run one classification and return its answer plus its wall-clock cost."""
    started = time.time()
    try:
        answer = t2s.f_classify_result_entity(question, allowed, model)
        answer = (answer or "").strip().lower()
        error = ""
    except Exception as e:
        answer, error = "", f"{type(e).__name__}: {e}"
    return answer, error, time.time() - started


_progress_lock = threading.Lock()
_progress_done = 0


def _tick(total: int) -> None:
    """Report progress on stderr, so it survives the stdout muting."""
    global _progress_done
    with _progress_lock:
        _progress_done += 1
        print(f"\r  {_progress_done}/{total} questions", end="", file=sys.stderr, flush=True)


def bench_one(item, model_a, model_b, allowed, allowed_set, total):
    """Run both configurations on one question and classify each outcome."""
    question = item["question"]
    answer_a, error_a, seconds_a = measure(model_a, question, allowed)
    answer_b, error_b, seconds_b = measure(model_b, question, allowed)
    _tick(total)
    return {
        "id": item["id"],
        "question": question,
        "truth": item["truth"],
        "a": answer_a,
        "b": answer_b,
        "a_error": error_a,
        "b_error": error_b,
        "a_seconds": seconds_a,
        "b_seconds": seconds_b,
        "a_outcome": classify_outcome(answer_a, item["truth"], allowed_set),
        "b_outcome": classify_outcome(answer_b, item["truth"], allowed_set),
    }


def percentile(values, share):
    """Return the value at ``share`` of a sorted sample (nearest rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))
    return ordered[index]


def outcome_counts(results, side):
    """Return the three-way outcome tally for one side."""
    counter = Counter(row[f"{side}_outcome"] for row in results)
    return counter["correct"], counter["abstained"], counter["wrong"]


def report(results, elapsed, model_a, model_b, min_decidable, noise_floor):
    """Print the comparison: outcomes, per-class table, confusions, latency, verdict."""
    scored = [row for row in results if row["truth"]]
    total = len(scored)

    print()
    print("=" * 78)
    print(f"Questions run: {len(results)}   scored: {total}   wall clock: {elapsed:.1f}s")
    print(f"A = {model_a}")
    print(f"B = {model_b}")
    if model_a == model_b:
        print("Same configuration on both sides: what follows is the NOISE FLOOR, not a comparison.")
        print("Feed the confident-error count back in with --noise-floor on the real run.")
    if not total:
        print("Nothing scored (no ground truth). Answers are in --out only.")
        print("=" * 78)
        return None

    # The number that stops a headline score from being mistaken for competence.
    majority_label, majority_n = Counter(row["truth"] for row in scored).most_common(1)[0]
    print(f"\nMajority baseline: always answering '{majority_label}' scores "
          f"{majority_n}/{total} ({100.0 * majority_n / total:.1f}%). "
          f"Read every score below against this, not against zero.")

    print("\nOutcomes")
    print(f"  {'':22s}{'correct':>10s}{'abstained':>12s}{'WRONG':>10s}")
    a_ok, a_abs, a_bad = outcome_counts(scored, "a")
    b_ok, b_abs, b_bad = outcome_counts(scored, "b")
    for label, ok, abstain, bad in (("A " + model_a, a_ok, a_abs, a_bad),
                                    ("B " + model_b, b_ok, b_abs, b_bad)):
        print(f"  {label[:22]:22s}{ok:>10d}{abstain:>12d}{bad:>10d}")
    print(f"  {'delta (B - A)':22s}{b_ok - a_ok:>+10d}{b_abs - a_abs:>+12d}{b_bad - a_bad:>+10d}")
    print("\n  An abstention falls back to the text-to-SQL model's own result_entity, which is")
    print("  the pre-existing behaviour, so it costs nothing. Only WRONG overrides a query.")

    # Per-class, with the tail refused a percentage rather than given a meaningless one.
    by_class = defaultdict(lambda: {"n": 0, "a": 0, "b": 0, "a_bad": 0, "b_bad": 0})
    for row in scored:
        bucket = by_class[row["truth"]]
        bucket["n"] += 1
        bucket["a"] += row["a_outcome"] == "correct"
        bucket["b"] += row["b_outcome"] == "correct"
        bucket["a_bad"] += row["a_outcome"] == "wrong"
        bucket["b_bad"] += row["b_outcome"] == "wrong"

    print(f"\nPer class (a class under n={min_decidable} gets no percentage: at that size a "
          f"proportion cannot discriminate)")
    print(f"  {'class':16s}{'n':>6s}{'A correct':>12s}{'B correct':>12s}{'A wrong':>10s}{'B wrong':>10s}")
    decidable_n = decidable_a_bad = decidable_b_bad = 0
    undecidable = []
    for name, bucket in sorted(by_class.items(), key=lambda kv: -kv[1]["n"]):
        n = bucket["n"]
        if n >= min_decidable:
            decidable_n += n
            decidable_a_bad += bucket["a_bad"]
            decidable_b_bad += bucket["b_bad"]
            print(f"  {name:16s}{n:>6d}{100.0 * bucket['a'] / n:>11.1f}%"
                  f"{100.0 * bucket['b'] / n:>11.1f}%{bucket['a_bad']:>10d}{bucket['b_bad']:>10d}")
        else:
            undecidable.append((name, n, bucket["a_bad"], bucket["b_bad"]))
    if undecidable:
        tail_n = sum(item[1] for item in undecidable)
        plural = "class" if len(undecidable) == 1 else "classes"
        print(f"\n  Not decidable at this sample size: {len(undecidable)} {plural}, {tail_n} questions "
              f"({100.0 * tail_n / total:.1f}% of the set)")
        for name, n, a_bad, b_bad in undecidable:
            flag = "  <-- B errs here" if b_bad > a_bad else ""
            print(f"    {name:16s} n={n:<4d} A wrong {a_bad}, B wrong {b_bad}{flag}")
        print("  These are counted, never scored. A model that breaks only here will not show")
        print("  up in any percentage above, which is the whole reason they are listed.")

    # Which confusion B actually makes: the truth -> predicted pairs, most common first.
    for side, name in (("a", model_a), ("b", model_b)):
        confusions = Counter(
            (row["truth"], row[side]) for row in scored if row[f"{side}_outcome"] == "wrong"
        )
        if confusions:
            print(f"\nConfident errors, {side.upper()} = {name}")
            for (truth, predicted), count in confusions.most_common(12):
                print(f"  {count:>4d}x  {truth} -> {predicted}")
            if len(confusions) > 12:
                print(f"  ... and {len(confusions) - 12} further pairs (see --out)")

    disagreements = [row for row in scored if row["a"] != row["b"]]
    print(f"\nA and B answered differently on {len(disagreements)} of {total} questions")
    for row in disagreements[:15]:
        print(f"  #{row['id']} {row['question'][:70]}")
        print(f"      truth={row['truth']}   A={row['a'] or '(abstain)'}   B={row['b'] or '(abstain)'}")
    if len(disagreements) > 15:
        print(f"  ... and {len(disagreements) - 15} more (see --out)")

    errors = [row for row in results if row["a_error"] or row["b_error"]]
    if errors:
        print(f"\nCall errors: {len(errors)}")
        for row in errors[:10]:
            print(f"  #{row['id']} A: {row['a_error'] or '-'}   B: {row['b_error'] or '-'}")

    a_times = [row["a_seconds"] for row in results]
    b_times = [row["b_seconds"] for row in results]
    print("\nPer-question latency (seconds)")
    print(f"  A  median {percentile(a_times, 0.5):.2f}   p90 {percentile(a_times, 0.9):.2f}   max {max(a_times or [0]):.2f}")
    print(f"  B  median {percentile(b_times, 0.5):.2f}   p90 {percentile(b_times, 0.9):.2f}   max {max(b_times or [0]):.2f}")

    # The decision rule, stated before the run rather than negotiated after it.
    print("\nVerdict")
    if model_a == model_b:
        disagreed = sum(1 for row in scored if row["a"] != row["b"])
        if decidable_n:
            floor = max(decidable_a_bad, decidable_b_bad)
            print(f"  Noise floor: {floor} confident error{"" if floor == 1 else "s"} on the {decidable_n} questions in")
            print(f"  decidable classes, and the configuration disagreed with itself on "
                  f"{disagreed} of {total} questions.")
            print(f"  Pass this to the real run as --noise-floor {floor}.")
        else:
            print(f"  No class reached n={min_decidable}, so there is no decidable subset and no")
            print(f"  usable floor. The run did show {disagreed} self-disagreements on {total}")
            print("  questions, which is a smoke test, not a floor. Re-run without --limit.")
    elif noise_floor is None:
        print("  No --noise-floor given, so no verdict. Run the same model on both sides first:")
        print(f"    uv run eval/bench-result-entity.py --model-a {model_a} --model-b {model_a}")
        print("  Without that number a small delta cannot be told from a coin flip.")
    else:
        delta = decidable_b_bad - decidable_a_bad
        print(f"  Confident errors on decidable classes: A {decidable_a_bad}, B {decidable_b_bad} "
              f"(delta {delta:+d}), noise floor {noise_floor}.")
        if delta <= noise_floor:
            print("  ADOPT B: the extra confident errors sit within the noise floor.")
        else:
            print(f"  HOLD: B makes {delta} more confident errors, above the floor of {noise_floor}.")
        print("  Abstentions are deliberately not counted here: they fall back, they do not override.")
    print("=" * 78)
    return {"a_correct": a_ok, "a_abstained": a_abs, "a_wrong": a_bad,
            "b_correct": b_ok, "b_abstained": b_abs, "b_wrong": b_bad,
            "scored": total, "decidable_n": decidable_n,
            "decidable_a_wrong": decidable_a_bad, "decidable_b_wrong": decidable_b_bad,
            "majority_label": majority_label, "majority_n": majority_n}


def force_utf8_console():
    """Make stdout/stderr UTF-8, because the bank is full of accents and this is Windows.

    An interactive console here is cp1252. Redirect stdout to a file and Python inherits
    that codec, so the first question carrying an accent raises UnicodeEncodeError in the
    middle of the report, and the run dies AFTER paying for every LLM call but BEFORE
    writing --out. Measured the hard way on 2026-08-30: 689 questions x 2 calls spent, no
    artefact. errors="replace" rather than strict, because a mangled character in a printed
    question is cosmetic and losing the run is not.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main():
    """Parse the CLI, run both configurations over the labelled set and report."""
    force_utf8_console()
    parser = argparse.ArgumentParser(
        description="Compare two answer-entity classifier configurations, off production.")
    parser.add_argument("--model-a", default="default", help="Side A model; 'default' uses the module default.")
    parser.add_argument("--model-b", default="default", help="Side B model; same value as A measures the noise floor.")
    parser.add_argument("--lang", choices=["en", "fr"], default="en", help="Which language's executions to read.")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N questions (0 = all).")
    parser.add_argument("--workers", type=int, default=4, help="Questions processed concurrently.")
    parser.add_argument("--truth-dir", default=DEFAULT_TRUTH_DIR,
                        help="Root of the evaluation-execution exports.")
    parser.add_argument("--run", default=DEFAULT_RUN_PREFIX,
                        help="Execution-run prefix to harvest labels from (an API version).")
    parser.add_argument("--min-decidable", type=int, default=30,
                        help="A class with fewer questions than this gets counted, never scored.")
    parser.add_argument("--noise-floor", type=int, default=None,
                        help="Confident-error count measured by running one model against itself.")
    parser.add_argument("--questions-file", default=None,
                        help="Read questions from a file instead of the exports (no labels, no scoring).")
    parser.add_argument("--out", default=None, help="Write the full per-question result as JSON.")
    parser.add_argument("--verbose", action="store_true", help="Keep the classifier's own console output.")
    args = parser.parse_args()

    allowed = load_allowed_entities()
    allowed_set = set(allowed)
    print(f"Classifier vocabulary: {len(allowed)} labels, read from main.py")

    if args.questions_file:
        items = load_questions_file(args.questions_file, args.limit)
        print(f"Loaded {len(items)} questions from {args.questions_file} (no labels, no scoring)")
    else:
        items, stats = load_truth(args.truth_dir, args.run, args.lang, allowed, args.limit)
        print(f"Loaded {len(items)} labelled {args.lang} questions from run {args.run}")
        print(f"  dropped: {stats['skipped_failed']} that failed their assertions "
              f"(a wrong answer is not ground truth), {stats['skipped_out_of_vocab']} labelled "
              f"outside the classifier's vocabulary, {stats['duplicates']} duplicate questions, "
              f"{stats['skipped_unscored']} unscored")

    if not items:
        print("Nothing to run. Check --truth-dir and --run, or pass --questions-file.")
        return 1

    started = time.time()
    # The classifier narrates its calls through _call_chat_llm; muted by default so the
    # comparison stays readable, and progress goes to stderr instead.
    muted = io.StringIO()
    with contextlib.nullcontext() if args.verbose else contextlib.redirect_stdout(muted):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(
                lambda item: bench_one(item, args.model_a, args.model_b, allowed, allowed_set, len(items)),
                items))
    elapsed = time.time() - started
    print(file=sys.stderr)

    # Written BEFORE the report on purpose. Every LLM call is already paid for by this
    # point, so a failure while formatting the summary must not be able to destroy the
    # run's only durable output.
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"model_a": args.model_a, "model_b": args.model_b, "lang": args.lang,
                       "run": args.run, "elapsed_seconds": elapsed, "results": results},
                      handle, ensure_ascii=False, indent=2)
        print(f"Raw results saved to {args.out} before reporting")


    summary = report(results, elapsed, args.model_a, args.model_b, args.min_decidable, args.noise_floor)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"model_a": args.model_a, "model_b": args.model_b, "lang": args.lang,
                       "run": args.run, "elapsed_seconds": elapsed,
                       "summary": summary, "results": results},
                      handle, ensure_ascii=False, indent=2)
        print(f"\nFull results written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
