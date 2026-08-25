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
  observed-unscored       values seen in the logs but never arbitrated. NOT a positive class,
                          and this was a correction: measured 2026-08-24, "Collection Criterion"
                          resolved to "Ex Collection" at 18.2 and "trois couleurs bleu blanc
                          rouge" to "Trois" at 27.8. Counting those as legitimate dragged the
                          recommended cut to 45.5 and would have carved the defect into the
                          configuration. The class is still produced, because its low tail is an
                          excellent DETECTOR of false acceptances already in production, but it
                          is kept out of the threshold arithmetic.
  positive-*-typo         each POSITIVE class above, mutated on purpose (two letters swapped,
                          one substituted, one dropped). Ground truth holds by construction, and
                          this is the class a threshold must not break, since correcting typos is
                          what the resolver is for.
  negative-cross          a value of type A submitted to the resolver of type B. Realistic
                          wording and free, but membership is NOT guaranteed: a series title
                          often has its collection, and "Star Trek: The Next Generation" resolves
                          to "Star Trek: The Next Generation Collection" quite correctly. Such a
                          case is flagged `contaminated` and dropped from the arithmetic, on
                          EQUALITY after descriptors are stripped, never on mere inclusion:
                          inclusion caught "suicide" against "Suicide Squad Collection", which is
                          a genuine false acceptance, not a legitimate one.
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

So the tail is fed from the catalogue instead (--catalogue-per-type), drawing from the resolver's
own ChromaDB collection, or from its table for a rapidfuzz strategy, ordered by the popularity
column the config already names so the sample looks like what users ask about rather than like the
alphabet. Unlimited, and better grounded than usage will ever be.

The draw covers EVERY strategy of a type, not just the first, and that matters for the only type
that has two. Person_name searches the persons table, then the alias table. Values from the first
resolve there and never cascade, so drawing only from it could measure nothing about the second:
the alias strategy was immeasurable exactly as long as it was unreachable. Values from the ALIAS
table are the population that was missing, since "Maurice Scherer" does not exist in the persons
table and therefore fails its threshold and carries the case through. The report then gives one
cut per resolving table, because a threshold is set per strategy and not per entity.

READING THE OUTPUT
Distance is a DISSIMILARITY: larger means further, and a threshold reads `distance <= max`.
Ratio is a SIMILARITY on 100: larger means closer, and a threshold reads `ratio >= min`. The
report gives, per entity type, both distributions and the cut misclassifying the fewest cases,
with the two error counts kept apart because they do not cost the same. It reports an INTERVAL
rather than a point: classification only changes at observed values, so a whole range of
thresholds is equivalent, and the midpoint is the robust choice. Measured 2026-08-24, the cut
came out at 93.3 where anything above 76.5 did just as well; announcing 93.3 alone would be false
precision. A field whose positive sample is too thin gets no recommendation at all, since on
Collection_name 98 of 119 positives resolve through rapidfuzz and carry no vector distance, and
the 21 that do are precisely the ones rapidfuzz missed. A false rejection
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


def sample_from_collection(collections_by_name, strategy, per_type, rng):
    """Draw values from the ChromaDB collection itself, which IS what the resolver searches.

    Corrects a wrong assumption (2026-08-25). The SQL table is not always the catalogue of the
    type: `Location_name` looks rows up in `T_WC_T2S_ITEM`, the whole Wikidata item referential,
    while the `locations` collection is a subset filtered elsewhere. Drawing "positives" from the
    table produced "-M- discography" and "...And Now Miguel" as locations, none of which resolved,
    and made the resolver look broken when the bench was.

    The collection has no such ambiguity: whatever it holds is what a query can match, so a
    document taken from it must resolve to itself.
    """
    name = strategy.get("collection")
    collection = (collections_by_name or {}).get(name)
    if collection is None:
        return []
    try:
        got = collection.get(limit=max(per_type * 5, 50), include=["documents"])
    except Exception as collection_error:
        print(f"[warn] collection {name} illisible : {collection_error}")
        return []
    documents = [d for d in (got.get("documents") or []) if isinstance(d, str) and d.strip()]
    separator = strategy.get("document_name_separator")
    values = []
    for document in documents:
        value = document.strip()
        # On veut ce qu'un utilisateur taperait, c'est-a-dire le NOM, pas le document indexe avec
        # sa description. Meme declaration par entite que cote resolution.
        if separator and separator in value:
            value = value.split(separator, 1)[0].strip()
        if value:
            values.append(value)
    rng.shuffle(values)
    return values[:per_type]


def sample_from_catalogue(connection, collections_by_name, types_filter, per_type, rng):
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
            # TOUTES les strategies, pas seulement la premiere (FASTAPI-TEXT2SQL-206, etape alias).
            # Person_name en a deux : la table des personnes, puis celle des alias. Tirer les
            # positifs de la seule premiere ne pouvait rien mesurer sur la seconde, puisque ces
            # valeurs s'y resolvent avant de cascader. Les valeurs de la table des alias, elles,
            # n'existent PAS dans la table des personnes ("Maurice Scherer" contre "Eric Rohmer"),
            # donc elles echouent le seuil de la premiere et portent le cas jusqu'a la seconde.
            # C'est exactement la population qui manquait.
            per_strategy = max(1, per_type // max(1, len(entry.get("search_list") or [1])))
            for strategy in entry.get("search_list") or []:
                table = strategy.get("strtablename")
                # La collection prime sur la table des qu'elle existe : c'est elle que le
                # resolveur interroge, la table ne sert qu'a recuperer la ligne ensuite.
                if strategy.get("search_mode") == "embeddings" and strategy.get("collection"):
                    for value in sample_from_collection(collections_by_name, strategy, per_strategy, rng):
                        drawn[etype].append({"value": value, "source": strategy.get("collection")})
                    continue
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
                    cursor.execute(sql, (max(per_strategy * 3, 30),))
                    rows = [str(r["value"]).strip() for r in cursor.fetchall() if r.get("value")]
                except Exception as query_error:
                    print(f"[warn] catalogue {etype} ({table}.{column}) : {query_error}")
                    continue
                rng.shuffle(rows)
                for value in rows[:per_strategy]:
                    drawn[etype].append({"value": value, "source": table})
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
    for etype, entries in (catalogue or {}).items():
        if etype not in wanted:
            continue
        for entry in entries:
            # `source` dit de quelle table ou collection la valeur a ete tiree, ce qui est la
            # seule facon de lire un type a plusieurs strategies : sur Person_name, les valeurs
            # venues de la table des alias sont celles qui exercent la seconde strategie.
            value = entry["value"] if isinstance(entry, dict) else entry
            source = entry.get("source") if isinstance(entry, dict) else None
            pool[etype].add(value)
            catalogue_cases.append({"type": etype, "value": value,
                                    "klass": "positive-catalogue", "source": source})
            typo = mutate(value, rng)
            if typo != value:
                catalogue_cases.append({"type": etype, "value": typo, "source": source,
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
            # `observed-*`, jamais `positive-*`, et c'est un correctif, pas un detail de nommage.
            # Une valeur vue dans un journal n'est pas une correspondance legitime, c'est une
            # valeur : sans assertion pour arbitrer, et avec treize resolveurs incapables
            # d'echouer, une bonne part de ces resolutions est fausse par construction. Mesure du
            # 2026-08-24 sur Collection_name : "Collection Criterion" -> "Ex Collection" a 18,2,
            # "trois couleurs bleu blanc rouge" -> "Trois" a 27,8. Les compter comme positifs
            # tirait le seuil recommande a 45,5 et aurait grave le defaut dans la configuration.
            # La classe reste produite parce qu'elle est un excellent DETECTEUR de ces fausses
            # acceptations, mais elle est hors du calcul du seuil.
            cases.append({
                "type": etype, "value": value,
                "klass": "positive-real" if grounded else "observed-unscored",
            })
            typo = mutate(value, rng)
            if typo != value:
                cases.append({
                    "type": etype, "value": typo,
                    "klass": "positive-typo" if grounded else "observed-unscored-typo",
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


_STOPWORDS_BY_TYPE = {}


def search_cfg_stopwords(etype):
    """Les `score_stopwords` declares pour ce type, lus une fois dans entity_resolution.json."""
    if not _STOPWORDS_BY_TYPE:
        try:
            config = json.load(io.open(os.path.join(REPO, "data/entity_resolution.json"), encoding="utf-8"))
        except Exception:
            config = []
        for entry in config:
            for strategy in entry.get("search_list") or []:
                if strategy.get("score_stopwords"):
                    _STOPWORDS_BY_TYPE[entry.get("placeholder_prefix")] = strategy["score_stopwords"]
                    break
        _STOPWORDS_BY_TYPE.setdefault("__loaded__", [])
    return _STOPWORDS_BY_TYPE.get(etype) or None


def run_cases(cases, connection, collections_by_name):
    """Resolve each case and keep the score of the candidate the resolver weighed."""
    import entity  # imported late: it pulls the resolution stack in
    global rapidfuzz_query
    import rapidfuzz_query

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
        # La trace COMPLETE, une entree par strategie ayant pese le cas. Retenir la premiere,
        # ce que faisait le banc, attribuait a la strategie 1 des scores qu'elle avait rejetes et
        # qu'une autre avait resolus : mesure du 2026-08-25, 31 valeurs tirees de la table des
        # alias comptees comme positifs de la table des personnes a 43,5, ce qui a fait tomber le
        # seuil recommande de 84,5 a 51,1.
        case["scores"] = mine
        if mine:
            # Le score qui compte est celui de la strategie qui a REELLEMENT resolu ; a defaut,
            # la meilleure tentative, celle qui a approche le plus pres du seuil.
            won = [s for s in mine if not s.get("rejected")]
            best = won[-1] if won else max(
                mine, key=lambda s: s.get("fuzz_ratio") if isinstance(s.get("fuzz_ratio"), (int, float)) else -1)
            # Une injection croisee suppose qu'une valeur d'un type n'appartient jamais a un
            # autre. Faux : un titre de serie a souvent sa collection. Mesure du 2026-08-24,
            # "Star Trek: The Next Generation" resout vers "Star Trek: The Next Generation
            # Collection" a 84,5, et c'est CORRECT. Compter ce cas comme un intrus accepte
            # pousserait le seuil vers le haut pour punir une bonne reponse. On marque donc
            # comme contamine tout croisement dont le candidat contient la valeur injectee.
            if case["klass"] == "negative-cross":
                # Le critere est l'EGALITE apres retrait des descripteurs, pas l'inclusion. Une
                # inclusion simple attrapait "suicide" -> "Suicide Squad Collection" a 45,2 et
                # "FX" -> "G.I. Joe (Reel FX) Collection" a 12,9, qui sont de vraies fausses
                # acceptations : un mot court contenu dans un nom plus long ne prouve rien.
                # L'egalite, elle, prouve quelque chose : "Star Trek: The Next Generation
                # Collection" prive de son descripteur EST la valeur injectee, donc la resoudre
                # est correct et la compter comme un intrus punirait une bonne reponse.
                try:
                    words = search_cfg_stopwords(case["type"])
                    sought = rapidfuzz_query.strip_franchise_words(
                        (case.get("value") or "").strip().lower(), words)
                    found = rapidfuzz_query.strip_franchise_words(
                        (best.get("candidate") or "").strip().lower(), words)
                    if sought and sought == found:
                        case["contaminated"] = True
                except Exception:
                    pass
            case["distance"] = best.get("distance")
            case["fuzz_ratio"] = best.get("fuzz_ratio")
            case["candidate"] = best.get("candidate")
            case["search_mode"] = best.get("search_mode")
            # La table et la collection identifient la STRATEGIE, ce que le banc oubliait de
            # recopier : sur Person_name, deux strategies rapidfuzz partagent la collection
            # `persons` et seule la table les separe. fuzz_ratio_raw dit ce que le score aurait
            # ete sans neutralisation des descripteurs, pour que l'effet reste auditable.
            case["table"] = best.get("table")
            case["collection"] = best.get("collection")
            case["fuzz_ratio_raw"] = best.get("fuzz_ratio_raw")
            case["stopwords_applied"] = best.get("stopwords_applied")
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
    scored = []
    for cut in values:
        if higher_is_better:
            refused = sum(1 for v in positives if v < cut)      # legitimate matches turned away
            let_in = sum(1 for v in negatives if v >= cut)      # strangers accepted
        else:
            refused = sum(1 for v in positives if v > cut)
            let_in = sum(1 for v in negatives if v <= cut)
        rank = (refused + let_in, let_in)
        scored.append((rank, float(cut), refused, let_in))
        if best is None or rank < best[0]:
            best = (rank, {
                "cut": round(float(cut), 4),
                "legitimate_refused": refused,
                "strangers_accepted": let_in,
                "positives": len(positives),
                "negatives": len(negatives),
            })
    # L'intervalle d'indifference, et il vaut mieux que le point. La coupe optimale tombe sur une
    # valeur observee, souvent au bord d'un vide : mesure du 2026-08-24, aucun cas entre 76,5 et
    # 93,3, si bien que la recommandation affichait 93,3 quand 77 donnait rigoureusement le meme
    # resultat. Annoncer 93,3 seul serait une precision fausse. On rend donc la plage de seuils
    # equivalents, dont le milieu est le choix le plus robuste : c'est celui qui est le plus loin
    # des deux distributions a la fois.
    equivalent = sorted(c for r, c, _, _ in scored if r == best[0])
    if equivalent:
        low, high = equivalent[0], equivalent[-1]
        # La classification ne change qu'AUX valeurs observees, donc l'intervalle reel s'etend
        # jusqu'a la valeur observee precedente, exclue. Ne considerer que les valeurs observees
        # comme seuils candidats revient a poser le curseur sur un cas particulier alors qu'un
        # seuil est un reel : mesure du 2026-08-24, la coupe sortait a 93,3 alors que tout seuil
        # au-dessus de 76,5 donnait le meme resultat, et 76,5 etait le pire intrus.
        below = [v for v in values if v < low]
        if below:
            low = below[-1]
        best[1]["equivalent_from"] = round(low, 4)
        best[1]["equivalent_to"] = round(high, 4)
        best[1]["robust_cut"] = round((low + high) / 2, 4)
    return best[1]


# En dessous de ce nombre de positifs mesures sur un champ, aucune recommandation n'est emise.
# Trente n'a rien de sacre, c'est l'ordre de grandeur en dessous duquel un point aberrant deplace
# la coupe a lui seul. Mieux vaut se taire que proposer un chiffre que la matiere ne soutient pas.
MIN_POSITIVES_FOR_A_CUT = 30


def report(cases):
    """Print, per entity type, the two distributions and the cut they suggest.

    Only `positive-*` classes enter the arithmetic. The `observed-*` ones, values seen in the
    logs and never arbitrated, are shown apart: they calibrate nothing, but their low tail names
    the false acceptances already being served in production.
    """
    grouped = collections.defaultdict(lambda: collections.defaultdict(list))
    for case in cases:
        if case.get("fuzz_ratio") is None and case.get("distance") is None:
            continue
        grouped[case["type"]][case["klass"]].append(case)

    out = {}
    for etype in sorted(grouped):
        klasses = grouped[etype]
        pos = [c for k, v in klasses.items() if k.startswith("positive") for c in v]
        neg_all = [c for k, v in klasses.items() if k.startswith("negative") for c in v]
        neg = [c for c in neg_all if not c.get("contaminated")]
        dirty = [c for c in neg_all if c.get("contaminated")]
        observed = [c for k, v in klasses.items() if k.startswith("observed") for c in v]

        print("\n### %s   %d positifs, %d negatifs%s" % (
            etype, len(pos), len(neg),
            " (%d croisements ecartes, candidat legitime)" % len(dirty) if dirty else ""))
        if not pos or not neg:
            print("   pas assez de matiere pour proposer un seuil")
            continue

        entry = {"positives": len(pos), "negatives": len(neg), "contaminated": len(dirty)}
        for field, higher in (("fuzz_ratio", True), ("distance", False)):
            pv = sorted(c[field] for c in pos if isinstance(c.get(field), (int, float)))
            nv = sorted(c[field] for c in neg if isinstance(c.get(field), (int, float)))
            if not pv or not nv:
                continue
            print("   %-11s positifs n=%d med=%.1f min=%.1f | negatifs n=%d med=%.1f max=%.1f"
                  % (field, len(pv), pv[len(pv) // 2], pv[0], len(nv), nv[len(nv) // 2], nv[-1]))
            if len(pv) < MIN_POSITIVES_FOR_A_CUT:
                # Lived case: on Collection_name, 98 of 119 positives resolve through rapidfuzz
                # and carry no vector distance at all. The remaining 21 are precisely the ones
                # rapidfuzz missed, so the sample is both small AND biased towards the hard
                # cases, and its flattering cut means nothing.
                # Deux causes tres differentes, et les confondre egare. Soit le corpus entier
                # est petit (--limit-per-type bas), soit le champ ne couvre qu'une minorite des
                # positifs, et cette minorite est alors biaisee : sur Collection_name, 98 des 119
                # positifs resolvent par rapidfuzz sans distance vectorielle, et les 21 qui en
                # ont une sont precisement ceux que rapidfuzz a rates, donc les plus difficiles.
                total_pos = len(pos)
                if len(pv) >= total_pos * 0.8:
                    print("   %-11s AUCUNE recommandation : %d positifs mesures seulement,"
                          % ("", len(pv)))
                    print("   %-11s corpus trop petit pour poser un seuil" % "")
                else:
                    print("   %-11s AUCUNE recommandation : %d positifs sur %d seulement portent"
                          % ("", len(pv), total_pos))
                    print("   %-11s ce champ, et ce sont ceux que l'autre voie a rates,"
                          % "")
                    print("   %-11s donc un echantillon petit ET biaise" % "")
                entry[field] = {"skipped": "echantillon insuffisant", "positives": len(pv)}
                continue
            cut = best_cut(pv, nv, higher)
            if cut:
                sense = ">=" if higher else "<="
                print("   %-11s seuil propose %s %.2f  (legitimes refuses %d, intrus acceptes %d)"
                      % ("", sense, cut.get("robust_cut", cut["cut"]),
                         cut["legitimate_refused"], cut["strangers_accepted"]))
                if cut.get("equivalent_from") is not None and cut["equivalent_from"] != cut["equivalent_to"]:
                    print("   %-11s tout seuil de %.2f a %.2f donne le meme resultat ; le milieu"
                          % ("", cut["equivalent_from"], cut["equivalent_to"]))
                    print("   %-11s est retenu comme le plus eloigne des deux distributions" % "")
                entry[field] = cut

        if observed:
            ov = sorted(c["fuzz_ratio"] for c in observed
                        if isinstance(c.get("fuzz_ratio"), (int, float)))
            if ov:
                low = [c for c in observed
                       if isinstance(c.get("fuzz_ratio"), (int, float)) and c["fuzz_ratio"] < 50]
                print("   observe    n=%d med=%.1f, dont %d sous 50 : autant de resolutions"
                      % (len(ov), ov[len(ov) // 2], len(low)))
                print("              deja servies en production et probablement fausses")
                for c in sorted(low, key=lambda x: x["fuzz_ratio"])[:5]:
                    print("                r=%5.1f  %-26s -> %s"
                          % (c["fuzz_ratio"], str(c["value"])[:26], str(c.get("candidate"))[:36]))
                entry["observed_below_50"] = len(low)

        # Un seuil se pose PAR STRATEGIE, pas par entite. Quand les cas d'un type se resolvent
        # par plusieurs tables, on rend une coupe pour chacune : c'est ce qui permet de calibrer
        # la table des alias de Person_name, restee immesurable tant que la premiere strategie
        # resolvait toujours et l'empechait d'etre atteinte.
        # La classe appartient au couple (cas, strategie), pas au cas. Une valeur tiree de la
        # table T est un positif pour la strategie qui interroge T, et un NEGATIF pour toute
        # autre : "Rien All Ahmet" vient de la table des alias, donc la table des personnes a
        # raison de la refuser. Ces cas font les meilleurs negatifs dont on dispose, bien
        # meilleurs que l'injection croisee, puisque ce sont de vrais noms de personnes qui
        # n'appartiennent authentiquement pas a la table interrogee.
        all_cases = pos + neg + [c for k, v in klasses.items() if k.startswith("observed") for c in v]
        tables = {s.get("table") for c in all_cases for s in (c.get("scores") or []) if s.get("table")}
        if len(tables) > 1:
            print("   --- par strategie, car un seuil se pose par strategie ---")
            for table in sorted(tables):
                pv, nv = [], []
                for c in all_cases:
                    for s in (c.get("scores") or []):
                        if s.get("table") != table:
                            continue
                        r = s.get("fuzz_ratio")
                        if not isinstance(r, (int, float)):
                            continue
                        k = c["klass"]
                        if k.startswith("observed"):
                            continue
                        if k.startswith("positive-catalogue"):
                            (pv if c.get("source") == table else nv).append(r)
                        elif k.startswith("negative"):
                            nv.append(r)
                        elif not s.get("rejected"):
                            pv.append(r)
                pv.sort(); nv.sort()
                if not pv or not nv:
                    print("   %-28s %d positifs, %d negatifs : trop peu pour une coupe"
                          % (table[:28], len(pv), len(nv)))
                    continue
                tcut = best_cut(pv, nv, True)
                print("   %-28s pos n=%d med=%.1f min=%.1f | neg n=%d max=%.1f"
                      % (table[:28], len(pv), pv[len(pv) // 2], pv[0], len(nv), nv[-1]))
                if tcut:
                    print("   %-28s seuil >= %.2f (%d refuses, %d admis), equivalent de %.2f a %.2f"
                          % ("", tcut.get("robust_cut", tcut["cut"]), tcut["legitimate_refused"],
                             tcut["strangers_accepted"], tcut["equivalent_from"], tcut["equivalent_to"]))
                    entry.setdefault("par_strategie", {})[table] = tcut

        if dirty:
            print("   croisements ecartes, le candidat contient la valeur injectee :")
            for c in dirty[:4]:
                print("                r=%5.1f  %-26s -> %s"
                      % (c.get("fuzz_ratio") or 0, str(c["value"])[:26], str(c.get("candidate"))[:36]))

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
    api = None
    if not args.build_only and args.catalogue_per_type:
        # L'import de main est remonte ici : le tirage au catalogue a besoin des collections
        # ChromaDB, qui n'existent qu'apres le demarrage du module.
        import main as api  # noqa: F401
        connection = get_db_connection()
        catalogue = sample_from_catalogue(
            connection, api.CHROMADB_COLLECTIONS_BY_NAME, types_filter,
            args.catalogue_per_type, random.Random(args.seed))
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
        if api is None:
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
