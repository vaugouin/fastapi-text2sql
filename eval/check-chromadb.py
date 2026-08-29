#!/usr/bin/env python3
"""Consistency checks on the ChromaDB store that entity resolution reads.

WHY THIS FILE EXISTS
--------------------
Entity resolution depends on an agreement between two repositories that nothing verifies.

`embedding-update` decides what text is indexed. For several entities it writes
`name + ": " + description`, because the description helps the semantic search a great deal.
`fastapi-text2sql` decides, per entity in `data/entity_resolution.json`, whether to cut the
document at `document_name_separator` before scoring it lexically. When it does not cut, the
confidence gate compares the name the user typed against the WHOLE document, description
included, and a long description drowns the name.

Neither file is wrong on its own. Their DISAGREEMENT is. That is what makes it invisible:
measured on 2026-08-29, "flamenco trilogy" scored 20 against a threshold of 72 facing the full
document and 80 facing the name alone, and the collections had been indexed with descriptions
for two months without the separator ever being declared. No signal, no error, an empty answer
where the row existed all along.

This script measures WHAT IS IN THE STORE rather than what the source code suggests. That is
deliberate. Two checks written this week failed because they modelled the thing they were
checking instead of observing it: a PHP unescaper written by hand disagreed with PHP on the one
sequence that mattered and certified a broken page, and a duplicate detector written with
`fuzz.ratio` found none of the three duplicates because it reproduced the very defect it was
hunting. A check that reads the real store cannot inherit the bugs of the code that fills it.

SCOPE
-----
This is a HOME FOR CHROMADB CHECKS, not a one-shot script. Today it carries two. Adding a third
should take a function and a decorator, not a new file. See "ADDING A CHECK" below.

Runs on the VPS, where ChromaDB lives. It reads only: no collection is created, modified or
deleted, and no embedding is computed, so no OpenAI key is needed.

Philippe also keeps the `embedding-query` repository for ad-hoc exploration of these same
collections. The division of labour: `embedding-query` is for asking open questions of the
store, this file is for the answers that must stay true and are therefore worth asserting.

USAGE
-----
    uv run eval/check-chromadb.py                          # every check
    uv run eval/check-chromadb.py --list                   # what is available
    uv run eval/check-chromadb.py --check separator-agreement
    uv run eval/check-chromadb.py --sample 2000            # bigger sample, slower

On the VPS, in Docker, following the pattern of eval/README.md:

    docker run -it --rm --network="host" \
      --env-file /home/debian/docker/fastapi-text2sql-blue/.env \
      --name fastapi-text2sql-check \
      -v /home/debian/docker/fastapi-text2sql-blue:/app \
      fastapi-text2sql-blue-app \
      python eval/check-chromadb.py

The -v mount is REQUIRED, and rebuilding is not an alternative. Neither image can run this
script alone: the API image installs `chromadb` but its Dockerfile copies only `*.py` and
`./data/`, so `eval/` never enters it; the evaluator image copies `eval/` to `/app` but has
neither `chromadb` nor `data/`. Mounting the checkout over `/app` gives the API image both the
script and a `data/entity_resolution.json` read from disk rather than frozen at build time.
Mount the colour currently serving, since its configuration is the one in force.

Exit code is 1 when at least one ERROR is reported, 0 otherwise, so it can gate a deployment.

ADDING A CHECK
--------------
Write a function decorated with `@check("my-name", "one line summary")`. It receives a `Context`
(the ChromaDB client, the resolution config, the sample size) and returns a list of `Finding`.
Report the NUMBERS you measured in `evidence`, not only a verdict: a reader must be able to
disagree with a threshold without rerunning anything. Keep thresholds as module constants with
the measurement that justifies them written next to the value.
"""
import argparse
import json
import os
import sys
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# `chromadb` is imported inside main(), after --list has had its chance to answer. Importing it
# at module level made `--list` fail on a workstation whose opentelemetry install is broken,
# which is absurd for a flag that only prints two lines and touches no store.

# --------------------------------------------------------------------------------------------
# Thresholds. Each one carries the measurement that set it, so it can be argued with.
# --------------------------------------------------------------------------------------------

# The separator the indexer uses. `embedding-update` writes `strfulldesc += ": " + stroverview`
# in a single place, so this is a property of the producer, not a per-entity choice.
INDEXER_SEPARATOR = ": "

# A tail longer than this reads as a DESCRIPTION, not as a subtitle. Measured 2026-08-29:
# "Star Trek: The Next Generation" has a 19-character tail, while the descriptions appended to
# T_WC_T2S_LIST average 105 characters and the flamenco one runs to 80. The distinction matters
# because a name may legitimately contain the separator, which is exactly why cutting is opt-in
# per entity and must never be turned on globally.
DESCRIPTION_MIN_TAIL = 40

# Share of sampled documents carrying such a tail above which the entity is judged to index
# descriptions. Set low on purpose: at one document in ten, one resolution in ten meets the
# defect, which is already a production problem and not a curiosity.
SUSPECT_SHARE = 0.10

# A share alone is not enough, and the first real run proved it. On 2026-08-29 `lists` held 23
# documents, 2 of them carrying a description, and reported 9%, ONE POINT under the bar. The
# check would have missed the very defect it was written for: on a small collection each
# document weighs 4.3 points and a proportion stops being able to decide.
#
# Hence a second, softer band. A handful of described documents warns even when the share is
# low, and the floor of two keeps it quiet on the large catalogues where a long subtitle is a
# legitimate accident. Measured the same day: `movies` carried 3 long tails out of 1000, which
# is 0.3% and stays silent, while `lists` at 8.7% speaks.
WARN_MIN_COUNT = 2
WARN_MIN_SHARE = 0.02

DEFAULT_SAMPLE = 1000

# --------------------------------------------------------------------------------------------

Finding = namedtuple("Finding", "level target message evidence")
Context = namedtuple("Context", "client strategies sample")

CHECKS = {}


def check(name, summary):
    """Register a check under `name`. The summary is what --list prints."""
    def _register(fn):
        CHECKS[name] = (summary, fn)
        return fn
    return _register


def load_embeddings_strategies():
    """Every entity-resolution strategy that reads ChromaDB, keyed by collection name.

    Strategies in `rapidfuzz` mode never touch a document, so they are not this script's
    business. A placeholder can carry several strategies (Collection_name has one of each),
    which is why the config is walked rather than indexed by placeholder.
    """
    cfg = json.loads((ROOT / "data" / "entity_resolution.json").read_text(encoding="utf-8"))
    out = {}
    for entry in cfg:
        for strategy in entry.get("search_list") or []:
            if strategy.get("search_mode") != "embeddings":
                continue
            name = strategy.get("collection")
            if name:
                out[name] = {"placeholder": entry.get("placeholder_prefix"), "config": strategy}
    return out


def sample_documents(client, name, limit):
    """Fetch up to `limit` documents. Returns None when the collection cannot be read.

    `get()` retrieves by id and computes no embedding, so the collection is opened without an
    embedding function and no OpenAI key is required.
    """
    try:
        collection = client.get_collection(name=name)
    except Exception:
        return None
    try:
        got = collection.get(limit=limit, include=["documents"])
    except Exception:
        return None
    return [d for d in (got.get("documents") or []) if isinstance(d, str)]


# --------------------------------------------------------------------------------------------
# Check 1: the disagreement this script was written for.
# --------------------------------------------------------------------------------------------

@check("separator-agreement",
       "documents indexed as 'name: description' must declare document_name_separator")
def check_separator_agreement(ctx):
    findings = []
    for name, meta in sorted(ctx.strategies.items()):
        declared = meta["config"].get("document_name_separator")
        docs = sample_documents(ctx.client, name, ctx.sample)
        if docs is None:
            findings.append(Finding("WARN", name, "collection unreadable, skipped", ""))
            continue
        if not docs:
            findings.append(Finding("WARN", name, "no document sampled, nothing to judge", ""))
            continue

        probe = declared or INDEXER_SEPARATOR
        with_sep = 0
        with_long_tail = 0
        tails = []
        # Kept so an accusation can SHOW its evidence. The store alone cannot tell a colon that
        # introduces a description from one that belongs to the name ("Star Trek: The Next
        # Generation"), only tail length separates them, and that is a heuristic. Printing the
        # offending documents lets a human settle in one glance what no threshold can.
        offenders = []
        for doc in docs:
            if probe not in doc:
                continue
            with_sep += 1
            tail = doc.split(probe, 1)[1].strip()
            tails.append(len(tail))
            if len(tail) >= DESCRIPTION_MIN_TAIL:
                with_long_tail += 1
                if len(offenders) < 3:
                    offenders.append(doc[:110] + ("..." if len(doc) > 110 else ""))

        total = len(docs)
        long_share = with_long_tail / total
        median_tail = sorted(tails)[len(tails) // 2] if tails else 0
        evidence = (f"{total} sampled, {with_sep} contain {probe!r}, "
                    f"{with_long_tail} with a tail >= {DESCRIPTION_MIN_TAIL} chars "
                    f"({long_share:.0%}), median tail {median_tail}")

        shown = "".join(f"\n         e.g. {o}" for o in offenders)
        if not declared and long_share >= SUSPECT_SHARE:
            findings.append(Finding(
                "ERROR", name,
                "indexes descriptions but declares no document_name_separator, so the gate "
                "scores the typed name against the description too",
                evidence + shown))
        elif (not declared and with_long_tail >= WARN_MIN_COUNT
                and long_share >= WARN_MIN_SHARE):
            findings.append(Finding(
                "WARN", name,
                f"{with_long_tail} document(s) carry a description while no "
                "document_name_separator is declared; under the error bar, but each one is a "
                "resolution that can fail",
                evidence + shown))
        elif declared and with_sep == 0:
            # Not a production defect, but it means the producer stopped appending descriptions
            # while the consumer still expects them. Left standing, it is a false landmark for
            # whoever reads the config next.
            findings.append(Finding(
                "WARN", name,
                f"declares document_name_separator {declared!r} but no sampled document "
                "contains it, the declaration is dead",
                evidence))
        else:
            state = f"declared {declared!r}" if declared else "no description indexed"
            findings.append(Finding("OK", name, state, evidence))
    return findings


# --------------------------------------------------------------------------------------------
# Check 2: a strategy pointing at nothing resolves nothing, silently.
# --------------------------------------------------------------------------------------------

@check("collection-populated",
       "every embeddings strategy must point at a collection that exists and holds documents")
def check_collection_populated(ctx):
    try:
        present = {c.name if hasattr(c, "name") else str(c)
                   for c in ctx.client.list_collections()}
    except Exception as exc:                                        # noqa: BLE001
        return [Finding("ERROR", "-", f"cannot list collections: {exc}", "")]

    findings = []
    for name, meta in sorted(ctx.strategies.items()):
        placeholder = meta["placeholder"]
        if name not in present:
            findings.append(Finding(
                "ERROR", name,
                f"declared for {placeholder} but absent from ChromaDB, every resolution on "
                "this placeholder falls through in silence", ""))
            continue
        try:
            count = ctx.client.get_collection(name=name).count()
        except Exception as exc:                                    # noqa: BLE001
            findings.append(Finding("ERROR", name, f"cannot be counted: {exc}", ""))
            continue
        if count == 0:
            findings.append(Finding(
                "ERROR", name, f"empty, so {placeholder} can never resolve", "0 documents"))
        else:
            findings.append(Finding("OK", name, f"serves {placeholder}", f"{count} documents"))
    return findings


# --------------------------------------------------------------------------------------------
# Self-test. The thresholds are the part of this file that can rot in silence, and they are the
# only part testable without the store, so they are tested. It runs offline, in under a second,
# and needs neither ChromaDB nor a key.
# --------------------------------------------------------------------------------------------

def selftest():
    """Assert that the tail-length heuristic separates a subtitle from a description.

    This is the whole difficulty of `separator-agreement`: a name may legitimately contain the
    separator, so counting colons is not enough. The two fixtures are the real shapes, a series
    catalogue full of subtitles and a list catalogue carrying descriptions.
    """
    class _Coll:
        def __init__(self, docs):
            self._docs = docs

        def get(self, limit=None, include=None):
            return {"documents": self._docs[:limit]}

    class _Client:
        def __init__(self, by_name):
            self._by_name = by_name

        def get_collection(self, name=None):
            if name not in self._by_name:
                raise KeyError(name)
            return _Coll(self._by_name[name])

    # Four fixtures, each one a shape measured on the real store on 2026-08-29.
    subtitles = ["Star Trek: The Next Generation", "Doctor Who", "Breaking Bad",
                 "Sherlock: A Study in Pink", "The Wire"] * 20
    described = ["Wikiflix", "Cannes winners",
                 "The Flamenco Trilogy: One of Spanish cinema's great auteurs, Carlos Saura, "
                 "filmed three flamenco pieces"] * 20
    # The real `lists`: 23 documents, 2 of them described. It reported 9%, ONE POINT under the
    # error bar, which is what added the warning band. Kept so the day someone raises
    # SUSPECT_SHARE, this fixture says out loud what that would cost.
    small = (["Wikiflix"] * 21 +
             ["The Flamenco Trilogy: One of Spanish cinema's great auteurs, Carlos Saura, "
              "filmed three flamenco pieces",
              "The BRD Trilogy: Fassbinder on postwar West Germany, three films made between "
              "1979 and 1982"])
    # The real `movies`: 1000 documents, 90 with a colon, 3 with a long tail. Must stay silent,
    # otherwise the check cries wolf on every run and stops being read at all.
    big = (["Doctor Who"] * 910 + ["Mission: Impossible"] * 87 +
           ["Dune: Part Two and a subtitle long enough to look like a description here"] * 3)

    fixtures = {"series": subtitles, "lists": described, "small": small, "big": big}
    ctx = Context(client=_Client(fixtures),
                  strategies={k: {"placeholder": k, "config": {}} for k in fixtures},
                  sample=DEFAULT_SAMPLE)
    got = {f.target: f.level for f in check_separator_agreement(ctx)}

    failures = []
    for target, want in (("series", "OK"), ("lists", "ERROR"),
                         ("small", "WARN"), ("big", "OK")):
        ok = got.get(target) == want
        mark = 'OK  ' if ok else 'FAIL'
        print(f"  [{mark}] {target}: {got.get(target)} (wanted {want})")
        if not ok:
            failures.append(target)
    print("  series: colons in 40% of the names, all short, must NOT be flagged.")
    print("  lists:  descriptions throughout, must be an error.")
    print("  small:  23 documents, 2 described, 9%, under the error bar but must warn.")
    print("  big:    1000 documents, 3 long subtitles, 0.3%, must stay silent.")
    if failures:
        print(f"\nSELFTEST FAILED on {', '.join(failures)}")
        return 1
    print("\nSELFTEST OK")
    return 0


# --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Consistency checks on the ChromaDB store read by entity resolution.")
    parser.add_argument("--check", action="append", metavar="NAME",
                        help="run only this check, repeatable (default: all)")
    parser.add_argument("--list", action="store_true", help="list the checks and exit")
    parser.add_argument("--selftest", action="store_true",
                        help="test the thresholds offline, without ChromaDB, and exit")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help=f"documents sampled per collection (default {DEFAULT_SAMPLE})")
    # main.py defaults the port to 8000; the VPS actually serves ChromaDB on 8100 and sets
    # CHROMADB_PORT accordingly. 8100 is the default here so the script works on the VPS with no
    # env file, and the divergence is written down rather than discovered.
    parser.add_argument("--host", default=os.getenv("CHROMADB_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CHROMADB_PORT", "8100")))
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if args.list:
        for name, (summary, _) in sorted(CHECKS.items()):
            print(f"  {name:22s} {summary}")
        return 0

    selected = args.check or sorted(CHECKS)
    unknown = [c for c in selected if c not in CHECKS]
    if unknown:
        print(f"unknown check(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"available: {', '.join(sorted(CHECKS))}", file=sys.stderr)
        return 2

    import chromadb

    print(f"ChromaDB at {args.host}:{args.port}, sample {args.sample} documents per collection")
    client = chromadb.HttpClient(host=args.host, port=args.port)
    ctx = Context(client=client, strategies=load_embeddings_strategies(), sample=args.sample)
    print(f"{len(ctx.strategies)} embeddings strategies in data/entity_resolution.json")

    errors = 0
    for name in selected:
        summary, fn = CHECKS[name]
        print(f"\n== {name} : {summary}")
        for f in fn(ctx):
            errors += f.level == "ERROR"
            mark = {"ERROR": "FAIL", "WARN": "WARN", "OK": "ok  "}.get(f.level, f.level)
            print(f"  [{mark}] {f.target:14s} {f.message}")
            if f.evidence:
                print(f"         {f.evidence}")

    print()
    if errors:
        print(f"VERDICT: {errors} ERROR(s)")
        return 1
    print("VERDICT: no error")
    return 0


if __name__ == "__main__":
    sys.exit(main())
