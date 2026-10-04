#!/usr/bin/env python3
"""FASTAPI-TEXT2SQL-309: replay the typographic rescue on every gate refusal already on disk.

Step 2 of the ticket's evaluation, and the cheapest one: no database, no ChromaDB, no LLM. Every
execution export carries the API trace, and since -224 a gate refusal prints the shortlist WITH
the compared text ("shortlist: movieid_76157_it d=0.361 'Il bell'Antonio', ..."). So each refusal
of a title resolver can be scored again, offline, exactly as the new second pass would score it:
same `fuzz.ratio`, same threshold, same `score_stopwords`, the configured normalisers on both
sides.

What it answers, per refusal: would the rescue have accepted a candidate, which one, and was it
the right one? "Right" is read from the row's own result assertion (`ID_MOVIE IN (...)`,
`ID_SERIE IN (...)`) when there is one; otherwise the verdict is `unknown` and the line is for a
human to read.

Two limits, stated so the figures are not over-read:
- The trace prints the first FIVE candidates of a ten-candidate shortlist, so this is a lower
  bound on rescues: a candidate at ranks 6 to 10 is invisible here and visible to the API.
- A document longer than 60 characters is printed truncated ("..."); its score cannot be
  reproduced, so it is skipped and counted.

    uv run eval/replay-rescue-309.py                       # $TEXT2SQL_EVAL_EXPORT_DIR, else the default below
    uv run eval/replay-rescue-309.py --exports-dir C:/Users/vaugo/Code/shared_data/text2sql-eval
    uv run eval/replay-rescue-309.py --runs 001.001.019_en_gpt-6-sol_gpt-6-sol_gpt-4o_re-gpt-6-luna
"""
import argparse
import collections
import glob
import io
import json
import os
import re
import sys

from rapidfuzz import fuzz

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import rapidfuzz_query  # noqa: E402

# Since 2026-10-04 the exports live outside the repository, an exact copy of the VPS share.
DEFAULT_EXPORTS = os.environ.get("TEXT2SQL_EVAL_EXPORT_DIR") or os.path.join(
    os.path.dirname(REPO), "shared_data", "text2sql-eval")

_REFUSAL_RE = re.compile(
    r"Entity resolution: \{\{(?P<key>(?P<type>[A-Za-z_]+?)\d*)\}\} -> rejected best embeddings candidate "
    r".*?min_fuzz_ratio=(?P<min>[\d.]+|None)\); shortlist: (?P<shortlist>.*)$")
_ITEM_RE = re.compile(r"(?P<id>[a-z]+id_\d+_[A-Za-z*]+) d=(?P<d>[\d.]+) '(?P<doc>.*?)'(?=, [a-z]+id_\d+_|$)")
_FALLBACK_RE = re.compile(r"Entity resolution: \{\{(?P<key>[A-Za-z_]+\d*)\}\} -> (?P<value>.*) \(raw fallback")
_ASSERT_RE = re.compile(r"Statement: (ID_MOVIE|ID_SERIE) IN \(([\d,\s]+)\)")


def load_config():
    config = json.load(io.open(os.path.join(REPO, "data/entity_resolution.json"), encoding="utf-8"))
    by_type = {}
    for entry in config:
        for strategy in entry.get("search_list") or []:
            if strategy.get("search_mode") == "embeddings" and strategy.get("rescue_normalizations"):
                by_type[entry["placeholder_prefix"]] = strategy
    return by_type


def score(sought, doc, strategy, normalizers):
    s, c = sought.strip().lower(), doc.strip().lower()
    sep = strategy.get("document_name_separator")
    if sep and sep in c:
        c = c.split(sep, 1)[0].strip()
    words = strategy.get("score_stopwords")
    if words:
        s = rapidfuzz_query.strip_franchise_words(s, words)
        c = rapidfuzz_query.strip_franchise_words(c, words)
    if normalizers:
        s = rapidfuzz_query.apply_rescue_normalizers(s, normalizers)
        c = rapidfuzz_query.apply_rescue_normalizers(c, normalizers)
    return fuzz.ratio(s, c) if c else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exports-dir", default=DEFAULT_EXPORTS)
    parser.add_argument("--runs", default="", help="comma-separated run folders (default: all)")
    args = parser.parse_args()

    strategies = load_config()
    if not strategies:
        sys.exit("No embeddings strategy declares rescue_normalizations in data/entity_resolution.json")
    root = os.path.join(args.exports_dir, "evaluation_execution")
    runs = [r.strip() for r in args.runs.split(",") if r.strip()] or sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(root, "*")) if os.path.isdir(p))

    totals = collections.Counter()
    distinct = {}
    for run in runs:
        for path in glob.glob(os.path.join(root, run, "*.json")):
            try:
                row = json.load(io.open(path, encoding="utf-8"))
            except Exception:
                totals["unreadable"] += 1
                continue
            out = row.get("api_output") or {}
            texts = [m.get("text", "") if isinstance(m, dict) else str(m) for m in out.get("messages") or []]
            expected = set()
            for _col, ids in _ASSERT_RE.findall((row.get("scoring") or {}).get("assertions_result_detailed") or ""):
                expected.update(i.strip() for i in ids.split(",") if i.strip())
            for i, text in enumerate(texts):
                m = _REFUSAL_RE.search(text)
                if not m or m.group("type") not in strategies:
                    continue
                strategy = strategies[m.group("type")]
                sought = None
                for later in texts[i + 1:i + 4]:
                    f = _FALLBACK_RE.search(later)
                    if f and f.group("key") == m.group("key"):
                        sought = f.group("value")
                        break
                if sought is None:
                    totals["refusal without its raw-fallback line"] += 1
                    continue
                totals["refusals"] += 1
                threshold = float(strategy["min_fuzz_ratio"])
                items = list(_ITEM_RE.finditer(m.group("shortlist")))
                chosen = None
                for item in items:
                    doc = item.group("doc")
                    if doc.endswith("..."):
                        totals["truncated candidates skipped"] += 1
                        continue
                    before = score(sought, doc, strategy, None)
                    if before >= threshold:
                        # The first pass would have accepted it: the refusal was made on another
                        # candidate or on ranks 6-10. Reported, never counted as a rescue.
                        totals["shortlist item already passing (trace inconsistency)"] += 1
                        continue
                    after = score(sought, doc, strategy, strategy["rescue_normalizations"])
                    if after >= threshold:
                        chosen = (item, before, after)
                        break
                if not chosen:
                    continue
                item, before, after = chosen
                found_id = item.group("id").split("_")[1]
                verdict = "unknown" if not expected else ("right" if found_id in expected else "WRONG")
                totals["rescued"] += 1
                totals["rescued, " + verdict] += 1
                key = (m.group("type"), sought, item.group("doc"))
                d = distinct.setdefault(key, {"found_id": found_id, "before": before, "after": after,
                                              "verdicts": collections.Counter(), "rows": set()})
                d["verdicts"][verdict] += 1
                d["rows"].add(f"{row.get('evaluation_id')}/{row.get('language')}")

    print(f"Runs read: {len(runs)} under {root}\n")
    for k in ("refusals", "rescued", "rescued, right", "rescued, WRONG", "rescued, unknown",
              "truncated candidates skipped", "shortlist item already passing (trace inconsistency)",
              "refusal without its raw-fallback line", "unreadable"):
        print(f"  {k}: {totals.get(k, 0)}")
    print("\nDistinct rescues (type | sought -> accepted | id | ratio before -> after | verdicts | rows)")
    for (etype, sought, doc), d in sorted(distinct.items()):
        verdicts = ", ".join(f"{v} {n}" for v, n in sorted(d["verdicts"].items()))
        print(f"  {etype} | {sought} -> {doc} | {d['found_id']} | {d['before']:.1f} -> {d['after']:.1f} "
              f"| {verdicts} | {', '.join(sorted(d['rows']))}")
    return 1 if totals.get("rescued, WRONG") else 0


if __name__ == "__main__":
    sys.exit(main())
