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

A fourth column cuts ACROSS those three (FASTAPI-TEXT2SQL-211): "collapse" counts the
empties whose SQL pins the person being LISTED to a person NAMED in the question, a shape
that can only ever return that named person. Those are query defects, not answers, and
signal (d) of the guard now reopens them. The column exists to keep that widening honest:
run it before and after a prompt change and watch how many AUTHORITATIVE empties it moves.
The predicate is imported from sql_shapes.py, the same one main.py runs, on purpose.

A fifth column counts `dropped_clause` (FASTAPI-TEXT2SQL-220): the generator declaring that
its SQL does not implement the whole question, typically because a filter would have needed a
placeholder entity extraction never produced. Two figures, and they answer different questions.
Over ALL calls it says how often the phenomenon happens at all, which is the measurement -220
asks for. Among BLOCKED empties it says how many of them come from a query that never asked the
whole question, which is a different animal from an authoritative empty and is the structural
signal -207 has been asking for.

A sixth column needs no new field and reads the WHOLE history (FASTAPI-TEXT2SQL-220): among the
empties never evaluated because a `{{placeholder}}` survived into the final SQL, how many of
those placeholders were never produced by entity extraction at all. A surviving placeholder whose
key IS in the extraction is a resolution that failed; a surviving placeholder whose key is NOT
there was invented by the generator, and no resolver could ever have filled it. The message
`entity.py` already writes names the survivors, and the response already carries the extraction
keys, so the split is computable on every log ever written, back to 2025.

**Read a zero carefully.** `dropped_clause` only exists from the version that shipped it, so a
log written before carries no such key and a zero would be indistinguishable from "never
happens". The report therefore prints how many responses carry the field at all: when that line
reads 0, the column below it means nothing yet. Use --by-version to see the field appear.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sql_shapes

# entity.py writes: "Unresolved placeholders remain in SQL after entity resolution: {{A}}, {{B}}"
# and truncates past ten with ", ...". Parsing it costs nothing and works on archived logs.
UNRESOLVED_MARK = "Unresolved placeholders remain in SQL after entity resolution:"
PLACEHOLDER_RE = re.compile(r"\{\{([^}]+)\}\}")

GUARD_MESSAGE = "treating the empty result as authoritative"
RETRY_MESSAGE = "SQL query returned 0 rows; attempting to simplify"
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


def undeclared_placeholders(response: dict):
    """Placeholders that survived into the SQL although extraction never produced them.

    FASTAPI-TEXT2SQL-220. Returns (survivors, undeclared). A survivor whose key is among the
    extraction keys is a resolution that found nothing; one whose key is absent was invented by
    the generator, and no resolver could have filled it because no value was ever produced.
    """
    survivors = []
    for message in response.get("messages") or []:
        text = message.get("text") or ""
        if UNRESOLVED_MARK in text:
            survivors = PLACEHOLDER_RE.findall(text.split(UNRESOLVED_MARK, 1)[1])
            break
    if not survivors:
        return [], []
    extraction = response.get("entity_extraction")
    keys = {k for k in (extraction or {}) if k != "question"} if isinstance(extraction, dict) else set()
    return survivors, [p for p in survivors if p not in keys]


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
    undeclared_samples = defaultdict(list)
    # Kept aside from per_version, which gets merged into "ALL": this one must survive the
    # merge to answer "is the defect recent, or already fixed?" in a single run.
    version_split = defaultdict(Counter)
    dates = []

    for name, payload in iter_logs(args.logs_dir, args.archives):
        request = payload.get("request") or {}
        response = payload.get("response") or {}
        version = response.get("api_version") or "unknown"
        counts = per_version[version]
        counts["calls"] += 1
        version_split[version]["calls"] += 1

        # FASTAPI-TEXT2SQL-220. Counted here, before every `continue` below, because a dropped
        # clause is a property of the generation and not of the empty-result path: it matters
        # just as much on a call that returned rows, where it means the user got a WIDER answer
        # than they asked for without being told.
        if "dropped_clause" in response:
            counts["dropped_field_present"] += 1
            if (response.get("dropped_clause") or "").strip():
                counts["dropped_any"] += 1

        # FASTAPI-TEXT2SQL-220, retroactive: needs no new field, so it reads the whole history.
        survivors, undeclared = undeclared_placeholders(response)
        if survivors:
            counts["placeholder_survived"] += 1
            if undeclared:
                counts["placeholder_undeclared"] += 1
                version_split[version]["undeclared"] += 1
                if args.show:
                    undeclared_samples[version].append(
                        (version, request.get("question") or "", ", ".join(undeclared))
                    )
            else:
                counts["placeholder_unresolved"] += 1

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

        texts = [m.get("text") or "" for m in (response.get("messages") or [])]
        if any(RETRY_MESSAGE in text for text in texts):
            counts["retry_fired"] += 1

        blocked = any(GUARD_MESSAGE in text for text in texts)
        if not blocked:
            # No guard message means the execution block was never entered: it is itself
            # gated on `not ambiguous_question_for_text2sql`, so an ambiguous question skips
            # the query, the retry AND the message. Not "let through", never evaluated.
            counts["empty_never_evaluated"] += 1
            continue

        bucket = classify(response)
        counts["blocked"] += 1
        counts[bucket] += 1
        if bucket == "RESOLUTION_FAILED":
            version_split[version]["resolution_failed"] += 1
        if sql_shapes.detect_person_role_collapse(
            response.get("sql_query") or "", response.get("result_entity") or ""
        ):
            counts["collapse"] += 1
            counts["collapse_" + bucket] += 1
        # FASTAPI-TEXT2SQL-220 / -207: an empty whose query never asked the whole question.
        # Its emptiness cannot be authoritative for a question that was never posed in full.
        if (response.get("dropped_clause") or "").strip():
            counts["dropped_blocked"] += 1
            counts["dropped_" + bucket] += 1
        if args.show:
            samples[(version, bucket)].append((version, request.get("question") or ""))

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
        # The samples are keyed by the REAL version while the counts are merged under "ALL",
        # so without this they are looked up under a key nothing ever wrote and --show prints
        # nothing at all. It had never worked without --by-version, for the original buckets
        # as much as for the undeclared ones: a flag that silently does nothing is worse than
        # an absent flag, because it answers "there are none" to a question never asked.
        merged_samples = defaultdict(list)
        for (version_key, bucket), questions in samples.items():
            merged_samples[("ALL", bucket)].extend(questions)
        samples = merged_samples
        merged_undeclared = defaultdict(list)
        for version_key, rows in undeclared_samples.items():
            merged_undeclared["ALL"].extend(rows)
        undeclared_samples = merged_undeclared

    for version in versions:
        c = per_version[version]
        print()
        print(f"=== {version} ===")
        print(f"  text2sql calls                        {c['calls']:>6}")
        print(f"    complex mode off (cannot trigger)   {c['complex_disabled']:>6}")
        print(f"    complex mode on                     {c['complex_enabled']:>6}")
        print(f"      complex model actually used       {c['complex_used']:>6}")
        print(f"      dropped a clause (any outcome)    {c['dropped_any']:>6}  <- answer wider than the question")
        print(f"        responses carrying the field    {c['dropped_field_present']:>6}  <- if 0, the line above is meaningless")
        print(f"      empty result on page 1            {c['empty_page1']:>6}")
        print(f"        never evaluated (ambiguous=1)   {c['empty_never_evaluated']:>6}")
        print(f"          a placeholder survived the SQL  {c['placeholder_survived']:>6}")
        print(f"            extraction HAD the key        {c['placeholder_unresolved']:>6}  <- resolution found nothing")
        print(f"            extraction NEVER had it       {c['placeholder_undeclared']:>6}  <- generator invented it, -220")
        if not args.by_version and (c["placeholder_undeclared"] or c["RESOLUTION_FAILED"]):
            print("          per API version (undeclared / resolution-failed, per 1000 calls):")
            for v in sorted(version_split):
                u = version_split[v]["undeclared"]
                r = version_split[v]["resolution_failed"]
                n = version_split[v]["calls"] or 1
                if u or r:
                    print(f"            {v:<12} {u:>4} / {r:>4}   on {n:>6} calls"
                          f"   ({u * 1000.0 / n:>5.2f} / {r * 1000.0 / n:>5.2f} per 1000)")
        print(f"        reached the guard, BLOCKED      {c['blocked']:>6}")
        print(f"        no-results retry actually fired {c['retry_fired']:>6}  <- 0 means the retry is dead code")
        if c["blocked"]:
            print(f"          resolution failed (recoverable)   {c['RESOLUTION_FAILED']:>6}  <- widening the trigger catches these")
            print(f"          nothing extracted (recoverable)   {c['NOTHING_EXTRACTED']:>6}  <- needs its own condition")
            print(f"          authoritative (correctly blocked) {c['AUTHORITATIVE']:>6}  <- must stay blocked")
            print(f"          person-role collapse (any bucket)  {c['collapse']:>6}  <- signal (d) reopens these")
            print(f"            of which authoritative           {c['collapse_AUTHORITATIVE']:>6}  <- the widening's real cost")
            print(f"          dropped a clause (any bucket)      {c['dropped_blocked']:>6}  <- the query never asked the whole question")
            print(f"            of which authoritative           {c['dropped_AUTHORITATIVE']:>6}  <- empties -207 could reopen on a certain signal")
        for sample_version, question, placeholders in undeclared_samples.get(version, [])[: args.show]:
            print(f"          [UNDECLARED {sample_version} {placeholders}] {question[:60]}")
        for bucket in ("RESOLUTION_FAILED", "NOTHING_EXTRACTED", "AUTHORITATIVE"):
            shown = samples.get((version, bucket), [])[: args.show]
            for sample_version, question in shown:
                print(f"          [{bucket} {sample_version}] {question[:75]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
