#!/usr/bin/env python3
"""Noise floor and calibration for the Jev answer-entity bench (FASTAPI-TEXT2SQL-282).

Reads the `--out` files that `bench-result-entity-jev.py` already writes. Makes no API
call, needs no key and no network: everything below is derived from runs already paid for.

Two questions, and they are not the same question
-------------------------------------------------
NOISE FLOOR. The sibling bench measures gpt-4o against itself because at temperature 0 a
model still disagrees with itself, and that number is what separates a real regression
from a coin flip. The Jev bench has only one side, so the floor comes from two runs
compared here, question by question. Two things vary independently and must be counted
separately, which is the point of this script:

  * the LABEL. If it moves, the classification itself is unstable.
  * the CONFIDENCE. If only this moves, the classification is stable and what wobbles is
    the number the synthesised abstention is built on. Those are very different problems:
    the first says the model is noisy, the second says our threshold is.

CALIBRATION. `confidence` is used as an abstention gate, so the only property that matters
is whether it predicts correctness. If it does, the operating threshold is read off this
table instead of being fished out of a sweep that moves between runs. If it does not, the
gate is built on a number that means nothing, and the margin between the top two
`probabilities` is the next thing to try.

Usage:
  uv run eval/bench-jev-analyse.py /shared/jev-a.json /shared/jev-b.json
  uv run eval/bench-jev-analyse.py /shared/jev-a.json            # calibration only
"""

import argparse
import collections
import json
import sys


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = {r["id"]: r for r in payload.get("results", []) if r.get("error") is None}
    return payload, rows


def noise_floor(a_meta, a_rows, b_meta, b_rows):
    shared = sorted(set(a_rows) & set(b_rows))
    print("=" * 78)
    print(f"NOISE FLOOR  |  {a_meta.get('model')} against itself  |  {len(shared)} questions")
    print("=" * 78)
    if not shared:
        print("\nNo question in common. Were both runs made on the same --run and --lang?")
        return

    label_moved = [i for i in shared if a_rows[i]["label"] != b_rows[i]["label"]]
    conf_moved = [i for i in shared
                  if abs(a_rows[i]["confidence"] - b_rows[i]["confidence"]) > 1e-9]
    deltas = sorted(abs(a_rows[i]["confidence"] - b_rows[i]["confidence"]) for i in shared)

    print(f"\n  labels that moved      : {len(label_moved):4d} / {len(shared)} "
          f"({100.0 * len(label_moved) / len(shared):.1f} %)")
    print(f"  confidences that moved : {len(conf_moved):4d} / {len(shared)} "
          f"({100.0 * len(conf_moved) / len(shared):.1f} %)")
    if deltas:
        mid = deltas[len(deltas) // 2]
        p90 = deltas[int(len(deltas) * 0.9)] if len(deltas) > 9 else deltas[-1]
        print(f"  confidence delta       : median {mid:.3f}, p90 {p90:.3f}, max {deltas[-1]:.3f}")

    print("\n  How to read this. A label floor near zero with a moving confidence means the")
    print("  classification is stable and the ABSTENTION GATE is what wobbles, so the")
    print("  equal-risk threshold jumping between runs is our instrument, not the model.")

    if label_moved:
        print(f"\n  The {len(label_moved)} question(s) whose label moved:")
        for i in label_moved[:20]:
            a, b = a_rows[i], b_rows[i]
            mark = ""
            if a["label"] == a["truth"] and b["label"] != b["truth"]:
                mark = "   <- A right, B wrong"
            elif b["label"] == b["truth"] and a["label"] != a["truth"]:
                mark = "   <- B right, A wrong"
            print(f"    #{i} truth={a['truth']}")
            print(f"        A={a['label']} ({a['confidence']:.2f})   "
                  f"B={b['label']} ({b['confidence']:.2f}){mark}")
            print(f"        {a['question'][:70]}")
        if len(label_moved) > 20:
            print(f"    ... and {len(label_moved) - 20} more")
    else:
        print("\n  No label moved at all: on this corpus the classification is reproducible.")


def calibration(meta, rows, bins):
    print()
    print("=" * 78)
    print(f"CALIBRATION  |  {meta.get('model')}  |  {len(rows)} questions")
    print("=" * 78)
    print("\nDoes `confidence` predict correctness? A calibrated model puts about 80 % of its")
    print("0.80 answers right. Read the two right-hand columns against each other.\n")

    edges = [i / bins for i in range(bins + 1)]
    buckets = collections.defaultdict(list)
    for row in rows.values():
        c = row["confidence"]
        idx = min(int(c * bins), bins - 1)
        buckets[idx].append(row["label"] == row["truth"])

    print(f"  {'confidence':>16}  {'n':>5}  {'mean conf':>10}  {'% right':>9}  {'gap':>7}")
    print(f"  {'-' * 16}  {'-' * 5}  {'-' * 10}  {'-' * 9}  {'-' * 7}")
    worst = None
    for idx in range(bins):
        hits = buckets.get(idx)
        if not hits:
            continue
        lo, hi = edges[idx], edges[idx + 1]
        confs = [r["confidence"] for r in rows.values()
                 if min(int(r["confidence"] * bins), bins - 1) == idx]
        mean_conf = sum(confs) / len(confs)
        share = sum(hits) / len(hits)
        gap = share - mean_conf
        flag = ""
        if len(hits) >= 30:
            if worst is None or abs(gap) > abs(worst[1]):
                worst = (f"{lo:.2f}-{hi:.2f}", gap)
        else:
            flag = "  (n<30, not decidable)"
        print(f"  {lo:>7.2f}-{hi:<8.2f}{len(hits):>5}  {mean_conf:>10.3f}  "
              f"{100 * share:>8.1f} %  {gap:>+7.1%}{flag}")

    print("\n  gap = observed correctness minus stated confidence. Positive means the model")
    print("  UNDERSTATES how right it is; negative means it overstates, which is the")
    print("  dangerous direction for a gate that trusts the number.")
    if worst:
        band, gap = worst
        print(f"\n  Largest gap on a decidable band: {band}, {gap:+.1%}.")
        if gap < -0.05:
            print("  Overconfident there: an abstention threshold set on this number lets")
            print("  through more errors than it promises.")
        elif gap > 0.05:
            print("  Underconfident there: the gate abstains on answers that were right,")
            print("  which is free but wasteful, and it is why the sweep looks pessimistic.")
        else:
            print("  Within five points, so the number is usable as a gate and the operating")
            print("  threshold can be read off this table rather than fished out of a sweep.")

    # The alternative gate, free to evaluate since probabilities are already stored.
    margins = []
    for row in rows.values():
        probs = row.get("probabilities") or {}
        if len(probs) >= 2:
            top = sorted(probs.values(), reverse=True)[:2]
            margins.append((top[0] - top[1], row["label"] == row["truth"]))
    if margins:
        margins.sort()
        half = len(margins) // 2
        low = sum(1 for _, ok in margins[:half] if ok) / max(half, 1)
        high = sum(1 for _, ok in margins[half:] if ok) / max(len(margins) - half, 1)
        print(f"\n  Alternative gate, the margin between the top two probabilities:")
        print(f"    narrow half: {100 * low:.1f} % right   wide half: {100 * high:.1f} % right")
        print("    A wide spread between these two means the margin separates right from")
        print("    wrong better than `confidence` does, and is the better gate.")
    else:
        print("\n  No per-label probabilities stored, so the margin gate cannot be evaluated.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="One or two --out JSON files.")
    parser.add_argument("--bins", type=int, default=10, help="Calibration bands.")
    args = parser.parse_args()

    if len(args.files) > 2:
        print("At most two files: one to calibrate, two to also measure the floor.")
        return 1

    a_meta, a_rows = load(args.files[0])
    if len(args.files) == 2:
        b_meta, b_rows = load(args.files[1])
        noise_floor(a_meta, a_rows, b_meta, b_rows)
    calibration(a_meta, a_rows, args.bins)
    return 0


if __name__ == "__main__":
    sys.exit(main())
