#!/usr/bin/env python3
"""Count, and classify, the empty results the no-results complex retry declines to rescue.

Why this exists (FASTAPI-TEXT2SQL-156). Since 1.1.17, `can_retry_no_results` in `main.py`
ends with `and bool(ambiguous_question_for_text2sql)`. The intent is right: a well-formed
query that legitimately returns 0 rows must not be masked by a memory-fabricated retry.
The signal is wrong: `ambiguous` is only 1 when a `{{placeholder}}` SURVIVES in the final
SQL, and the raw-fallback branch removes the placeholder by substituting the user's own
words. So the flag drops to 0 at the exact moment resolution failed, and the guard blocks
a recoverable empty. The 1.1.17 evaluation measured the cost: complex invocations
collapsed 47 to 4, `empty_result` failures tripled.

Before widening the trigger, measure. This reads the retained usage logs and splits every
blocked empty into three buckets, because they do not have the same fix:

  RESOLUTION_FAILED   at least one entity ended in "(raw fallback)": it had a configured
                      resolver and no strategy matched, so its words were copied verbatim
                      into the SQL. Recoverable. This is what widening the trigger catches.

  NOTHING_EXTRACTED   the extraction returned no entity at all, so the question was never
                      anonymized. Also recoverable, but a raw-fallback count would NOT see
                      it: there is no entity to fall back. Needs its own condition.

  AUTHORITATIVE       every extracted entity resolved to a real row. The empty is the truth
                      ("series directed by Chris Carter"). Correctly blocked; must stay so.

Reads loose `*_text2sql_post_*.json` files and, with --archives, the monthly tarballs that
archive-logs.sh produces under `logs/archive/<YYYYMM>.tar.gz`.

Usage:
  python analyze-complex-retry-logs.py                      # ./logs, loose files
  python analyze-complex-retry-logs.py --archives           # include the monthly tarballs
  python analyze-complex-retry-logs.py --by-version         # split the report per API version
  python analyze-complex-retry-logs.py --show 15            # print the blocked questions
  python analyze-complex-retry-logs.py /home/debian/docker/fastapi-text2sql-blue/logs
"""
import argparse
import glob
import json
import os
import re
import sys
import tarfile
from collections import Counter, defaultdict

GUARD_MESSAGE = "treating the empty result as authoritative"
RAW_FALLBACK_MARK = "(raw fallback)"
FILENAME_RE = re.compile(r"^(\d{8})-\d{6}_text2sql_post_([0-9.]+)_[0-9a-f]{32}\.json$")


def iter_logs(logs_dir: str, include_archives: bool):
    """Yield (filename, parsed json) for every text2sql usage log found."""
    for path in sorted(glob.glob(os.path.join(logs_dir, "*_text2sql_post_*.json"))):
        name = os.path.basename(path)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                yield name, json.load(handle)
        except Exception as e:
            print(f"  (skipped {name}: {e})", file=sys.stderr)

    if not include_archives:
        return
    for archive in sorted(glob.glob(os.path.join(logs_dir, "archive", "*.tar.gz"))):
        try:
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    name = os.path.basename(member.name)
                    if not member.isfile() or "_text2sql_post_" not in name:
                        continue
                    handle = tar.extractfile(member)
                    if handle is None:
                        continue
                    try:
                        yield name, json.loads(handle.read().decode("utf-8"))
                    except Exception as e:
                        print(f"  (skipped {name} in {os.path.basename(archive)}: {e})", file=sys.stderr)
        except Exception as e:
            print(f"  (skipped archive {os.path.basename(archive)}: {e})", file=sys.stderr)


def classify(response: dict) -> str:
    """Return the bucket a blocked empty result belongs to."""
    extraction = response.get("entity_extraction")
    keys = [k for k in (extraction or {}) if k != "question"] if isinstance(extraction, dict) else []
    if not keys:
        return "NOTHING_EXTRACTED"
    for message in response.get("messages") or []:
        if RAW_FALLBACK_MARK in (message.get("text") or ""):
            return "RESOLUTION_FAILED"
    return "AUTHORITATIVE"


def main():
    """Walk the logs, tally the outcomes and print the report."""
    parser = argparse.ArgumentParser(description="Measure the no-results complex-retry guard (FASTAPI-TEXT2SQL-156).")
    parser.add_argument("logs_dir", nargs="?", default="logs", help="Log directory (default: ./logs).")
    parser.add_argument("--archives", action="store_true", help="Also read logs/archive/<YYYYMM>.tar.gz.")
    parser.add_argument("--by-version", action="store_true", help="Split every figure per API version.")
    parser.add_argument("--show", type=int, default=0, help="Print up to N blocked questions per bucket.")
    args = parser.parse_args()

    if not os.path.isdir(args.logs_dir):
        print(f"No such directory: {args.logs_dir}")
        return 1

    per_version = defaultdict(Counter)
    samples = defaultdict(list)
    dates = []

    for name, payload in iter_logs(args.logs_dir, args.archives):
        request = payload.get("request") or {}
        response = payload.get("response") or {}
        version = response.get("api_version") or "unknown"
        counts = per_version[version]
        counts["calls"] += 1

        match = FILENAME_RE.match(name)
        if match:
            dates.append(match.group(1))

        if not request.get("complex_question_processing"):
            counts["complex_disabled"] += 1
            continue
        counts["complex_enabled"] += 1

        if response.get("complex_model_used"):
            counts["complex_used"] += 1

        rows = response.get("result")
        if (response.get("page") or 1) != 1 or not isinstance(rows, list) or rows:
            continue
        counts["empty_page1"] += 1

        blocked = any(GUARD_MESSAGE in (m.get("text") or "") for m in (response.get("messages") or []))
        if not blocked:
            counts["empty_not_blocked"] += 1
            continue

        bucket = classify(response)
        counts["blocked"] += 1
        counts[bucket] += 1
        if args.show:
            samples[(version, bucket)].append(request.get("question") or "")

    if not per_version:
        print("No text2sql log found.")
        return 1

    if dates:
        print(f"Period: {min(dates)} to {max(dates)}")
    versions = sorted(per_version) if args.by_version else ["ALL"]
    if not args.by_version:
        merged = Counter()
        for counts in per_version.values():
            merged.update(counts)
        per_version = {"ALL": merged}

    for version in versions:
        c = per_version[version]
        print()
        print(f"=== {version} ===")
        print(f"  text2sql calls                        {c['calls']:>6}")
        print(f"    complex mode off (cannot trigger)   {c['complex_disabled']:>6}")
        print(f"    complex mode on                     {c['complex_enabled']:>6}")
        print(f"      complex model actually used       {c['complex_used']:>6}")
        print(f"      empty result on page 1            {c['empty_page1']:>6}")
        print(f"        retried (guard let it through)  {c['empty_not_blocked']:>6}")
        print(f"        BLOCKED by the guard            {c['blocked']:>6}")
        if c["blocked"]:
            print(f"          resolution failed (recoverable)   {c['RESOLUTION_FAILED']:>6}  <- widening the trigger catches these")
            print(f"          nothing extracted (recoverable)   {c['NOTHING_EXTRACTED']:>6}  <- needs its own condition")
            print(f"          authoritative (correctly blocked) {c['AUTHORITATIVE']:>6}  <- must stay blocked")
        for bucket in ("RESOLUTION_FAILED", "NOTHING_EXTRACTED", "AUTHORITATIVE"):
            shown = samples.get((version, bucket), [])[: args.show]
            for question in shown:
                print(f"          [{bucket}] {question[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
