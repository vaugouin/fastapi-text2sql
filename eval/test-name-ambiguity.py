#!/usr/bin/env python3
"""Non-regression battery for the ``name_ambiguity`` flag (FASTAPI-TEXT2SQL-157).

WHAT THIS CHECKS
----------------
`/search/text2sql` returns a neutral ``name_ambiguity`` object ONLY when the
generated SQL is a *pure* exact-equality match on an entity's name/title
column(s) against a single literal AND returns >=2 DISTINCT rows -- i.e. the user
named one entity (movie / serie / person) but the database holds several homonyms
or duplicate titles. It is descriptive, not an instruction: clients decide what to
do with it (voice-agent disambiguates, tmdb-front ignores). See the README section
"Response Fields" and ticket FASTAPI-TEXT2SQL-157 / VOICE-AGENT-093.

This script pins the flag's behaviour with a fixed battery of live queries and
checks, so a future change to the detection code (or the prompt that shapes the
SQL) can't silently regress it. It is an INTEGRATION test: it calls the running
API over HTTP. It touches no database and is read-only.

WHAT EACH GROUP PINS
--------------------
- single_no_flag : a title/name search returning exactly 1 row must NOT flag.
- no_flag        : multi-row results that are NOT a same-name cluster (list
                   queries with a JOIN / genre / collection filter, or a query
                   NARROWED by a discriminator such as a year or director) must
                   NOT flag -- even when they return several rows.
- flag_movie     : a bare duplicate-title movie search must flag, with
                   count == number of DISTINCT ID_IMDB in the raw result
                   (the collapse must merge ONLY true duplicates, never distinct
                   films that merely share a title+year -- the bug fixed in
                   commit fac0797, e.g. two 1989 "Black Rain", two 2025 "Dracula").
- flag_serie     : same as flag_movie for a duplicate TV-series title (phrase as
                   "the TV series X", since some titles are also films).
- flag_person    : a homonym person search must flag (role/birth-year carried).
- flag_soft      : apostrophe robustness -- the WHERE literal 'Ocean''s Eleven'
                   must be parsed and un-escaped correctly (or, if the resolver
                   didn't build a pure-title cluster, at least not error).
- page2_no_flag  : the flag is computed on page 1 only.

HOW TO RUN
----------
    python eval/test-name-ambiguity.py                 # default: green
    python eval/test-name-ambiguity.py --color blue    # test the blue stack
    python eval/test-name-ambiguity.py --base-url http://localhost:8000
    python eval/test-name-ambiguity.py --verbose       # print the flag payload

Exit code is 0 when every case passes, 1 otherwise -- so it can gate a deploy.

CONFIG (read from eval/.env, same keys as the eval harness)
-----------------------------------------------------------
    TEXT2SQL_API_URL   scheme+host, no port   (e.g. http://www.vaugouin.com)
    API_PORT_GREEN     green port             (e.g. 8187)   <- default
    API_PORT_BLUE      blue port              (e.g. 8186)
    TEXT2SQL_API_KEY   the X-API-Key value
Overrides: --base-url wins over URL+port; --env-file points at another .env;
also honours voice-agent-style TEXT2SQL_BASE_URL / TEXT2SQL_API_KEY_VALUE if the
eval keys are absent, so the same script runs from either repo's env.

HOW TO EXTEND
-------------
Add a dict to CASES. Fields: {"q": <question>, "kind": <one of the KINDS below>,
optional "page": <int>, optional "note": <why this case exists>}. Keep real,
stable examples (a title whose duplicate set won't churn) so the battery stays
deterministic.

FINDING DUPLICATE CANDIDATES (how the positive cases were sourced) -- group the
entity table by its display name/title and keep the groups of size > 1:

    -- persons:
    SELECT COUNT(*) AS N, PERSON_NAME FROM T_WC_T2S_PERSON GROUP BY PERSON_NAME HAVING N>1 ORDER BY N DESC;
    -- TV series:
    SELECT COUNT(*) AS N, SERIE_TITLE FROM T_WC_T2S_SERIE  GROUP BY SERIE_TITLE HAVING N>1 ORDER BY N DESC;
    -- movies (English title). The flag ALSO matches MOVIE_TITLE_FR / ORIGINAL_TITLE,
    -- so group those columns too to catch cross-language duplicates like "Le Bonheur":
    SELECT COUNT(*) AS N, MOVIE_TITLE FROM T_WC_T2S_MOVIE  GROUP BY MOVIE_TITLE HAVING N>1 ORDER BY N DESC;

Phrase the resulting cases so the entity resolves correctly: persons as
"Tell me about <name>", series as "the TV series <title>" (several serie titles
are also films), movies as "the movie <title>".
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

# Make non-ASCII titles (e.g. "Dracula" Spanish "Drácula") print cleanly on
# a Windows console instead of raising / mojibake.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# --- the battery -------------------------------------------------------------
# Each case is a live question plus the behaviour it pins. Expected row counts are
# only asserted where they are stable; elsewhere we assert the INVARIANT (flag set
# or not, count == distinct ID_IMDB) which holds regardless of catalogue churn.
CASES = [
    # A title/name search that resolves to a single row must never flag.
    {"q": "Tell me about the movie The Big Lebowski", "kind": "single_no_flag"},
    {"q": "Tell me about the movie Pulp Fiction", "kind": "single_no_flag"},
    {"q": "Tell me about Christopher Nolan", "kind": "single_no_flag",
     "note": "unique person name -> 1 row -> no flag"},

    # NARROWED by a discriminator: the WHERE is no longer pure name equality, so no
    # flag even when several rows come back (e.g. two distinct 1931 Draculas).
    {"q": "The Big Sleep directed by Howard Hawks", "kind": "no_flag",
     "note": "director join narrows to 1"},
    {"q": "Tell me about the movie Dracula released in 1931", "kind": "no_flag",
     "note": "year predicate -> not a pure-title query -> no flag (known limit: 2 rows stay un-flagged)"},

    # LIST queries: multi-row but not a same-name cluster.
    {"q": "Movies directed by Christopher Nolan", "kind": "no_flag"},
    {"q": "List movies in the Harry Potter collection", "kind": "no_flag"},
    {"q": "What horror movies came out in 2026", "kind": "no_flag"},
    {"q": "Movies with Brad Pitt", "kind": "no_flag"},

    # POSITIVES -- duplicate movie titles. count must equal DISTINCT ID_IMDB.
    {"q": "Tell me about the movie Le Bonheur", "kind": "flag_movie",
     "note": "4 films; multi-column match (display 'Happiness' != spoken title)"},
    {"q": "Tell me about the movie Dracula", "kind": "flag_movie",
     "note": "20 distinct films; no false collapse on shared title/year"},
    {"q": "Tell me about the movie Black Rain", "kind": "flag_movie",
     "note": "two 1989 films (Scott US / Imamura JP) -> year-collision case"},

    # POSITIVES -- duplicate SERIE titles (found via
    #   SELECT COUNT(*), SERIE_TITLE FROM T_WC_T2S_SERIE GROUP BY SERIE_TITLE HAVING COUNT(*)>1
    # Phrase as "the TV series X" so result_entity resolves to serie, not movie
    # (several of these titles are also films: 48 Hours, 1992, ...).
    {"q": "Tell me about the TV series 1001 Nights", "kind": "flag_serie",
     "note": "2 series; clean baseline serie cluster"},
    {"q": "Tell me about the TV series 20,000 Leagues Under the Sea", "kind": "flag_serie",
     "note": "2 series; comma inside the WHERE literal (robustness)"},
    {"q": "Tell me about the TV series 1 vs. 100", "kind": "flag_serie",
     "note": "3 series; count>2 and 'vs.' punctuation"},

    # POSITIVES -- homonym persons.
    {"q": "Tell me about Steve McQueen", "kind": "flag_person",
     "note": "actor 1930 (Acting) vs director 1969 (Directing)"},
    {"q": "Tell me about Harrison Ford", "kind": "flag_person",
     "note": "modern star vs silent-era actor 1884-1957"},
    {"q": "Tell me about John Williams", "kind": "flag_person",
     "note": "6 homonyms (composer + others) -> count>2 person cluster"},

    # Apostrophe robustness: literal 'Ocean''s Eleven' must parse/un-escape.
    {"q": "Tell me about the movie Ocean's Eleven", "kind": "flag_soft",
     "note": "1960 + 2001; tests quoted-apostrophe literal in the WHERE"},

    # The flag is page-1 only.
    {"q": "Tell me about the movie Dracula", "kind": "page2_no_flag", "page": 2},
]

KINDS = {"single_no_flag", "no_flag", "flag_movie", "flag_serie", "flag_person",
         "flag_soft", "page2_no_flag"}


def load_env(env_file):
    """Minimal .env reader (no dependency). Returns a dict; missing file -> {}."""
    values = {}
    if not os.path.isfile(env_file):
        return values
    with open(env_file, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def resolve_config(args):
    """Resolve (base_url, key_name, key_value) from CLI args + .env, with the
    eval keys first and voice-agent-style keys as a fallback."""
    env = load_env(args.env_file)
    key_name = env.get("TEXT2SQL_API_KEY_NAME", "X-API-Key")
    key_value = env.get("TEXT2SQL_API_KEY") or env.get("TEXT2SQL_API_KEY_VALUE") or ""

    if args.base_url:
        base = args.base_url.rstrip("/")
    elif env.get("TEXT2SQL_BASE_URL"):  # voice-agent style: full URL incl. port
        base = env["TEXT2SQL_BASE_URL"].rstrip("/")
    else:  # eval style: host + per-color port
        host = (env.get("TEXT2SQL_API_URL") or "http://localhost").rstrip("/")
        port = env.get("API_PORT_BLUE" if args.color == "blue" else "API_PORT_GREEN", "8187")
        base = f"{host}:{port}"
    return base, key_name, key_value


def call(base, key_name, key_value, question, page=1, timeout=120):
    body = json.dumps({
        "question": question, "ui_language": "en", "page": page, "rows_per_page": 50,
        "retrieve_from_cache": True, "store_to_cache": True,
        "complex_question_processing": False,
    }).encode()
    req = urllib.request.Request(
        base + "/search/text2sql", data=body,
        headers={"Content-Type": "application/json", key_name: key_value})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def distinct_imdb(payload):
    seen = set()
    for item in payload.get("result") or []:
        val = item.get("data", {}).get("ID_IMDB")
        if val not in (None, ""):
            seen.add(str(val).strip())
    return len(seen)


def check(case, payload):
    """Return (ok: bool, detail: str) for one case against its API response."""
    kind = case["kind"]
    rows = len(payload.get("result") or [])
    na = payload.get("name_ambiguity")
    flag_state = "set" if na else "None"

    if kind == "single_no_flag":
        # 1 row must not flag. (If the catalogue grew a homonym, rows>1 makes this
        # case moot rather than failing -- we only assert the 1-row implication.)
        if rows == 1:
            return (na is None, f"rows=1 flag={flag_state}")
        return (True, f"rows={rows} (not 1; case moot) flag={flag_state}")

    if kind == "no_flag":
        return (na is None, f"rows={rows} flag={flag_state}")

    if kind == "page2_no_flag":
        return (na is None, f"page2 rows={rows} flag={flag_state}")

    if kind in ("flag_movie", "flag_serie"):
        entity = "serie" if kind == "flag_serie" else "movie"
        if not na:
            return (False, f"expected flag, got None (rows={rows})")
        di = distinct_imdb(payload)
        ok = (na.get("entity") == entity and na.get("count", 0) >= 2
              and na.get("count") == di and bool(na.get("anchor")))
        return (ok, f"entity={na.get('entity')} anchor={na.get('anchor')!r} "
                    f"count={na.get('count')} distinct_imdb={di}")

    if kind == "flag_person":
        if not na:
            return (False, f"expected flag, got None (rows={rows})")
        ok = na.get("entity") == "person" and na.get("count", 0) >= 2
        return (ok, f"entity={na.get('entity')} anchor={na.get('anchor')!r} count={na.get('count')}")

    if kind == "flag_soft":
        # If a cluster was built, validate it strictly (anchor un-escaped, invariant);
        # if not, pass but report -- the point is the parser must not choke on the quote.
        if not na:
            return (True, f"no flag, rows={rows} (parser did not error)")
        di = distinct_imdb(payload)
        ok = na.get("count", 0) >= 2 and na.get("count") == di and bool(na.get("anchor"))
        return (ok, f"anchor={na.get('anchor')!r} count={na.get('count')} distinct_imdb={di}")

    return (False, f"unknown kind {kind!r}")


def main():
    parser = argparse.ArgumentParser(description="name_ambiguity flag non-regression battery")
    parser.add_argument("--color", choices=["green", "blue"], default="green",
                        help="which Blue/Green stack to hit (default: green)")
    parser.add_argument("--base-url", default="",
                        help="full base URL incl. port; overrides --color / .env")
    parser.add_argument("--env-file", default=os.path.join(os.path.dirname(__file__), ".env"),
                        help="path to the .env holding TEXT2SQL_API_KEY etc.")
    parser.add_argument("--verbose", action="store_true", help="print each flag payload")
    args = parser.parse_args()

    base, key_name, key_value = resolve_config(args)
    if not key_value:
        print(f"ERROR: no API key found (looked for TEXT2SQL_API_KEY / "
              f"TEXT2SQL_API_KEY_VALUE in {args.env_file})", file=sys.stderr)
        return 2

    print(f"Target: {base}  ({args.color})  cases: {len(CASES)}\n")

    passed = failed = 0
    for case in CASES:
        q, page = case["q"], case.get("page", 1)
        try:
            payload = call(base, key_name, key_value, q, page=page)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            print(f"FAIL | {case['kind']:<14} | {q!r} | REQUEST ERROR: {exc}")
            failed += 1
            continue
        ok, detail = check(case, payload)
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"{'PASS' if ok else 'FAIL'} | {case['kind']:<14} | {q!r} | {detail}")
        if case.get("note"):
            print(f"       ^ {case['note']}")
        if args.verbose and payload.get("name_ambiguity"):
            print("       flag: " + json.dumps(payload["name_ambiguity"], ensure_ascii=False))

    print(f"\n{'='*60}\n{passed} passed, {failed} failed  "
          f"({'ALL PASS' if failed == 0 else 'REGRESSION'})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
