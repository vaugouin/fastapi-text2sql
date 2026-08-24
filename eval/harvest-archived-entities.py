#!/usr/bin/env python3
"""Harvest extracted entity values from the archived API logs, into a local cache.

WHY A SEPARATE SCRIPT (FASTAPI-TEXT2SQL-206)
The bench needs many real values per entity type, and the thin types are exactly the ones it
cannot calibrate: the local corpus holds 3 Network_name values against 363 Person_name. Months
of execution logs sit on the VPS share, 23530 files across the two colours, which is two orders
of magnitude more matter.

That share reads at about 13 files per second, so a full pass takes half an hour. Harvesting is
therefore split out and cached: it runs once, in the background, and the bench then reads a local
file in milliseconds. Re-run it when the archive has grown, not on every bench.

WHAT IT KEEPS
Only the placeholder values from the entity-extraction step, with how often each was seen. No
question text, no SQL, no result: the bench needs values, and a smaller cache is a cache that
gets used. Values are counted, because a value seen four hundred times says something a hapax
does not, and the bench can weight or sample accordingly.

A regex is used rather than json.load, on purpose. Parsing 23530 JSON documents to reach one
small dictionary in each is the expensive way to do it, and the placeholder shape is rigid
enough that a pattern reads it safely. Malformed or truncated files degrade to "no match"
instead of raising, which is the right behaviour on an archive nobody is going to repair.

Usage:
  uv run eval/harvest-archived-entities.py
  uv run eval/harvest-archived-entities.py --dirs "T:/.../blue/logs,T:/.../green/logs"
  uv run eval/harvest-archived-entities.py --limit 500        # a quick sample, for a smoke test
"""
import argparse
import collections
import glob
import io
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_DIRS = [
    "T:/prive/dev.ovh/ovh-pv7/home/debian/docker/fastapi-text2sql-blue/logs",
    "T:/prive/dev.ovh/ovh-pv7/home/debian/docker/fastapi-text2sql-green/logs",
    os.path.join(REPO, "logs"),
]

# The fourteen placeholders that reach a scored resolver. Closed-vocabulary and regex
# placeholders resolve by exact lookup and produce no score, so they are of no use here.
SCORED_TYPES = {
    "Person_name", "Movie_title", "Serie_title", "Company_name", "Network_name",
    "Topic_name", "List_name", "Award_name", "Nomination_name", "Collection_name",
    "Movement_name", "Location_name", "Group_name", "Death_name",
}

# Matches   "Network_name1": "HBO"   inside the entity-extraction payload. The trailing digit is
# optional because a single occurrence is sometimes emitted unnumbered.
PAIR = re.compile(r'"([A-Z][A-Za-z]+_[a-z]+)\d*"\s*:\s*"((?:[^"\\]|\\.){1,160})"')


def harvest(dirs, limit):
    counts = collections.defaultdict(collections.Counter)
    seen_files = 0
    started = time.time()
    for directory in dirs:
        if not os.path.isdir(directory):
            print(f"[skip] {directory} injoignable", flush=True)
            continue
        files = sorted(glob.glob(os.path.join(directory, "*.json")))
        if limit:
            files = files[:limit]
        print(f"[scan] {directory} : {len(files)} fichiers", flush=True)
        for path in files:
            try:
                text = io.open(path, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            seen_files += 1
            for key, value in PAIR.findall(text):
                if key not in SCORED_TYPES:
                    continue
                try:
                    value = json.loads('"' + value + '"')
                except Exception:
                    pass
                value = (value or "").strip()
                # A value carrying a brace is a placeholder echoed back, not a real value.
                if value and "{{" not in value:
                    counts[key][value] += 1
            if seen_files % 500 == 0:
                rate = seen_files / max(time.time() - started, 0.001)
                print(f"[scan] {seen_files} fichiers, {rate:.0f}/s", flush=True)
    return counts, seen_files


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dirs", default="", help="comma-separated directories (default: both VPS archives plus logs/)")
    parser.add_argument("--limit", type=int, default=0, help="files per directory, 0 = all")
    parser.add_argument("--out", default=os.path.join(REPO, "eval/data/archived-entity-values.json"))
    args = parser.parse_args()

    dirs = [d.strip() for d in args.dirs.split(",") if d.strip()] or DEFAULT_DIRS
    counts, seen_files = harvest(dirs, args.limit)

    payload = {
        "source_dirs": dirs,
        "files_read": seen_files,
        "values": {etype: dict(counter.most_common()) for etype, counter in sorted(counts.items())},
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(f"\n{seen_files} fichiers lus")
    print("valeurs distinctes par type :")
    for etype in sorted(counts):
        print("   %-18s %5d" % (etype, len(counts[etype])))
    print(f"\nEcrit dans {args.out}")


if __name__ == "__main__":
    sys.exit(main())
