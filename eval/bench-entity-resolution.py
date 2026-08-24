#!/usr/bin/env python3
"""Off-production bench for entity resolution: what threshold separates a typo from a stranger.

WHY THIS EXISTS (FASTAPI-TEXT2SQL-206)
Of the fourteen resolvers in data/entity_resolution.json, exactly one carries a rejection
threshold: Collection_name, with min_fuzz_ratio = 72. The other thirteen have neither
max_distance nor min_fuzz_ratio, so an embeddings search accepts its nearest neighbour however
far it sits. Measured on 2026-08-24: "Wagonlit collection" resolved to "Life Collection", while
"Collection Bibendum" was rejected only because Collection_name happens to be the protected one
(distance 1.042, fuzz_ratio 54).

Setting thresholds needs the distribution of those scores for matches that SHOULD pass and for
matches that SHOULD NOT. The first half comes from real usage. The second half does not exist,
and cannot: with no threshold, everything resolved, so the corpus records no rejection. That is
survivorship bias in its textbook form, and the reason this bench MANUFACTURES its negatives
instead of mining them.

THE CLASSES, IN DECREASING ORDER OF CERTAINTY
  positive-catalogue      values drawn straight from the very table the resolver searches. The
                          strongest ground truth available: such a value MUST resolve to itself,
                          and a miss is a resolver defect rather than a threshold question.
  positive-real           (type, value) pairs whose evaluation always scored 1. Ground truth is
                          the assertions, not the resolver: a match that "succeeded" into a wrong
                          answer is not a positive.
  positive-unscored       values seen in the logs but never scored. Weaker: nothing says the
                          answer was right. Kept only where scored positives run out, and named
                          apart so the weakness stays visible in the report.
  positive-*-typo         each of the above, mutated on purpose (two letters swapped, one
                          substituted, one dropped). Ground truth holds by construction, and this
                          is the class a threshold must not break, since correcting typos is what
                          the resolver is for.
  negative-cross          a value of type A submitted to the resolver of type B. Realistic
                          wording, guaranteed non-membership, and free.
  negative-invent         made-up names (the Zorglub family). Tests "nothing like this exists"
                          rather than "this belongs elsewhere", a different failure.

One more group, pairs that NEVER scored 1, is exported as `suspect` and deliberately left out of
the arithmetic. Some are wrong resolutions, some fail for unrelated reasons, and only reading
them tells which. Triage them by hand and promote the ones that qualify.

WHERE THE VALUES COME FROM, AND THE THIN-TYPE PROBLEM
Usage is lopsided: hundreds of Person_name and Movie_title values against a handful of
Network_name, and a threshold calibrated on three examples is a superstition with decimals.

Two remedies, and they fix different halves. eval/harvest-archived-entities.py reads months of
execution logs from the VPS share and caches every extracted value locally, which this bench
picks up automatically: that lifted Topic_name from 48 to 236 and Collection_name from 36 to 128.
It did nothing for the true tail, and could not: across 24040 archived requests Network_name
shows SEVEN distinct values, because nobody asks about a network by name. The scarcity is in the
usage, not in the sampling.

So the tail is fed from the catalogue instead (--catalogue-per-type), drawing from each
resolver's own table, ordered by the popularity column the config already names so the sample
looks like what users ask about rather than like the alphabet. Unlimited, and better grounded
than usage will ever be.

READING THE OUTPUT
Distance is a DISSIMILARITY: larger means further, and a threshold reads `distance <= max`.
Ratio is a SIMILARITY on 100: larger means closer, and a threshold reads `ratio >= min`. The
report gives, per entity type, both distributions and the cut misclassifying the fewest cases,
with the two error counts kept apart because they do not cost the same. A false rejection
degrades into a raw fallback, then an empty result, then the complex-question retry: expensive,
but visible and caught. A false acceptance produces a confidently wrong answer nobody notices.
Prefer the strict side. The retry is precisely what makes strictness affordable.

Usage:
  uv run eval/bench-entity-resolution.py --build-only          # corpus alone, needs no database
  uv run eval/bench-entity-resolution.py --limit-per-type 40
  uv run eval/bench-entity-resolution.py --types Network_name,Collection_name

Reads DB_*, CHROMADB_* and the LLM keys from the repository .env, like the rest of the stack.
"""
import argparse
import collections
import glob
import io
import json
import os
import random
import re
import sys

from dotenv import load_dotenv
import pymysql.cursors

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE_CACHE = os.path.join(REPO, "eval/data/archived-entity-values.json")

# The fourteen placeholders that actually reach a scored resolver. Closed-vocabulary and regex
# placeholders (Movie_genre, Release_year, ...) resolve by exact lookup and produce no score.
SCORED_TYPES = [
    "Person_name", "Movie_title", "Serie_title", "Company_name", "Network_name",
    "Topic_name", "List_name", "Award_name", "Nomination_name", "Collection_name",
    "Movement_name", "Location_name", "Group_name", "Death_name",
]

INVENTED = [
    "Zorglub", "Bibendum", "Wagonlit", "Kraglinov", "Pentafrag",
    "Vorzimmer", "Quillebeuf", "Zamboni-Trask", "Mirlitonde", "Halvorsen-Puig",
]


def get_db_connection():
    """Open the shared MariaDB connection, same environment variables as the API."""
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=15,
    )


def base_type(key):
    """'Person_name2' -> 'Person_name'."""
    return re.sub(r"\d+$", "", (key or "").strip("{} "))


def harvest_pairs():
    """Collect (type, value) pairs from the evaluation exports, the local logs and the archive.

    The exports carry an assertion score, which is what separates a positive from a suspect.
    Logs carry no score, so they only widen the value pool that negatives are drawn from.
    """
    scores = collections.defaultdict(set)
    for path in glob.glob(os.path.join(REPO, "eval/data/evaluation_execution/*/*.json")):
        try:
            row = json.load(io.open(path, encoding="utf-8"))
        except Exception:
            continue
        extraction = (row.get("api_output") or {}).get("entity_extraction") or {}
        score = (row.get("scoring") or {}).get("assertions_total_score")
        if not isinstance(extraction, dict):
            continue
        for key, value in extraction.items():
            etype = base_type(key)
            if key != "question" and etype in SCORED_TYPES and isinstance(value, str) and value.strip():
                scores[(etype, value.strip())].add(score)

    pool = collections.defaultdict(set)
    for path in glob.glob(os.path.join(REPO, "logs/*.json")):
        try:
            row = json.load(io.open(path, encoding="utf-8"))
        except Exception:
            continue
        extraction = (row.get("response") or {}).get("entity_extraction") or {}
        if not isinstance(extraction, dict):
            continue
        for key, value in extraction.items():
            etype = base_type(key)
            if key != "question" and etype in SCORED_TYPES and isinstance(value, str) and value.strip():
                pool[etype].add(value.strip())

    # Months of archived executions, cached locally by eval/harvest-archived-entities.py. This is
    # what lifts the thin types out of the "three examples" range.
    archived = 0
    if os.path.isfile(ARCHIVE_CACHE):
        try:
            cache = json.load(io.open(ARCHIVE_CACHE, encoding="utf-8"))
            for etype, values in (cache.get("values") or {}).items():
                if etype in SCORED_TYPES:
                    for value in values:
                        pool[etype].add(value)
                        archived += 1
        except Exception as cache_error:
            print(f"[warn] cache d'archives illisible, ignore : {cache_error}")

    positives = sorted(p for p, s in scores.items() if s == {1})
    suspects = sorted(p for p, s in scores.items() if 1 not in s)
    for etype, value in positives:
        pool[etype].add(value)
    return positives, suspects, pool, archived


def sample_from_catalogue(connection, types_filter, per_type, rng):
    """Draw values straight from each resolver's OWN table, the surest positives there are.

    The archive fixed the middle of the distribution and could not fix its tail: across 24040
    archived requests, Network_name shows **seven** distinct values, because nobody asks about a
    network by name. No amount of extra logs changes that, since the scarcity is in the usage,
    not in the sampling.

    The catalogue has no such limit and its ground truth is stronger than usage will ever be: a
    value copied verbatim out of the table the resolver searches MUST resolve to itself. A miss
    there is a resolver defect, not a threshold question, which makes this class the reference
    against which any threshold is judged.

    Ordered by the popularity column the config already names, so the sample looks like what
    users actually ask about rather than like the alphabet.
    """
    try:
        import json as _json
        config = _json.load(io.open(os.path.join(REPO, "data/entity_resolution.json"), encoding="utf-8"))
    except Exception as config_error:
        print(f"[warn] entity_resolution.json illisible, catalogue ignore : {config_error}")
        return {}

    wanted = set(types_filter or SCORED_TYPES)
    drawn = collections.defaultdict(list)
    with connection.cursor() as cursor:
        for entry in config:
            etype = entry.get("placeholder_prefix")
            if etype not in wanted:
                continue
            strategy = next((s for s in (entry.get("search_list") or []) if s.get("strtablename")), None)
            if not strategy:
                continue
            table = strategy.get("strtablename")
            column = strategy.get("default_field")
            if not table or not column:
                continue
            order_by = strategy.get("rapidfuzz_col_popularity") or strategy.get("order_by")
            # Identifiers come from a repository config file, never from a request, and are
            # interpolated because MySQL will not parameterise a table or column name.
            order_clause = f"ORDER BY `{order_by}` DESC " if order_by else ""
            sql = (f"SELECT `{column}` AS value FROM `{table}` "
                   f"WHERE `{column}` IS NOT NULL AND `{column}` <> '' {order_clause}LIMIT %s")
            try:
                cursor.execute(sql, (max(per_type * 3, 30),))
                rows = [str(r["value"]).strip() for r in cursor.fetchall() if r.get("value")]
            except Exception as query_error:
                print(f"[warn] catalogue {etype} ({table}.{column}) : {query_error}")
                continue
            rng.shuffle(rows)
            drawn[etype] = rows[:per_type]
    return drawn


def mutate(value, rng):
    """Introduce one realistic typo: swap two adjacent letters, substitute one, or drop one.

    Only inside a word and never on the first character, because a first-letter error is a
    different problem (it defeats prefix indexes) and would muddy the measurement.
    """
    letters = [i for i, c in enumerate(value) if c.isalpha() and i > 0]
    if len(letters) < 3:
        return value
    kind = rng.choice(("swap", "substitute", "drop"))
    chars = list(value)
    if kind == "swap":
        candidates = [i for i in letters if i + 1 < len(chars) and chars[i + 1].isalpha()]
        if not candidates:
            return value
        i = rng.choice(candidates)
        chars[i], chars[i + 1] = chars[i + 1], chars[i]
    elif kind == "substitute":
        i = rng.choice(letters)
        chars[i] = rng.choice("abcdefghijklmnopqrstuvwxyz")
    else:
        i = rng.choice(letters)
        del chars[i]
    return "".join(chars)


def build_corpus(limit_per_type, types_filter, seed, use_pool_as_positive, catalogue=None):
    """Assemble the classes. Without `catalogue` this reads files only and needs no database."""
    rng = random.Random(seed)
    positives, suspects, pool, archived = harvest_pairs()
    wanted = set(types_filter or SCORED_TYPES)

    by_type = collections.defaultdict(list)
    for etype, value in positives:
        if etype in wanted:
            by_type[etype].append(value)

    # Catalogue values come first and keep their own class: their ground truth is the strongest
    # available, since a value copied out of the very table the resolver searches must resolve to
    # itself. They also feed the negative pool, so a catalogue value of one type can be injected
    # into the resolver of another.
    catalogue_cases = []
    for etype, values in (catalogue or {}).items():
        if etype not in wanted:
            continue
        for value in values:
            pool[etype].add(value)
            catalogue_cases.append({"type": etype, "value": value, "klass": "positive-catalogue"})
            typo = mutate(value, rng)
            if typo != value:
                catalogue_cases.append({"type": etype, "value": typo,
                                        "klass": "positive-catalogue-typo", "expected": value})

    # Thin types have no scored positives at all. Falling back to the unscored pool is a weaker
    # ground truth (nothing says the answer was right) but it beats not measuring them, and the
    # class name keeps the distinction visible in the output.
    weakly_grounded = set()
    if use_pool_as_positive:
        for etype in wanted:
            if len(by_type[etype]) < 10 and pool.get(etype):
                extra = [v for v in sorted(pool[etype]) if v not in set(by_type[etype])]
                rng.shuffle(extra)
                if extra:
                    by_type[etype].extend(extra[: (limit_per_type or 40)])
                    weakly_grounded.add(etype)

    scored_positives = {(t, v) for t, v in positives}
    cases = list(catalogue_cases)
    for etype, values in by_type.items():
        rng.shuffle(values)
        kept = values[:limit_per_type] if limit_per_type else values
        for value in kept:
            grounded = (etype, value) in scored_positives
            cases.append({
                "type": etype, "value": value,
                "klass": "positive-real" if grounded else "positive-unscored",
            })
            typo = mutate(value, rng)
            if typo != value:
                cases.append({
                    "type": etype, "value": typo,
                    "klass": "positive-typo" if grounded else "positive-typo-unscored",
                    "expected": value,
                })

    # Cross injection: a value belonging to another type, drawn from the widest pool available so
    # the negatives are not merely a permutation of the positives already measured.
    for etype in set(list(by_type) + [c["type"] for c in catalogue_cases]):
        others = [t for t in pool if t != etype and pool[t]]
        if not others:
            continue
        rng.shuffle(others)
        n = min(limit_per_type or 40, max(len(by_type[etype]), 10))
        for i in range(n):
            source = others[i % len(others)]
            cases.append({
                "type": etype, "value": rng.choice(sorted(pool[source])),
                "klass": "negative-cross", "borrowed_from": source,
            })

    for etype in set(list(by_type) + [c["type"] for c in catalogue_cases]):
        for name in INVENTED:
            cases.append({"type": etype, "value": name, "klass": "negative-invent"})

    return cases, suspects, sorted(weakly_grounded), archived


def run_cases(cases, connection, collections_by_name):
    """Resolve each case and keep the score of the candidate the resolver weighed."""
    import entity  # imported late: it pulls the resolution stack in

    for index, case in enumerate(cases, 1):
        key = case["type"] + "1"
        extraction = {"question": "about {{" + key + "}}", key: case["value"]}
        try:
            plan = entity.plan_entity_resolutions(
                connection=connection,
                entity_extraction=extraction,
                chromadb_collections_by_name=collections_by_name,
            )
        except Exception as resolution_error:
            case["error"] = str(resolution_error)
            continue
        scored = plan.get("match_scores") or []
        mine = [s for s in scored if base_type(s.get("placeholder")) == case["type"]] or scored
        if mine:
            best = mine[0]
            case["distance"] = best.get("distance")
            case["fuzz_ratio"] = best.get("fuzz_ratio")
            case["candidate"] = best.get("candidate")
            case["search_mode"] = best.get("search_mode")
            case["exact_match"] = best.get("exact_match")
            case["rejected_by_current_threshold"] = best.get("rejected")
        if index % 100 == 0:
            print("   %d/%d cas resolus" % (index, len(cases)), flush=True)
    return cases


def best_cut(positives, negatives, higher_is_better):
    """Return the cut minimising total misclassification, both error counts kept apart.

    Ties break toward the strict side, because the two errors do not cost the same: a false
    rejection is caught downstream by the complex-question retry, a false acceptance is not.
    """
    values = sorted({v for v in list(positives) + list(negatives)})
    if not values:
        return None
    best = None
    for cut in values:
        if higher_is_better:
            refused = sum(1 for v in positives if v < cut)      # legitimate matches turned away
            let_in = sum(1 for v in negatives if v >= cut)      # strangers accepted
        else:
            refused = sum(1 for v in positives if v > cut)
            let_in = sum(1 for v in negatives if v <= cut)
        rank = (refused + let_in, let_in)
        if best is None or rank < best[0]:
            best = (rank, {
                "cut": round(float(cut), 4),
                "legitimate_refused": refused,
                "strangers_accepted": let_in,
                "positives": len(positives),
                "negatives": len(negatives),
            })
    return best[1]


def report(cases):
    """Print, per entity type, the two distributions and the cut they suggest."""
    grouped = collections.defaultdict(lambda: collections.defaultdict(list))
    for case in cases:
        if case.get("fuzz_ratio") is None and case.get("distance") is None:
            continue
        grouped[case["type"]][case["klass"]].append(case)

    out = {}
    for etype in sorted(grouped):
        klasses = grouped[etype]
        pos = [c for k, v in klasses.items() if k.startswith("positive") for c in v]
        neg = [c for k, v in klasses.items() if k.startswith("negative") for c in v]
        print("\n### %s   %d positifs, %d negatifs" % (etype, len(pos), len(neg)))
        if not pos or not neg:
            print("   pas assez de matiere pour proposer un seuil")
            continue
        entry = {"positives": len(pos), "negatives": len(neg)}
        for field, higher in (("fuzz_ratio", True), ("distance", False)):
            pv = sorted(c[field] for c in pos if isinstance(c.get(field), (int, float)))
            nv = sorted(c[field] for c in neg if isinstance(c.get(field), (int, float)))
            if not pv or not nv:
                continue
            cut = best_cut(pv, nv, higher)
            print("   %-11s positifs med=%.1f min=%.1f | negatifs med=%.1f max=%.1f"
                  % (field, pv[len(pv) // 2], pv[0], nv[len(nv) // 2], nv[-1]))
            if cut:
                print("   %-11s seuil propose %s %.2f  (legitimes refuses %d, intrus acceptes %d)"
                      % ("", ">=" if higher else "<=", cut["cut"],
                         cut["legitimate_refused"], cut["strangers_accepted"]))
                entry[field] = cut
        out[etype] = entry
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit-per-type", type=int, default=40,
                        help="positives kept per entity type (0 = all). Default 40.")
    parser.add_argument("--types", default="", help="comma-separated subset of entity types")
    parser.add_argument("--seed", type=int, default=20260824, help="fixed so runs compare")
    parser.add_argument("--build-only", action="store_true",
                        help="write the corpus and stop, no database needed")
    parser.add_argument("--no-unscored", action="store_true",
                        help="do not top thin types up from the unscored pool")
    parser.add_argument("--catalogue-per-type", type=int, default=40,
                        help="values drawn from each resolver's own table (0 = off). The surest "
                             "positives there are, and the only cure for a type nobody asks about: "
                             "Network_name shows 7 distinct values across 24040 archived requests")
    parser.add_argument("--out", default=os.path.join(REPO, "eval/data/bench-entity-resolution.json"))
    args = parser.parse_args()

    types_filter = [t.strip() for t in args.types.split(",") if t.strip()]

    # The catalogue draw needs the database, so --build-only skips it and falls back to the
    # file-only corpus. That is the honest degradation: fewer positives, same method.
    catalogue = {}
    connection = None
    if not args.build_only and args.catalogue_per_type:
        connection = get_db_connection()
        catalogue = sample_from_catalogue(
            connection, types_filter, args.catalogue_per_type, random.Random(args.seed))
        print("Catalogue : " + ", ".join(
            "%s=%d" % (k, len(v)) for k, v in sorted(catalogue.items())) or "vide")

    cases, suspects, weak, archived = build_corpus(
        args.limit_per_type, types_filter, args.seed, not args.no_unscored, catalogue)

    counts = collections.Counter(c["klass"] for c in cases)
    print("Corpus : " + ", ".join("%s=%d" % (k, v) for k, v in sorted(counts.items())))
    print("Valeurs tirees du cache d'archives : %d" % archived)
    print("Suspects a trier a la main (jamais score 1) : %d" % len(suspects))
    if weak:
        print("Types completes depuis le vivier NON score, verite de terrain plus faible : "
              + ", ".join(weak))

    if args.build_only:
        payload = {"cases": cases, "suspects": suspects, "weakly_grounded": weak, "report": None}
    else:
        import main as api  # module-level startup connects ChromaDB and loads the collections
        if connection is None:
            connection = get_db_connection()
        try:
            cases = run_cases(cases, connection, api.CHROMADB_COLLECTIONS_BY_NAME)
        finally:
            try:
                connection.close()
            except Exception:
                pass
        payload = {"cases": cases, "suspects": suspects, "weakly_grounded": weak,
                   "report": report(cases)}

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print("\nEcrit dans %s" % args.out)


if __name__ == "__main__":
    sys.exit(main())
