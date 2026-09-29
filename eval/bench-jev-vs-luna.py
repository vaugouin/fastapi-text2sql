#!/usr/bin/env python3
"""Jev against gpt-6-luna on the answer-entity classifier, question by question.

Offline: makes no API call, needs no key and no network. It joins two `--out` files that
the two benches already write, so the comparison costs nothing once both runs are paid:

  * a `bench-result-entity.py --out` file where one side (or both) is `gpt-6-luna`;
  * a `bench-result-entity-jev.py --out` file, and optionally a second Jev run for its
    noise floor.

Why a comparator and not a third bench
--------------------------------------
Luna was benched against gpt-4o (GPT-6-003) and Jev against gpt-4o (FASTAPI-TEXT2SQL-282),
never against each other. The "prefer Luna" recommendation of the 1.1.19 analysis rests on
that indirect comparison. Both benches already score the same ground truth (passed
executions of the same run, same vocabulary), so the direct comparison only needs the two
result files joined on the same questions. A third bench would pay both providers again
for answers already on disk.

How it reads, and why
---------------------
The two models do not fail the same way. Luna abstains natively (`unknown`, or a word
outside the set); Jev never does, and its abstention is synthesised from `confidence`
(see the Jev bench). A single accuracy figure would hide exactly that, so the comparison
is made AT EQUAL RISK: find the lowest Jev threshold whose confident errors do not exceed
Luna's, then compare how many correct answers each gives there. The same reading is
repeated on the decidable classes alone, where a label error is a real error rather than a
questionable ground truth (see the caveat about evaluation 948 in the sibling bench).

The two files must come from the same run prefix and language, or the ground truths differ
and nothing below means anything. The script refuses to compare them otherwise.

Usage:
  # From results already on disk (Luna of 2026-09-23, Jev of 2026-09-21)
  uv run eval/bench-jev-vs-luna.py \\
      --luna eval/data/bench/re-gpt4o-vs-gpt6luna-en-20260923.json \\
      --jev eval/data/bench/full-en-jev-plain.json

  # Fresh, pinned runs with both noise floors (see FASTAPI-TEXT2SQL-282 for the VPS commands)
  uv run eval/bench-jev-vs-luna.py --luna /shared/luna-floor-en.json \\
      --jev /shared/jev-en-a.json --jev-b /shared/jev-en-b.json --out /shared/jev-vs-luna-en.json

FASTAPI-TEXT2SQL-282.
"""

import argparse
import collections
import json
import statistics
import sys

DEFAULT_THRESHOLDS = [0.0, 0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
CORRECT, ABSTAINED, WRONG = "correct", "abstained", "wrong"


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def luna_side(payload, requested, model_hint):
    """Pick which side of a bench-result-entity file is Luna. Returns (side, is_floor)."""
    model_a, model_b = payload.get("model_a", ""), payload.get("model_b", "")
    if requested in ("a", "b"):
        return requested, model_a == model_b
    a_is, b_is = model_hint in model_a, model_hint in model_b
    if a_is and b_is:
        return "a", True
    if a_is or b_is:
        return ("a" if a_is else "b"), False
    raise SystemExit(f"Neither side of the Luna file is '{model_hint}' (A={model_a}, B={model_b}). "
                     f"Pass --luna-side a|b, or --luna-model.")


def jev_outcome(row, allowed_set, threshold):
    """The Jev bench's own rule: abstain below the threshold, then the three outcomes."""
    label, confidence = row.get("label") or "", float(row.get("confidence") or 0.0)
    if not label or label not in allowed_set or confidence < threshold:
        return ABSTAINED
    return CORRECT if label == row["truth"] else WRONG


def count(outcomes):
    tally = collections.Counter(outcomes)
    return tally[CORRECT], tally[ABSTAINED], tally[WRONG]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--luna", required=True, help="bench-result-entity.py --out file with a Luna side.")
    parser.add_argument("--luna-side", choices=["auto", "a", "b"], default="auto")
    parser.add_argument("--luna-model", default="luna", help="Substring naming the Luna side in auto mode.")
    parser.add_argument("--jev", required=True, help="bench-result-entity-jev.py --out file.")
    parser.add_argument("--jev-b", default=None, help="A second Jev run, for its noise floor.")
    parser.add_argument("--min-decidable", type=int, default=30)
    parser.add_argument("--thresholds", default=None, help="Comma-separated Jev thresholds to sweep.")
    parser.add_argument("--cases", type=int, default=15, help="Head-to-head cases listed per direction.")
    parser.add_argument("--out", default=None, help="Write the summary and the joined rows as JSON.")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    luna_payload, jev_payload = load(args.luna), load(args.jev)
    for key in ("lang", "run"):
        if luna_payload.get(key) != jev_payload.get(key):
            raise SystemExit(f"Refusing to compare: {key} differs (Luna file {luna_payload.get(key)!r}, "
                             f"Jev file {jev_payload.get(key)!r}). The ground truths would not be the same.")
    side, luna_is_floor = luna_side(luna_payload, args.luna_side, args.luna_model)
    luna_model = luna_payload.get(f"model_{side}", "?")
    other = "b" if side == "a" else "a"
    thresholds = DEFAULT_THRESHOLDS
    if args.thresholds:
        thresholds = sorted({float(t) for t in args.thresholds.split(",") if t.strip()})

    luna_rows = {r["id"]: r for r in luna_payload["results"]}
    jev_rows = {r["id"]: r for r in jev_payload["results"]}
    # The vocabulary is not stored in either file. Every label either model can produce
    # validly is a truth label somewhere in the set or a label Jev chose from CRITERIA,
    # which the Jev bench refuses to run unless it equals the application vocabulary.
    allowed_set = {r["truth"] for r in jev_rows.values() if r.get("truth")}
    allowed_set |= {r["label"] for r in jev_rows.values() if r.get("label")}

    joined, dropped = [], collections.Counter()
    for qid in sorted(set(luna_rows) | set(jev_rows)):
        luna, jev = luna_rows.get(qid), jev_rows.get(qid)
        if luna is None or jev is None:
            dropped["in one file only"] += 1
        elif not luna.get("truth") or luna["truth"] != jev.get("truth"):
            dropped["truth differs or missing"] += 1
        elif luna.get(f"{side}_error") or jev.get("error") is not None:
            dropped["a call errored"] += 1
        else:
            joined.append((luna, jev))
    total = len(joined)

    print("=" * 78)
    print(f"Jev vs Luna, answer-entity classifier  |  lang={jev_payload.get('lang')}  "
          f"run={jev_payload.get('run')}  |  {total} questions")
    print("=" * 78)
    print(f"Luna: {luna_model} (side {side.upper()} of {args.luna})")
    served = jev_payload.get("served_models")
    served_text = (", ".join(f"{k} x{v}" for k, v in served.items()) if served
                   else "not recorded (run made before 2026-09-29, on the moving alias)")
    print(f"Jev:  requested {jev_payload.get('model', '?')}, served by {served_text}")
    if dropped:
        print("Dropped: " + ", ".join(f"{n} {why}" for why, n in dropped.items()))
    if not total:
        print("\nNothing in common. No comparison is possible.")
        return 1

    class_n = collections.Counter(luna["truth"] for luna, _ in joined)
    decidable = {name for name, n in class_n.items() if n >= args.min_decidable}

    luna_out = [luna[f"{side}_outcome"] for luna, _ in joined]
    luna_c, luna_a, luna_w = count(luna_out)
    luna_wd = sum(1 for (luna, _), o in zip(joined, luna_out) if o == WRONG and luna["truth"] in decidable)

    print(f"\nLuna: {luna_c} correct, {luna_a} abstained, {luna_w} wrong "
          f"({luna_wd} on the decidable classes, n >= {args.min_decidable})")

    print(f"\nJev threshold sweep (abstention synthesised from confidence)")
    print(f"  {'threshold':>9s}{'correct':>9s}{'abstained':>11s}{'wrong':>7s}{'wrong, decidable':>18s}")
    sweep = []
    for threshold in thresholds:
        outs = [jev_outcome(jev, allowed_set, threshold) for _, jev in joined]
        c, a, w = count(outs)
        wd = sum(1 for (_, jev), o in zip(joined, outs) if o == WRONG and jev["truth"] in decidable)
        sweep.append({"threshold": threshold, "correct": c, "abstained": a, "wrong": w, "wrong_decidable": wd})
        print(f"  {threshold:>9.2f}{c:>9d}{a:>11d}{w:>7d}{wd:>18d}")

    def equal_risk(key, luna_value):
        fitting = [row for row in sweep if row[key] <= luna_value]
        return max(fitting, key=lambda row: (row["correct"], -row["threshold"])) if fitting else None

    print("\nAt equal risk (Jev's best threshold whose errors do not exceed Luna's)")
    verdict = {}
    for key, luna_value, label in (("wrong", luna_w, "all classes"),
                                   ("wrong_decidable", luna_wd, "decidable classes")):
        best = equal_risk(key, luna_value)
        if best is None:
            print(f"  {label:18s}: no swept threshold keeps Jev at or under Luna's {luna_value} errors")
            verdict[key] = None
            continue
        delta = best["correct"] - luna_c
        print(f"  {label:18s}: Jev @{best['threshold']:.2f} gives {best['correct']} correct against "
              f"Luna's {luna_c} ({delta:+d}), {best[key]} errors against {luna_value}, "
              f"abstaining {best['abstained']} times against {luna_a}")
        verdict[key] = {"threshold": best["threshold"], "jev_correct": best["correct"],
                        "luna_correct": luna_c, "delta": delta}

    anchor = verdict.get("wrong_decidable") or verdict.get("wrong")
    threshold = anchor["threshold"] if anchor else max(thresholds)
    jev_out = [jev_outcome(jev, allowed_set, threshold) for _, jev in joined]

    print(f"\nPer class, Jev @{threshold:.2f} (a class under n={args.min_decidable} gets no percentage)")
    print(f"  {'class':16s}{'n':>6s}{'Luna correct':>14s}{'Jev correct':>13s}{'Luna wrong':>12s}{'Jev wrong':>11s}")
    per_class = collections.defaultdict(lambda: [0, 0, 0, 0])
    for (luna, _), lo, jo in zip(joined, luna_out, jev_out):
        bucket = per_class[luna["truth"]]
        bucket[0] += lo == CORRECT
        bucket[1] += jo == CORRECT
        bucket[2] += lo == WRONG
        bucket[3] += jo == WRONG
    tail = []
    for name, n in class_n.most_common():
        lc, jc, lw, jw = per_class[name]
        if name in decidable:
            print(f"  {name:16s}{n:>6d}{100.0 * lc / n:>13.1f}%{100.0 * jc / n:>12.1f}%{lw:>12d}{jw:>11d}")
        else:
            tail.append((name, n, lw, jw))
    if tail:
        print(f"  not decidable: {len(tail)} classes, {sum(t[1] for t in tail)} questions; errors "
              f"Luna {sum(t[2] for t in tail)}, Jev {sum(t[3] for t in tail)}")

    def listing(title, wanted_luna, wanted_jev):
        cases = [(luna, jev) for (luna, jev), lo, jo in zip(joined, luna_out, jev_out)
                 if lo == wanted_luna and jo == wanted_jev]
        print(f"\n{title}: {len(cases)}")
        for luna, jev in cases[:args.cases]:
            print(f"  {luna['id']:>6}  truth={luna['truth']:12s} Luna={luna.get(side) or '-':12s} "
                  f"Jev={jev.get('label') or '-':12s} ({float(jev.get('confidence') or 0):.2f})  "
                  f"{luna['question'][:60]}")
        return len(cases)

    luna_only = listing("Luna right, Jev wrong", CORRECT, WRONG)
    jev_only = listing("Jev right, Luna wrong", WRONG, CORRECT)

    print("\nNoise floors (label flips between two runs of the same configuration)")
    floors = {}
    if luna_is_floor:
        flips = sum(1 for luna, _ in joined
                    if not luna.get(f"{other}_error") and (luna.get(side) or "") != (luna.get(other) or ""))
        floors["luna"] = flips
        print(f"  Luna: {flips} of {total}")
    else:
        print("  Luna: not measured (the Luna file is not a Luna-vs-Luna run)")
    if args.jev_b:
        second = {r["id"]: r for r in load(args.jev_b)["results"] if r.get("error") is None}
        pairs = [(jev, second[jev["id"]]) for _, jev in joined if jev["id"] in second]
        flips = sum(1 for one, two in pairs if one.get("label") != two.get("label"))
        floors["jev"] = flips
        print(f"  Jev:  {flips} of {len(pairs)}")
    else:
        print("  Jev:  not measured (pass --jev-b)")

    luna_seconds = [luna.get(f"{side}_seconds") for luna, _ in joined if luna.get(f"{side}_seconds")]
    if luna_seconds:
        print(f"\nLatency: Luna median {statistics.median(luna_seconds):.2f} s in its own run "
              f"(depends on that run's concurrency; see GPT-6-003). Jev: not recorded per question.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"lang": jev_payload.get("lang"), "run": jev_payload.get("run"),
                       "luna_model": luna_model, "jev_model": jev_payload.get("model"),
                       "jev_served_models": served, "questions": total,
                       "luna": {"correct": luna_c, "abstained": luna_a, "wrong": luna_w,
                                "wrong_decidable": luna_wd},
                       "jev_sweep": sweep, "equal_risk": verdict, "noise_floors": floors,
                       "luna_right_jev_wrong": luna_only, "jev_right_luna_wrong": jev_only},
                      handle, ensure_ascii=False, indent=2)
        print(f"\nWritten: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
