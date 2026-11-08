#!/usr/bin/env python3
"""Off-production bench of the intent classifier (FASTAPI-TEXT2SQL-353).

The intent rides on the answer-entity call, whose reply grows from one word to a JSON object.
Two questions follow, and this bench answers both without an API server, a campaign or a
cache entry:

1. Does the entity label hold? The one-word classifier (`f_classify_result_entity`) and the
   intent classifier (`f_classify_result_intent`) run side by side on the same ground truth
   as `bench-result-entity.py` (passed executions of a campaign), and the three outcomes are
   counted for each: correct, abstained, confidently wrong. Only the last one is dangerous
   (it forces a regeneration towards the wrong answer type). The ticket's acceptance is
   "entity label unchanged": the intent side must not err more than the one-word side by
   more than its noise floor.
2. Is the task right? The intent classifier and the keyword rules run on the questions whose
   result_shape assertion carries `intent.task` (TEXT2SQL-EVAL-003, 82 questions labelled on
   2026-11-08), both languages. The rules were tuned on those labels, so their score is an
   upper bound, not a measure; the classifier's is the measure.

Labels: read from `--labels`, either the bank JSON folder (`assertions.result_shape`, once a
sync has carried the labels) or the result file of text2sql-eval's
`update-evaluations-intent-task.sql` (`| id | ...; intent.task == X |` rows).

Usage:
  uv run checks/bench-result-intent.py --run 001.001.020 --limit 300 --workers 8
  uv run checks/bench-result-intent.py --labels ../text2sql-eval/update-evaluations-intent-task-20261108.txt --skip-entity
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, REPO_ROOT)

_spec = importlib.util.spec_from_file_location("bench_result_entity", os.path.join(HERE, "bench-result-entity.py"))
bre = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bre)
t2s = bre.t2s
import result_intent  # noqa: E402

EVAL_REPO = os.path.join(os.path.dirname(REPO_ROOT), "text2sql-eval")
DEFAULT_LABELS = os.path.join(EVAL_REPO, "data", "evaluation")
_LABEL_ROW_RE = re.compile(r"\|\s*(\d+)\s*\|.*?intent\.task\s*==\s*(\w+)")
_LABEL_CLAUSE_RE = re.compile(r"intent\.task\s*==\s*(\w+)")


def load_labels(path):
    """{evaluation id: task} from a bank folder or an update result file."""
    labels = {}
    if os.path.isdir(path):
        for file in glob.glob(os.path.join(path, "*.json")):
            with open(file, encoding="utf-8") as handle:
                data = json.load(handle)
            shape = ((data.get("assertions") or {}).get("result_shape") or "")
            match = _LABEL_CLAUSE_RE.search(shape)
            if match:
                labels[int(data["evaluation_id"])] = match.group(1)
    else:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = _LABEL_ROW_RE.search(line)
                if match:
                    labels[int(match.group(1))] = match.group(2)
    return labels


def load_questions(bank_dir, ids):
    """{id: (question_en, question_fr)} for the labelled ids, from the bank JSON."""
    out = {}
    for file in glob.glob(os.path.join(bank_dir, "*.json")):
        eid = int(os.path.basename(file).split("_", 1)[0])
        if eid in ids:
            with open(file, encoding="utf-8") as handle:
                data = json.load(handle)
            out[eid] = (data.get("question_en") or "", data.get("question_fr") or "")
    return out


def classify_intent(question, allowed, model):
    started = time.time()
    try:
        entity, intent = t2s.f_classify_result_intent(question, allowed, model)
        error = ""
    except Exception as e:  # the function swallows its own errors; this is belt and braces
        entity, intent, error = "", None, f"{type(e).__name__}: {e}"
    return entity, intent, error, time.time() - started


def bench_tasks(labels, questions, allowed, model, workers):
    jobs = [(eid, lang, q, labels[eid]) for eid, pair in sorted(questions.items())
            for lang, q in zip(("en", "fr"), pair) if q]

    def one(job):
        eid, lang, q, want = job
        _, intent, error, seconds = classify_intent(q, allowed, model)
        llm_task = (intent or {}).get("task", "")
        return eid, lang, q, want, llm_task, result_intent.rules_task(q), error, seconds

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, jobs))
    print(f"\n== Task on the {len(labels)} labelled questions ({len(rows)} calls, model {model})")
    for lang in ("en", "fr"):
        part = [r for r in rows if r[1] == lang]
        llm_ok = sum(r[4] == r[3] for r in part)
        rules_ok = sum(r[5] == r[3] for r in part)
        none = sum(not r[4] for r in part)
        print(f"  {lang}: classifier {llm_ok}/{len(part)} (no task {none}), rules {rules_ok}/{len(part)} (tuned on these labels)")
    per_task = Counter()
    per_task_ok = Counter()
    for r in rows:
        per_task[r[3]] += 1
        per_task_ok[r[3]] += r[4] == r[3]
    print("  per task (classifier): " + ", ".join(f"{t} {per_task_ok[t]}/{per_task[t]}" for t in sorted(per_task)))
    misses = [r for r in rows if r[4] != r[3]]
    for eid, lang, q, want, got, rules, error, _ in misses:
        print(f"  MISS {eid} {lang} want {want} got {got or '-'} (rules {rules}){' ERROR ' + error if error else ''} | {q}")
    seconds = sorted(r[7] for r in rows)
    if seconds:
        print(f"  call time: median {seconds[len(seconds) // 2]:.2f} s, p90 {seconds[int(len(seconds) * 0.9)]:.2f} s")
    return rows


def bench_entity(truth_dir, run, lang, allowed, model, limit, workers):
    items, _stats = bre.load_truth(truth_dir, run, lang, allowed, 0)
    items = bre.stratified_sample(items, limit) if limit else items
    allowed_set = set(allowed)

    def one(item):
        old, old_error, old_s = bre.measure(model, item["question"], allowed)
        new, _, new_error, new_s = classify_intent(item["question"], allowed, model)
        return (bre.classify_outcome(old, item["truth"], allowed_set) if not old_error else "error",
                bre.classify_outcome(new, item["truth"], allowed_set) if not new_error else "error",
                old, new, item, old_s, new_s)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, items))
    # bre.measure captures stdout with contextlib.redirect_stdout, which is process-wide: run
    # from several threads, the restores interleave and can leave sys.stdout on a StringIO,
    # and the report then vanishes with exit code 0. Put the real stream back.
    sys.stdout = sys.__stdout__
    print(f"\n== Entity label, one-word vs intent call, {lang.upper()}, {len(rows)} questions of {run} (model {model})")
    for side, idx in (("one-word", 0), ("intent  ", 1)):
        c = Counter(r[idx] for r in rows)
        print(f"  {side}: correct {c['correct']}, abstained {c['abstained']}, wrong {c['wrong']}, error {c['error']}")
    flips = [r for r in rows if r[2] != r[3]]
    print(f"  label differs on {len(flips)} questions")
    for o_out, n_out, old, new, item, _, _ in flips[:40]:
        print(f"    truth {item['truth']:<12} one-word {old or '-':<12} intent {new or '-':<12} | {item['question']}")
    for side, idx in (("one-word", 5), ("intent", 6)):
        s = sorted(r[idx] for r in rows)
        if s:
            print(f"  {side} call time: median {s[len(s) // 2]:.2f} s, p90 {s[int(len(s) * 0.9)]:.2f} s")
    return rows


def main():
    bre.force_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default="default")
    parser.add_argument("--labels", default=DEFAULT_LABELS, help="Bank JSON folder or update result file.")
    parser.add_argument("--bank", default=DEFAULT_LABELS, help="Bank JSON folder, for the question texts.")
    parser.add_argument("--truth-dir", default=bre.DEFAULT_TRUTH_DIR)
    parser.add_argument("--run", default="001.001.020")
    parser.add_argument("--limit", type=int, default=300, help="Entity questions per language (0 = all).")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-entity", action="store_true")
    parser.add_argument("--skip-tasks", action="store_true")
    args = parser.parse_args()

    allowed = bre.load_allowed_entities()
    if not args.skip_tasks:
        labels = load_labels(args.labels)
        if not labels:
            print(f"No intent.task label found in {args.labels}; pass --labels with the update result file.")
        else:
            bench_tasks(labels, load_questions(args.bank, set(labels)), allowed, args.model, args.workers)
    if not args.skip_entity:
        for lang in ("en", "fr"):
            bench_entity(args.truth_dir, args.run, lang, allowed, args.model, args.limit, args.workers)


if __name__ == "__main__":
    main()
