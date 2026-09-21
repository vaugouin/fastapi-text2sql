#!/usr/bin/env python3
"""Off-production bench for the answer-entity classifier on TypeSafe's Jev model.

Sibling of `bench-result-entity.py`, and deliberately a separate script rather than a
branch inside it: Jev is not reachable through `text2sql._call_chat_llm`, which routes
on the model-name prefix and knows only OpenAI, Anthropic and Gemini. Adding a provider
there would put an unmeasured vendor call on the request path of every search before
anything had been measured, which is the wrong order. Nothing in this file is imported
by the application; it writes no execution row, no cache entry and touches no API server.

What it reuses, on purpose
--------------------------
Ground truth, the allowed vocabulary, the sampling and the outcome rule are imported
from `bench-result-entity.py` by file path, never copied. That bench already harvests
labels from evaluation executions that PASSED their assertions, drops the labels the
classifier is structurally unable to return (`movie_serie`, `movie_video`,
`serie_video`, which come from the text-to-SQL model), and reads the vocabulary out of
`main._RESULT_ENTITY_SOURCES` rather than holding a copy. Two benches that disagreed on
any of those would not be comparable, and comparing them is the entire point.

The one thing that has to be invented here: abstention
------------------------------------------------------
`f_classify_result_entity` has three outcomes, and only one of them is dangerous:

  correct            matches the ground-truth label
  abstained          "" or a word outside the vocabulary. The caller then keeps the
                     text-to-SQL model's own result_entity, which is the pre-existing
                     behaviour, so an abstention costs nothing
  confidently wrong  a different VALID label, which overrides a possibly-correct query
                     and forces a regeneration towards the wrong answer type

gpt-4o abstains natively: the prompt tells it to answer "unknown" when unsure, and the
caller filters anything outside the set. Jev has no such exit. A Choice call always
returns a label from `criteria` plus a confidence, so on this task an unmodified Jev
would be a classifier that is never unsure, and it would trade the cheapest safety
property the pipeline has for a probability nobody has calibrated.

So abstention is synthesised from `confidence`, and this script does NOT pick the
threshold. It sweeps it and prints the three outcomes at each step, because the only
honest way to compare the two is at equal risk: read off the threshold where Jev's
confident-error rate matches gpt-4o's, then compare how much each abstains there. A
single headline accuracy would hide exactly that trade.

Read the per-class table, not the headline
------------------------------------------
The distribution is savage. On the cache as exported 2026-09-21, `movie` + `person` +
`serie` carry 90.6 % of 6 778 rows, so answering "movie" every time already scores
56.5 %. Eleven classes sit under 25 examples and `death` has one. Percentages are
refused below --min-decidable for the same reason as in the sibling bench: a metric
computed on seven examples that reports "fine" is worse than no metric, because it
reassures.

Usage:
  uv run eval/bench-result-entity-jev.py --dry-run            # no key, no network
  uv run eval/bench-result-entity-jev.py --limit 100
  uv run eval/bench-result-entity-jev.py --limit 100 --compare-confident-error 4.0

Requires TYPESAFE_API_KEY in the environment (read by the SDK itself) and
`uv add typesafe-sdk`. FASTAPI-TEXT2SQL-282.
"""

import argparse
import collections
import concurrent.futures
import importlib.util
import json
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


def load_sibling_bench():
    """Import `bench-result-entity.py` by path; its hyphens make it un-importable by name.

    Its `if __name__ == "__main__"` guard means loading it runs no benchmark.

    The stub below is what lets this bench run in a container of its own. The sibling
    does `import text2sql as t2s` at module level, and `text2sql` pulls in pandas, numpy,
    psutil, openai, `data_watcher` and `json_guardrails`, then boots a prompt hot-reload
    watcher over `data/` just by being imported. None of that is reachable from here:
    `t2s` is touched only inside the sibling's `measure()` and `preflight()`, and this
    bench calls neither, since Jev is not reachable through `_call_chat_llm`. The four
    things actually borrowed, `load_allowed_entities`, `load_truth`, `classify_outcome`
    and `force_utf8_console`, are pure.

    So an empty module is registered under that name before the sibling is executed. The
    alternative was copying those four functions, which would let the two benches drift
    apart on ground truth and vocabulary, and comparing them is the entire point. If the
    sibling ever starts using `t2s` at module level, this fails loudly at load rather
    than quietly measuring the wrong thing.
    """
    sys.modules.setdefault("text2sql", types.ModuleType("text2sql"))
    path = os.path.join(HERE, "bench-result-entity.py")
    spec = importlib.util.spec_from_file_location("bench_result_entity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the sibling bench at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BENCH = load_sibling_bench()

# The Choice primitive takes a label -> description map, and that is the whole prompt:
# there is no room for the eleven few-shot examples the gpt-4o system prompt carries.
# The filter trap is what this task is actually hard at ("List Criterion collection
# movies" is `movie`, "What collections is Inception part of?" is `collection`, same
# word, opposite roles), so every description below states what the label means AS AN
# ANSWER, and the shared instruction carries the rule. If Jev loses to gpt-4o, the first
# hypothesis to test is that this compression is the cause, not the model.
CRITERIA = {
    "movie": "The rows are films. Pick this when the user wants films listed.",
    "serie": "The rows are TV series. Pick this when the user wants series listed.",
    "person": (
        "The rows are people: actors, directors, writers, composers, any role. Pick this "
        "whenever the user asks WHO, or asks for a role such as directors or actors, even "
        "when the words 'movie', 'film' or 'TV' sit in front of that role and only scope "
        "the medium."
    ),
    "collection": (
        "The rows are film collections or franchises, and the collections themselves are "
        "what the user wants listed. NOT this when a named collection merely narrows the "
        "search, as in 'movies in the Criterion collection'."
    ),
    "list": "The rows are curated lists, and the lists themselves are the answer.",
    "topic": "The rows are topics or themes, and the topics themselves are the answer.",
    "movement": "The rows are artistic or cinematic movements, and they are the answer.",
    "technical": "The rows are technical attributes such as formats or processes.",
    "group": "The rows are groups of people, and the groups themselves are the answer.",
    "death": "The rows are death records, and those records are what the user asked for.",
    "award": (
        "The rows are awards, and the awards themselves are the answer. NOT this when a "
        "named award merely narrows the search, as in 'films that won the Palme d'Or'."
    ),
    "nomination": "The rows are award nominations, and the nominations are the answer.",
    "company": (
        "The rows are production companies, and they are the answer. NOT this when a named "
        "company merely narrows the search."
    ),
    "network": (
        "The rows are TV networks or streaming services, and they are the answer. NOT this "
        "when a named network merely narrows the search, as in 'series on Netflix'."
    ),
    "location": (
        "The rows are places, and the places are the answer. NOT this when a place merely "
        "narrows the search, as in 'films set in Paris'."
    ),
    "genre": (
        "The rows are genres, and the genres themselves are the answer, as in 'what are the "
        "movie genres?'. NOT this when a genre merely narrows the search, as in 'sci-fi films'."
    ),
    "person_image": (
        "The rows are photographs OF a person: pictures, photos, portraits, images of "
        "someone. The user wants the image rows, not the person's card."
    ),
    "movie_image": (
        "The rows are images OF a film: posters, backdrops, stills. The user wants the image "
        "rows, not the film's card."
    ),
    "serie_image": (
        "The rows are images OF a TV series: posters, backdrops, stills. The user wants the "
        "image rows, not the series' card."
    ),
}

INSTRUCTIONS = (
    "A user asked a question of a movie and TV database. Decide what kind of thing the "
    "user wants LISTED in the result rows. Choose the type of the ROWS that should come "
    "back, never the filters or constraints used to narrow the search."
)

DEFAULT_MODEL = "jev-latest"
DEFAULT_THRESHOLDS = [0.0, 0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]


def check_criteria_against_vocabulary(allowed):
    """Fail loudly when this file has drifted from `main._RESULT_ENTITY_SOURCES`.

    The sibling bench reads the vocabulary from main.py precisely so it cannot drift.
    This file cannot do the same, because a description has to be written by hand for
    each label, so drift is detected instead of prevented. An entity added to the
    application and missing here would silently become unanswerable by Jev, and would
    look like a model failure.
    """
    allowed_set, ours = set(allowed), set(CRITERIA)
    missing, extra = sorted(allowed_set - ours), sorted(ours - allowed_set)
    problems = []
    if missing:
        problems.append(f"no description for {missing} (add them to CRITERIA)")
    if extra:
        problems.append(f"described but not in the application vocabulary: {extra}")
    return problems


def build_client():
    """Construct the SDK client, with the two failure modes named rather than traced."""
    try:
        from typesafe_sdk import Choice, TypeSafeClient  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "typesafe-sdk is not installed. Run:  uv add typesafe-sdk\n"
            f"({exc})"
        )
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit(
            "TYPESAFE_API_KEY is not set. The SDK reads it from the environment; put it in "
            "the host .env like every other secret in this repo, never in the image."
        )
    from typesafe_sdk import TypeSafeClient as Client
    return Client()


def ask_jev(client, question: str, model: str):
    """One Choice call. Returns (label, confidence, probabilities, error).

    Errors are returned rather than raised, for the same reason the production classifier
    swallows its own: one bad question must not abort a bench of hundreds. A call that
    errored is counted separately and never as an abstention, which would flatter it.
    """
    from typesafe_sdk import Choice
    try:
        questions = {"result_entity": Choice(instructions=INSTRUCTIONS, criteria=CRITERIA)}
        try:
            response = client.system_one(state=question, questions=questions, model=model)
        except TypeError:
            # The installed SDK may not expose `model` on system_one. Falling back silently
            # was the first version of this, and it was wrong: a run pinned to a specific
            # version would have been answered by whatever the SDK defaults to, and the
            # report would have named the pinned model anyway. Since the fallback IS the
            # SDK default, it is only harmless when that is what was asked for.
            if model != DEFAULT_MODEL:
                return "", 0.0, {}, (
                    f"the installed typesafe-sdk does not accept a `model` argument, so "
                    f"--model {model} cannot be honoured. Upgrade the SDK, or drop --model "
                    f"and accept the SDK default ({DEFAULT_MODEL})")
            response = client.system_one(state=question, questions=questions)
        answer = response.answers["result_entity"]
        return (
            str(getattr(answer, "choice", "") or "").strip().lower(),
            float(getattr(answer, "confidence", 0.0) or 0.0),
            dict(getattr(answer, "probabilities", {}) or {}),
            None,
        )
    except Exception as exc:  # noqa: BLE001 - reported per question, never fatal
        return "", 0.0, {}, f"{type(exc).__name__}: {exc}"


# The exact strings `bench-result-entity.classify_outcome` returns. Taken from its CODE,
# not from its prose: its docstrings say "confidently wrong" for readability while the
# function returns "wrong", and copying the prose version cost a crash on the first real
# run (and, worse, would have made the per-class block below report zeros in silence).
OUTCOME_CORRECT = "correct"
OUTCOME_ABSTAINED = "abstained"
OUTCOME_WRONG = "wrong"
OUTCOMES = (OUTCOME_CORRECT, OUTCOME_ABSTAINED, OUTCOME_WRONG)


def outcome_at(label: str, confidence: float, truth: str, allowed_set, threshold: float) -> str:
    """Apply the synthesised abstention, then the sibling bench's own outcome rule."""
    if not label or label not in allowed_set or confidence < threshold:
        return OUTCOME_ABSTAINED
    return BENCH.classify_outcome(label, truth, allowed_set)


def sweep(results, allowed_set, thresholds):
    """Three outcomes at each threshold. The table this bench exists to print."""
    rows = []
    scored = [r for r in results if r["error"] is None]
    for threshold in thresholds:
        # Counter, not a pre-filled dict: a missing outcome must read as zero rather than
        # raise, and an unexpected one must be named rather than swallowed.
        counts = collections.Counter(
            outcome_at(record["label"], record["confidence"],
                       record["truth"], allowed_set, threshold)
            for record in scored
        )
        unexpected = set(counts) - set(OUTCOMES)
        if unexpected:
            raise RuntimeError(
                f"the sibling bench returned outcome(s) this script does not know: "
                f"{sorted(unexpected)}. Expected {list(OUTCOMES)}. Reconcile OUTCOMES with "
                f"bench-result-entity.classify_outcome before trusting any figure.")
        total = max(len(scored), 1)
        rows.append({
            "threshold": threshold,
            "correct": counts[OUTCOME_CORRECT],
            "abstained": counts[OUTCOME_ABSTAINED],
            "confidently_wrong": counts[OUTCOME_WRONG],
            "correct_pct": 100.0 * counts[OUTCOME_CORRECT] / total,
            "abstained_pct": 100.0 * counts[OUTCOME_ABSTAINED] / total,
            "confident_error_pct": 100.0 * counts[OUTCOME_WRONG] / total,
        })
    return rows


def report(results, rows, elapsed, model, min_decidable, compare_confident_error):
    scored = [r for r in results if r["error"] is None]
    errored = [r for r in results if r["error"] is not None]
    total = len(scored)

    print()
    print("=" * 78)
    print(f"Jev answer-entity bench  |  model={model}  |  {total} scored, "
          f"{len(errored)} errored  |  {elapsed:.1f}s")
    print("=" * 78)

    if errored:
        print(f"\n{len(errored)} call(s) failed and are excluded from every figure below.")
        for record in errored[:5]:
            print(f"  {record['error']}  <- {record['question'][:60]}")

    if not total:
        print("\nNothing scored. No comparison is possible.")
        return

    counts = {}
    for record in scored:
        counts[record["truth"]] = counts.get(record["truth"], 0) + 1
    majority = max(counts.values()) if counts else 0
    print(f"\nMajority-class baseline: {100.0 * majority / total:.1f} % "
          f"(always answering '{max(counts, key=counts.get)}')")
    print("A score near that number means nothing was learned.")

    print("\nThreshold sweep. 'Abstained' is free: the caller keeps the text-to-SQL")
    print("model's own result_entity. 'Wrong' overrides a possibly-correct query.")
    print(f"\n  {'confidence':>10}  {'correct':>15}  {'abstained':>15}  {'WRONG':>15}")
    print(f"  {'-' * 10}  {'-' * 15}  {'-' * 15}  {'-' * 15}")
    for row in rows:
        print(f"  {row['threshold']:>10.2f}  "
              f"{row['correct']:>6d} {row['correct_pct']:>6.1f} %  "
              f"{row['abstained']:>6d} {row['abstained_pct']:>6.1f} %  "
              f"{row['confidently_wrong']:>6d} {row['confident_error_pct']:>6.1f} %")

    operating = max(rows, key=lambda r: r["threshold"])
    operating_why = ("the strictest swept, for want of a --compare-confident-error to "
                     "name an operating point")

    if compare_confident_error is not None:
        print(f"\nEqual-risk read against gpt-4o's confident-error rate of "
              f"{compare_confident_error:.1f} %:")
        usable = [r for r in rows if r["confident_error_pct"] <= compare_confident_error]
        if not usable:
            operating_why = ("the strictest swept: no threshold reached the comparison "
                             "risk, so there is no equal-risk point to read at")
            best = min(rows, key=lambda r: r["confident_error_pct"])
            print(f"  None. Jev's floor is {best['confident_error_pct']:.1f} % at "
                  f"threshold {best['threshold']:.2f}, above gpt-4o even when abstaining "
                  f"{best['abstained_pct']:.1f} % of the time. On this sample it does not "
                  f"reach parity, so the swap is not defensible on risk.")
        else:
            pick = min(usable, key=lambda r: r["abstained_pct"])
            # The per-class table below is read at THIS threshold, not at the strictest
            # swept. Printing it at the strictest was the first version, and it slandered
            # every class: at a threshold nobody would deploy the model abstains far more,
            # so each class reads worse than it behaves at the point under consideration.
            operating = pick
            operating_why = "the equal-risk point, which is the one worth deploying"
            print(f"  Threshold {pick['threshold']:.2f}: confident error "
                  f"{pick['confident_error_pct']:.1f} %, abstains {pick['abstained_pct']:.1f} %, "
                  f"correct {pick['correct_pct']:.1f} %.")
            print("  Compare that abstention rate with gpt-4o's. Higher means Jev buys the")
            print("  same safety by deferring more often, which costs nothing but gains nothing.")

    print(f"\nPer class (classes under n={min_decidable} are not decidable at this sample):")
    strict = operating["threshold"]
    print(f"  measured at threshold {strict:.2f}, {operating_why}")
    print(f"  at that point, overall: {operating['correct_pct']:.1f} % correct, "
          f"{operating['abstained_pct']:.1f} % abstained, "
          f"{operating['confident_error_pct']:.1f} % confidently wrong")
    allowed_set = set(CRITERIA)
    for truth in sorted(counts, key=counts.get, reverse=True):
        subset = [r for r in scored if r["truth"] == truth]
        good = sum(1 for r in subset
                   if outcome_at(r["label"], r["confidence"], r["truth"], allowed_set, strict)
                   == OUTCOME_CORRECT)
        bad = sum(1 for r in subset
                  if outcome_at(r["label"], r["confidence"], r["truth"], allowed_set, strict)
                  == OUTCOME_WRONG)
        if len(subset) < min_decidable:
            print(f"  {truth:<14} n={len(subset):<4} not decidable at this n "
                  f"({good} right, {bad} wrong)")
        else:
            print(f"  {truth:<14} n={len(subset):<4} {100.0 * good / len(subset):>5.1f} % right, "
                  f"{bad} confidently wrong")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="TypeSafe model id.")
    parser.add_argument("--lang", choices=["en", "fr"], default="en")
    parser.add_argument("--limit", type=int, default=100, help="Questions to bench (0 = all).")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--truth-dir", default=BENCH.DEFAULT_TRUTH_DIR)
    parser.add_argument("--run", default=BENCH.DEFAULT_RUN_PREFIX)
    parser.add_argument("--min-decidable", type=int, default=30)
    parser.add_argument("--compare-confident-error", type=float, default=None,
                        help="gpt-4o's confident-error %% from the sibling bench, for an "
                             "equal-risk read.")
    parser.add_argument("--thresholds", default=None,
                        help="Comma-separated confidence thresholds to sweep.")
    parser.add_argument("--out", default=None, help="Write the per-question result as JSON.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check vocabulary, truth and payload shape. No key, no network.")
    args = parser.parse_args()

    BENCH.force_utf8_console()

    allowed = BENCH.load_allowed_entities()
    problems = check_criteria_against_vocabulary(allowed)
    if problems:
        print("CRITERIA has drifted from main._RESULT_ENTITY_SOURCES:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    items, stats = BENCH.load_truth(args.truth_dir, args.run, args.lang, allowed, args.limit)
    print(f"Vocabulary: {len(allowed)} labels, all described.")
    print(f"Ground truth: {len(items)} pass-verified questions from {args.run} ({args.lang}).")
    print(f"  dropped: {stats['skipped_failed']} that failed their assertions, "
          f"{stats['skipped_out_of_vocab']} outside the classifier vocabulary, "
          f"{stats['duplicates']} duplicates, {stats['skipped_unscored']} unscored.")
    if not items:
        print("No ground truth found. Check --truth-dir and --run.")
        return 1

    thresholds = DEFAULT_THRESHOLDS
    if args.thresholds:
        thresholds = sorted({float(t) for t in args.thresholds.split(",") if t.strip()})

    if args.dry_run:
        print("\nDry run. Payload that each question would send:")
        print(json.dumps({
            "model": args.model,
            "state": items[0]["question"],
            "questions": {"result_entity": {"instructions": INSTRUCTIONS,
                                            "criteria": {k: CRITERIA[k] for k in
                                                         list(CRITERIA)[:3]}}},
        }, indent=2, ensure_ascii=False)[:900] + "\n  ... criteria truncated to 3 of "
              f"{len(CRITERIA)} for display")
        print(f"\nWould sweep thresholds: {thresholds}")
        print("Nothing was sent. Set TYPESAFE_API_KEY and drop --dry-run to measure.")
        return 0

    client = build_client()
    started = time.time()
    results = []

    def run_one(item):
        label, confidence, probabilities, error = ask_jev(client, item["question"], args.model)
        return {"id": item["id"], "question": item["question"], "truth": item["truth"],
                "label": label, "confidence": confidence,
                "probabilities": probabilities, "error": error}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for record in pool.map(run_one, items):
            results.append(record)

    elapsed = time.time() - started
    rows = sweep(results, set(CRITERIA), thresholds)
    report(results, rows, elapsed, args.model, args.min_decidable,
           args.compare_confident_error)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"model": args.model, "lang": args.lang, "run": args.run,
                       "sweep": rows, "results": results}, handle,
                      indent=2, ensure_ascii=False)
        print(f"\nWritten: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
