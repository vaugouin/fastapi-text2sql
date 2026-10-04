#!/usr/bin/env python3
"""FASTAPI-TEXT2SQL-309: measure the gate's typographic rescue, stage by stage, on one corpus.

THE QUESTION
The embeddings search returns ten candidates; the confidence gate (`min_fuzz_ratio`) refuses the
ones that do not look enough like the value sought. Some refusals are right (an invented name, a
value of another type), some are wrong (eval 475: "Bell' Antonio" refused against "Il
bell'Antonio" at 85.7 for a threshold of 85.85, a space typed after the elision). The rescue
scores the same ten candidates again on normalised strings, same threshold, and only when the
gate refused all of them. This script measures what each set of normalisers rescues, and above
all what it lets through that it should not.

THE STAGES, ON THE SAME CODE AND THE SAME CORPUS
  none          the gate as it was before -309: no second pass (behaviour checked identical to the
                old code by eval/check-rescue-309.py, case 5)
  apostrophes   the first fix: apostrophe forms and the spaces around them
  full          apostrophes, accents, dashes, punctuation
  configured    each type with the list data/entity_resolution.json gives it: what production
                runs after its restart, the stage that decides the deployment
or any list with --normalizers. The stage is set IN MEMORY, on every embeddings strategy of the
types measured, whatever data/entity_resolution.json says; production is not touched. Same seed,
same corpus: the outcome of a value can only differ between two stages because of the stage.

THE CORPUS, BY CLASS
  refused-observed      every distinct value a gate refused in the evaluation exports (read from
                        the traces). Right or wrong is read from the row's result assertion
                        (`ID_MOVIE IN (...)`) when it names the type's id column; otherwise
                        `unknown`, listed for a human.
  positive-catalogue    values drawn from the resolver's own ChromaDB collection: must resolve to
                        themselves.
  positive-variant-*    catalogue values that contain an apostrophe, an accent, a dash or some
                        punctuation, retyped the way a user types them (space after the
                        apostrophe, curly apostrophe, accents dropped, dash as a space,
                        punctuation dropped). Must resolve to the value they come from.
  negative-cross        a catalogue value of another type: must be refused.
  negative-invent       made-up names, some with an apostrophe, an accent or a dash, so the
                        normalisers get a chance to let them through: must be refused.

READING THE RESULT
Per type and class: cases, accepted on the right id, accepted on a WRONG id, refused, and how many
acceptances came from the rescue. The bar of the ticket: a stage is adoptable for a type only if
it adds no wrong acceptance (negatives accepted, positives accepted on another id) against
`none`. `--compare` lists every value whose outcome changed between two saved stages, which is
the list to read before switching a stage on in the configuration.

RUNS IN DOCKER, NEVER WITH uv ON THE VPS: see eval/eval-309.sh, which runs this file in a
throwaway container built from the API image, with the checkout mounted read-only.

    python eval/eval-309.py --stage none
    python eval/eval-309.py --stage apostrophes
    python eval/eval-309.py --stage full
    python eval/eval-309.py --compare /shared/eval-309/<a>.json /shared/eval-309/<b>.json
"""
import argparse
import collections
import datetime
import glob
import io
import json
import os
import random
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

INVENTED = [
    "Zorglub", "Bibendum", "Wagonlit", "Kraglinov", "Pentafrag", "Vorzimmer", "Quillebeuf",
    "Zamboni-Trask", "Mirlitonde", "Halvorsen-Puig",
    # The same family, given what the normalisers act on, so they get every chance to admit one.
    "Zorglub l' Ancien", "L’ Étrange Bibendum", "Kraglinov-Pétrin", "Pentafrag: Le Retour!",
    "Mirlitonde à l'été", "Quillebeuf & Fils",
]

# The characters a variant class is built around, and how a user retypes them.
VARIANT_PROBES = {
    "apostrophe": "'",
    "accent": ["é", "è", "ê", "à", "ç", "ô", "ü", "ñ", "ï", "â"],
    "dash": "-",
    "punctuation": [":", "!", "?", "."],
}

_REFUSAL_RE = re.compile(
    r"Entity resolution: \{\{(?P<key>(?P<type>[A-Za-z_]+?)\d*)\}\} -> rejected best embeddings candidate ")
_FALLBACK_RE = re.compile(r"Entity resolution: \{\{(?P<key>[A-Za-z_]+\d*)\}\} -> (?P<value>.*) \(raw fallback")
_ASSERT_RE = re.compile(r"Statement: (ID_[A-Z_]+) IN \(([\d,\s]+)\)")


def _accents_off(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def variants_of(value):
    """The ways a user retypes a catalogue value, by kind; only those that differ from it."""
    out = []
    if "'" in value:
        spaced = re.sub(r"'(?=\w)", "' ", value)
        if spaced != value:
            out.append(("apostrophe-space", spaced))
        out.append(("apostrophe-curly", value.replace("'", "’")))
    folded = _accents_off(value)
    if folded != value:
        out.append(("accent-dropped", folded))
    if "-" in value:
        out.append(("dash-as-space", value.replace("-", " ")))
    stripped = re.sub(r"\s+", " ", re.sub(r"[.,:;!?]", " ", value)).strip()
    if stripped != value:
        out.append(("punctuation-dropped", stripped))
    return out


def gated_types(config):
    """Embeddings strategies carrying a gate, by type: the only ones a rescue can act on."""
    found = {}
    for entry in config:
        for strategy in entry.get("search_list") or []:
            if strategy.get("search_mode") == "embeddings" and strategy.get("min_fuzz_ratio") is not None:
                found.setdefault(entry["placeholder_prefix"], strategy)
    return found


def doc_id(chroma_id):
    parts = str(chroma_id or "").split("_")
    return parts[1] if len(parts) > 1 else None


def draw_catalogue(collections_by_name, strategies, per_type, rng):
    """Plain catalogue values, and values chosen for the characters the normalisers act on."""
    plain, probed = collections.defaultdict(list), collections.defaultdict(list)
    for etype, strategy in strategies.items():
        coll = collections_by_name.get(strategy.get("collection"))
        if coll is None:
            print(f"[warn] {etype}: collection {strategy.get('collection')} unavailable, type skipped")
            continue
        sep = strategy.get("document_name_separator")

        def bare(doc):
            doc = doc.strip()
            return doc.split(sep, 1)[0].strip() if sep and sep in doc else doc

        try:
            got = coll.get(limit=max(per_type * 5, 50), include=["documents"])
            pairs = [(bare(d), doc_id(i)) for d, i in zip(got.get("documents") or [], got.get("ids") or [])
                     if isinstance(d, str) and d.strip()]
            rng.shuffle(pairs)
            plain[etype] = pairs[:per_type]
        except Exception as exc:
            print(f"[warn] {etype}: catalogue draw failed: {exc}")
        for kind, chars in VARIANT_PROBES.items():
            seen = set()
            for ch in ([chars] if isinstance(chars, str) else chars):
                try:
                    got = coll.get(where_document={"$contains": ch}, limit=per_type, include=["documents"])
                except Exception as exc:
                    print(f"[warn] {etype}: draw on '{ch}' failed: {exc}")
                    continue
                for d, i in zip(got.get("documents") or [], got.get("ids") or []):
                    if isinstance(d, str) and ch in bare(d) and doc_id(i) not in seen:
                        seen.add(doc_id(i))
                        probed[etype].append((bare(d), doc_id(i), kind))
            # keep the probe classes balanced against the plain draw
        rng.shuffle(probed[etype])
        probed[etype] = probed[etype][: per_type * 4]
    return plain, probed


def observed_refusals(exports_dir, strategies):
    """Distinct (type, value) the gate refused in the exports, with the ids the row expected."""
    found = {}
    id_col = {t: s.get("strtableid") for t, s in strategies.items()}
    for path in glob.glob(os.path.join(exports_dir, "evaluation_execution", "*", "*.json")):
        try:
            row = json.load(io.open(path, encoding="utf-8"))
        except Exception:
            continue
        texts = [m.get("text", "") if isinstance(m, dict) else str(m)
                 for m in (row.get("api_output") or {}).get("messages") or []]
        asserted = collections.defaultdict(set)
        for col, ids in _ASSERT_RE.findall((row.get("scoring") or {}).get("assertions_result_detailed") or ""):
            asserted[col].update(i.strip() for i in ids.split(",") if i.strip())
        for i, text in enumerate(texts):
            m = _REFUSAL_RE.search(text)
            if not m or m.group("type") not in strategies:
                continue
            for later in texts[i + 1:i + 4]:
                f = _FALLBACK_RE.search(later)
                if f and f.group("key") == m.group("key"):
                    key = (m.group("type"), f.group("value"))
                    entry = found.setdefault(key, {"expected_ids": set(), "rows": set()})
                    entry["expected_ids"].update(asserted.get(id_col.get(m.group("type")), set()))
                    entry["rows"].add(f"{row.get('evaluation_id')}/{row.get('language')}")
                    break
    return found


def build_corpus(plain, probed, refused, strategies, rng):
    cases = []
    for (etype, value), entry in sorted(refused.items()):
        cases.append({"type": etype, "value": value, "klass": "refused-observed",
                      "expected_ids": sorted(entry["expected_ids"]), "rows": sorted(entry["rows"])})
    for etype, pairs in plain.items():
        for value, vid in pairs:
            cases.append({"type": etype, "value": value, "klass": "positive-catalogue", "expected_ids": [vid]})
    for etype, triples in probed.items():
        seen = set()
        for value, vid, _kind in triples:
            for vkind, variant in variants_of(value):
                if (etype, variant) in seen:
                    continue
                seen.add((etype, variant))
                cases.append({"type": etype, "value": variant, "klass": f"positive-variant-{vkind}",
                              "expected_ids": [vid], "source_value": value})
    types = sorted(strategies)
    for etype in types:
        others = [t for t in types if t != etype and plain.get(t)]
        for n in range(min(20, len(others) * 4)):
            src = others[n % len(others)]
            value, _ = rng.choice(plain[src])
            cases.append({"type": etype, "value": value, "klass": "negative-cross", "borrowed_from": src})
        for name in INVENTED:
            cases.append({"type": etype, "value": name, "klass": "negative-invent"})
    return cases


def set_stage(entity_module, types, normalizers):
    for entry in entity_module.ENTITY_RESOLUTION_CONFIG:
        if entry.get("placeholder_prefix") not in types:
            continue
        for strategy in entry.get("search_list") or []:
            if strategy.get("search_mode") != "embeddings":
                continue
            if normalizers:
                strategy["rescue_normalizations"] = list(normalizers)
            else:
                strategy.pop("rescue_normalizations", None)


def resolve(entity_module, connection, collections_by_name, case):
    key = case["type"] + "1"
    try:
        plan = entity_module.plan_entity_resolutions(
            connection=connection,
            entity_extraction={"question": "about {{" + key + "}}", key: case["value"]},
            chromadb_collections_by_name=collections_by_name,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    scores = [s for s in (plan.get("match_scores") or [])
              if s.get("search_mode") == "embeddings" and re.sub(r"\d+$", "", str(s.get("placeholder", "")).strip("{} ")) == case["type"]]
    if not scores:
        return {"outcome": "not-reached"}
    won = [s for s in scores if not s.get("rejected")]
    s = won[-1] if won else scores[-1]
    found_id = doc_id(s.get("candidate_id"))
    out = {"candidate": s.get("candidate"), "candidate_id": found_id, "fuzz_ratio": s.get("fuzz_ratio"),
           "fuzz_ratio_first_pass": s.get("fuzz_ratio_first_pass"), "distance": s.get("distance"),
           "rescued": bool(s.get("rescue_normalizations")), "exact": bool(s.get("exact_match"))}
    if not won:
        out["outcome"] = "refused"
    elif case["klass"].startswith("negative"):
        out["outcome"] = "accepted-wrong"
    elif case.get("expected_ids"):
        out["outcome"] = "accepted-right" if found_id in case["expected_ids"] else "accepted-wrong"
    else:
        out["outcome"] = "accepted-unknown"
    out["outcome"] = effective_outcome(case, out)
    return out


def effective_outcome(case, result):
    """`accepted-homonym` for a positive accepted on ANOTHER id that carries the SAME title: two
    films "S.O.S. Fantômes" (1984, 2016), two networks "E!". The gate cannot tell them apart and is
    not meant to (the year does that, downstream), so counting them as wrong acceptances raised two
    false alarms in the run of 2026-10-04. Applied when reading too, so older files benefit."""
    outcome = result.get("outcome")
    if outcome != "accepted-wrong" or case.get("klass", "").startswith("negative"):
        return outcome
    expected_title = case.get("source_value") or (case.get("value") if case.get("klass") == "positive-catalogue" else None)
    candidate = (result.get("candidate") or "").strip().lower()
    if expected_title and candidate and candidate == expected_title.strip().lower():
        return "accepted-homonym"
    return outcome


def summarise(cases):
    table = collections.defaultdict(collections.Counter)
    for c in cases:
        r = c.get("result") or {}
        row = table[(c["type"], c["klass"])]
        row["cases"] += 1
        row[r.get("outcome", "error")] += 1
        if r.get("rescued") and str(r.get("outcome", "")).startswith("accepted"):
            row["rescued"] += 1
    print("\n   %-16s %-32s %5s %7s %7s %8s %7s %7s %7s" % (
        "type", "class", "cases", "right", "WRONG", "homonym", "unknown", "refused", "rescued"))
    for (etype, klass), row in sorted(table.items()):
        print("   %-16s %-32s %5d %7d %7d %8d %7d %7d %7d" % (
            etype[:16], klass[:32], row["cases"], row["accepted-right"], row["accepted-wrong"],
            row["accepted-homonym"], row["accepted-unknown"], row["refused"], row["rescued"]))
    return {f"{t}|{k}": dict(v) for (t, k), v in table.items()}


def compare(paths):
    runs = []
    for p in paths:
        data = json.load(io.open(p, encoding="utf-8"))
        runs.append((data.get("stage"), {(c["type"], c["klass"], c["value"]): c for c in data["cases"]}))
    base_name, base = runs[0]
    for name, other in runs[1:]:
        print(f"\n=== {base_name} -> {name}: values whose outcome changed ===")
        changed = collections.Counter()
        for key in sorted(set(base) & set(other)):
            ra, rb = base[key].get("result") or {}, other[key].get("result") or {}
            a, b = effective_outcome(base[key], ra), effective_outcome(other[key], rb)
            if a != b:
                changed[(key[0], key[1], a, b)] += 1
                print(f"   {key[0]:<16} {key[1]:<32} {key[2][:40]:<40} {a} -> {b} "
                      f"[{rb.get('candidate')!s:.40}] id={rb.get('candidate_id')} r={rb.get('fuzz_ratio')} "
                      f"(first pass {rb.get('fuzz_ratio_first_pass')})")
        print("\n   summary of changes:")
        for (t, k, a, b), n in sorted(changed.items()):
            print(f"   {t:<16} {k:<32} {a} -> {b}: {n}")
        wrong = sum(n for (t, k, a, b), n in changed.items() if b == "accepted-wrong")
        unknown = sum(n for (t, k, a, b), n in changed.items() if b == "accepted-unknown")
        homonym = sum(n for (t, k, a, b), n in changed.items() if b == "accepted-homonym")
        print(f"\n   NEW WRONG ACCEPTANCES: {wrong}  (the bar: 0 for a type to adopt the stage)")
        # The unknowns are values the gate refused in production and no assertion arbitrates. They
        # are where the 2026-10-04 run hid its two real errors (Warner Bros. China, Dracula 2000 -
        # Saga), so they are counted apart and must be READ, never assumed right.
        print(f"   NEW UNKNOWN ACCEPTANCES: {unknown}  (no assertion: read each one above)")
        print(f"   NEW HOMONYM ACCEPTANCES: {homonym}  (same title, another id: not a gate error)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=["none", "apostrophes", "full", "configured"], default=None,
                        help="configured: each type keeps the rescue_normalizations of data/entity_resolution.json, "
                             "what production will run after its restart")
    parser.add_argument("--normalizers", default=None, help="comma-separated list, instead of --stage")
    parser.add_argument("--types", default="", help="comma-separated types (default: every gated embeddings type)")
    parser.add_argument("--per-type", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20261004)
    parser.add_argument("--exports-dir", default=os.environ.get("TEXT2SQL_EVAL_EXPORT_DIR", "/shared"))
    parser.add_argument("--out", default=None, help="default: <exports-dir>/eval-309/<stage>-<timestamp>.json")
    parser.add_argument("--compare", nargs="+", default=None, help="saved runs to compare, first is the base")
    args = parser.parse_args()

    if args.compare:
        compare(args.compare)
        return 0

    import rapidfuzz_query
    # Every stage, `none` included, runs on the -309 code: `none` removes the second pass and is
    # then the gate as it was, to the letter (eval/check-rescue-309.py, case 5). The old code
    # cannot serve as the baseline here, since it does not report the candidate's id.
    if not hasattr(rapidfuzz_query, "RESCUE_STAGES"):
        sys.exit("This checkout predates FASTAPI-TEXT2SQL-309: git pull in the API checkout first. "
                 "Pulling does not change production until its restart.sh is run.")
    if args.normalizers is not None:
        normalizers = [n.strip() for n in args.normalizers.split(",") if n.strip()]
        stage = "+".join(normalizers) or "none"
    else:
        stage = args.stage or "none"
        normalizers = None if stage == "configured" else rapidfuzz_query.RESCUE_STAGES[stage]

    print(f"=== FASTAPI-TEXT2SQL-309 evaluation, stage '{stage}' {normalizers} ===", flush=True)
    import main as api  # connects ChromaDB and MariaDB like the API does at startup
    import entity

    strategies = gated_types(entity.ENTITY_RESOLUTION_CONFIG)
    wanted = [t.strip() for t in args.types.split(",") if t.strip()] or sorted(strategies)
    strategies = {t: s for t, s in strategies.items() if t in wanted}
    print("Types: " + ", ".join(sorted(strategies)), flush=True)

    rng = random.Random(args.seed)
    plain, probed = draw_catalogue(api.CHROMADB_COLLECTIONS_BY_NAME, strategies, args.per_type, rng)
    refused = observed_refusals(args.exports_dir, strategies)
    cases = build_corpus(plain, probed, refused, strategies, rng)
    print("Corpus: " + ", ".join(f"{k}={v}" for k, v in sorted(collections.Counter(c["klass"] for c in cases).items())), flush=True)

    if normalizers is None:
        # `configured`: no override, each type runs the list its configuration declares.
        normalizers = {t: s.get("rescue_normalizations") or [] for t, s in sorted(strategies.items())}
        for t, n in normalizers.items():
            print(f"   {t}: {n or 'no rescue'}", flush=True)
    else:
        set_stage(entity, set(strategies), normalizers)
    connection = api.get_db_connection() if hasattr(api, "get_db_connection") else api.connection
    for n, case in enumerate(cases, 1):
        case["result"] = resolve(entity, connection, api.CHROMADB_COLLECTIONS_BY_NAME, case)
        if n % 200 == 0:
            print(f"   {n}/{len(cases)}", flush=True)

    summary = summarise(cases)
    out = args.out or os.path.join(args.exports_dir, "eval-309",
                                   f"{stage}-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"stage": stage, "normalizers": normalizers, "seed": args.seed, "per_type": args.per_type,
                   "types": sorted(strategies), "summary": summary, "cases": cases},
                  handle, ensure_ascii=False, indent=1, default=list)
    print(f"\nWritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
