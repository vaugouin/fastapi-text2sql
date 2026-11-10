"""FASTAPI-TEXT2SQL-374: offline bench of a name lexicon for Award_name, ahead of the ChromaDB
collection 'awards', against what production returned.

The case: "Oscar de la meilleure actrice" resolved to 'Ophir de la meilleure actrice' (award
15014) because the French document of award 269 was not among the ten nearest neighbours, and
nothing looked the name up in T_WC_T2S_AWARD. The question here: what does each stage of
``title_lexicon.TitleLexicon`` (exact, prefix, fuzzy) do on the award mentions production has
already seen, and how ambiguous are the names themselves?

Inputs
------
- The award pool exported by ``doc/sql/check-374-export-award-pool.sql`` (voie 1), raw gate output
  in ``../shared_data/fastapi-text2sql/bench-374/raw-awards.txt`` (not versioned), parsed here to
  ``awards.tsv`` (ID, POP, PERSONS, MOVIES, SERIES, TYPE, PARENT, WIKIDATA, NAME, NAME_FR).
- Mentions: the evaluation execution exports of every version and the API logs, as in
  ``bench-lexical-360-names.py``; gold ids from the bank's ``query_result`` assertions.

What it measures
----------------
For each distinct folded mention, three variants of the production lexicon on AWARD_NAME and
AWARD_NAME_FR, ranked by winners (PERSON_COUNT + MOVIE_COUNT + SERIE_COUNT) then popularity:
``exact`` (stages ["exact"], the candidate for production), ``prefix`` (exact + prefix) and
``all`` (plus fuzzy at the default 85.85, unmeasured, shown for information only).

Usage (from the repository root)::

    uv run --no-project --with-requirements requirements.txt python checks/bench-lexical-374-awards.py

Writes ``bench-lexical-374-awards.csv`` (one row per distinct mention) and a summary on stdout.
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = os.path.dirname(ROOT)
BENCH = os.path.join(CODE, "shared_data", "fastapi-text2sql", "bench-374")
EXPORTS = os.environ.get("TEXT2SQL_EVAL_EXPORT_DIR") or os.path.join(
    CODE, "shared_data", "text2sql-eval", "evaluation_execution")
LOGS = os.path.join(CODE, "shared_data", "fastapi-text2sql", "logs")
BANK = os.path.join(CODE, "text2sql-eval", "data", "evaluation")

sys.path.insert(0, ROOT)
import title_lexicon as tl  # noqa: E402

FIELDS = ["ID", "POP", "PERSONS", "MOVIES", "SERIES", "TYPE", "PARENT", "WIKIDATA", "NAME", "NAME_FR"]
VARIANTS = {"exact": ["exact"], "prefix": ["exact", "prefix"], "all": None}


def parse_raw(raw_path: str, tsv_path: str) -> int:
    """Gate output (padded table of packed records) -> one award per line."""
    n = 0
    with open(raw_path, encoding="utf-8") as fh, open(tsv_path, "w", encoding="utf-8", newline="\n") as out:
        out.write("\t".join(FIELDS) + "\n")
        for line in fh:
            if "\x1f" not in line:
                continue
            # str.strip() would eat CHAR(31) itself (a whitespace for Python) and with it the
            # empty trailing fields of the last record of a row: strip spaces and newlines only.
            body = line.strip(" \r\n")
            body = body[1:-1].strip(" ") if body.startswith("|") and body.endswith("|") else body
            for rec in body.split("@@REC@@"):
                f = rec.split("\x1f")
                if len(f) != len(FIELDS):
                    raise ValueError(f"record with {len(f)} fields: {rec[:80]!r}")
                out.write("\t".join(x.replace("\t", " ").strip() for x in f) + "\n")
                n += 1
    return n


def pool(path: str):
    with open(path, encoding="utf-8") as fh:
        fh.readline()
        for line in fh:
            f = line.rstrip("\n").split("\t")
            yield dict(zip(FIELDS, f))


def rows(path: str):
    for a in pool(path):
        yield (a["ID"], "", int(a["PERSONS"]) + int(a["MOVIES"]) + int(a["SERIES"]), a["POP"],
               a["NAME"], a["NAME_FR"])


def bank_ids(eid) -> set:
    out = set()
    for p in glob.glob(os.path.join(BANK, f"{eid}_*.json")):
        try:
            a = (json.load(open(p, encoding="utf-8")).get("assertions") or {}).get("query_result") or ""
        except ValueError:
            continue
        for m in re.finditer(r"ID_AWARD\s*(?:IN\s*\(([^)]*)\)|=\s*(\d+))", a):
            out |= {int(x) for x in re.findall(r"\d+", m.group(1) or m.group(2))}
    return out


def events_of(ao):
    for e in ao.get("entity_match_scores") or []:
        ph = (e.get("placeholder") or "").strip("{}")
        if re.sub(r"\d+$", "", ph) == "Award_name" and e.get("sought"):
            yield e


def harvest(use_logs=True):
    out = []
    for d in sorted(glob.glob(os.path.join(EXPORTS, "0*"))):
        for p in glob.glob(os.path.join(d, "*.json")):
            raw = open(p, encoding="utf-8").read()
            if "Award_name" not in raw:
                continue
            j = json.loads(raw)
            ao = j.get("api_output") or {}
            passed = (j.get("scoring") or {}).get("assertions_total_score") == 1
            for e in events_of(ao):
                out.append(dict(src="eval", eid=j["evaluation_id"], passed=passed, e=e,
                                question=ao.get("question") or ""))
    if use_logs:
        for p in glob.glob(os.path.join(LOGS, "*text2sql_post*.json")):
            raw = open(p, encoding="utf-8", errors="replace").read()
            if "Award_name" not in raw:
                continue
            try:
                j = json.loads(raw)
            except ValueError:
                continue
            ao = j.get("response") or {}
            if isinstance(ao, dict):
                for e in events_of(ao):
                    out.append(dict(src="log", eid=None, passed=None, e=e, question=ao.get("question") or ""))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.path.join(BENCH, "raw-awards.txt"))
    ap.add_argument("--pool", default=os.path.join(BENCH, "awards.tsv"))
    ap.add_argument("--out", default=BENCH)
    ap.add_argument("--no-logs", action="store_true")
    args = ap.parse_args()

    if os.path.exists(args.raw) and (not os.path.exists(args.pool)
                                     or os.path.getmtime(args.raw) > os.path.getmtime(args.pool)):
        print(f"parsed {parse_raw(args.raw, args.pool)} awards from {args.raw}")

    awards = {int(a["ID"]): a for a in pool(args.pool)}
    lex = tl.TitleLexicon(rows(args.pool), ["AWARD_NAME", "AWARD_NAME_FR"])
    print(f"lexicon: {len(lex)} awards, {len(lex.keys)} folded forms, build {lex.build_seconds}s")

    # ---- homonyms: a folded form carried by several awards
    forms = collections.defaultdict(lambda: {"en": set(), "fr": set()})
    for i, a in awards.items():
        if a["NAME"]:
            forms[tl.fold(a["NAME"])]["en"].add(i)
        if a["NAME_FR"]:
            forms[tl.fold(a["NAME_FR"])]["fr"].add(i)
    forms.pop("", None)
    shared = {k: v["en"] | v["fr"] for k, v in forms.items() if len(v["en"] | v["fr"]) > 1}

    def winners(i):
        a = awards[i]
        return int(a["PERSONS"]) + int(a["MOVIES"]) + int(a["SERIES"])

    tied = {k: ids for k, ids in shared.items()
            if sorted((winners(i) for i in ids), reverse=True)[0] == sorted((winners(i) for i in ids), reverse=True)[1]}
    cross = {k for k, v in forms.items() if v["en"] and v["fr"] and v["en"] != v["fr"] and not (v["en"] & v["fr"])}
    print(f"\n== homonyms: {len(shared)} folded forms carried by several awards "
          f"({sum(len(v) for v in shared.values())} awards), {len(tied)} with a tie on winners at the top; "
          f"{len(cross)} forms that are the EN name of one award and the FR name of another only")
    for k, ids in sorted(shared.items(), key=lambda kv: -max(winners(i) for i in kv[1]))[:15]:
        print("  " + k + ": " + ", ".join(f"{i} ({winners(i)} winners, {awards[i]['TYPE'] or '-'})"
                                          for i in sorted(ids, key=lambda i: -winners(i))[:4]))

    # ---- mentions
    events = harvest(not args.no_logs)
    print(f"\n{len(events)} Award_name mention events ({sum(r['src'] == 'eval' for r in events)} from evaluation exports)")
    groups = collections.OrderedDict()
    for r in events:
        groups.setdefault(tl.fold(r["e"]["sought"]), []).append(r)

    out_rows = []
    for _, evs in groups.items():
        sought = evs[0]["e"]["sought"]
        gold = set()
        for r in evs:
            if r["eid"] is not None:
                gold |= bank_ids(r["eid"])
        accepted = [r for r in evs if not r["e"].get("rejected")]
        prod_ids = collections.Counter()
        for r in accepted:
            m = re.search(r"_(\d+)_", r["e"].get("candidate_id") or "")
            if m:
                prod_ids[int(m.group(1))] += 1
        pe = (accepted or evs)[-1]["e"]
        m = re.search(r"_(\d+)_", pe.get("candidate_id") or "") if accepted else None
        pid = int(m.group(1)) if m else ""
        if accepted and pid == "":
            # Older exports carry no candidate_id: map the candidate's name, when a single award has it.
            ids = forms.get(tl.fold(pe.get("candidate") or ""))
            ids = (ids["en"] | ids["fr"]) if ids else set()
            pid = next(iter(ids)) if len(ids) == 1 else ""
        row = dict(sought=sought, n_events=len(evs), n_eval=sum(r["src"] == "eval" for r in evs),
                   eids=" ".join(sorted({str(r["eid"]) for r in evs if r["eid"] is not None})),
                   prod_id=pid, prod_name=pe.get("candidate") or "", prod_ratio=pe.get("fuzz_ratio"),
                   prod_rejected=not accepted, prod_ids=" ".join(f"{i}x{n}" for i, n in prod_ids.most_common()))
        for tag, stages in VARIANTS.items():
            res = lex.lookup(sought, None, 85.85, stages)
            ids = [x[0] for x in res["matches"]]
            row[f"{tag}_stage"] = res["stage"]
            row[f"{tag}_id"] = ids[0] if ids else ""
            row[f"{tag}_name"] = awards[ids[0]]["NAME"] if ids else ""
            row[f"{tag}_col"] = res["matches"][0][1] if ids else ""
            row[f"{tag}_n"] = res.get("n_candidates", 0)
        row["gold"] = " ".join(map(str, sorted(gold)))
        for tag in ("prod",) + tuple(VARIANTS):
            row[f"{tag}_ok"] = "" if not gold else int(row[f"{tag}_id"] in gold)
        row["question"] = evs[0]["question"][:160]
        out_rows.append(row)

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "bench-lexical-374-awards.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)

    gs = [r for r in out_rows if r["gold"]]
    print(f"{len(out_rows)} distinct mentions ({sum(r['n_eval'] > 0 for r in out_rows)} in evaluations), {len(gs)} with gold")
    print(f"production: accepted {sum(not r['prod_rejected'] for r in out_rows)}, rejected {sum(r['prod_rejected'] for r in out_rows)}; "
          f"P@1 on gold {sum(r['prod_ok'] == 1 for r in gs)}/{len(gs)}")
    for tag in VARIANTS:
        hit = [r for r in out_rows if r[f"{tag}_id"] != ""]
        both = [r for r in hit if not r["prod_rejected"]]
        diff = [r for r in both if r["prod_id"] != r[f"{tag}_id"]]
        print(f"\n== {tag}: stages {dict(collections.Counter(r[tag + '_stage'] for r in out_rows))}; "
              f"hits {len(hit)}/{len(out_rows)}; P@1 on gold among hits "
              f"{sum(r[tag + '_ok'] == 1 for r in hit if r['gold'])}/{sum(1 for r in hit if r['gold'])}")
        print(f"  both answer {len(both)}: same id {len(both) - len(diff)}, different {len(diff)}; "
              f"lexicon only (production rejected) {sum(1 for r in hit if r['prod_rejected'])}")
        for r in diff[:40]:
            print(f"    '{r['sought']}': production {r['prod_id']} '{r['prod_name']}' / {tag} {r[tag + '_id']} "
                  f"'{r[tag + '_name']}' ({r[tag + '_stage']}, {r[tag + '_col']}, {r[tag + '_n']} cand.)"
                  f"{' gold ' + r['gold'] if r['gold'] else ''} [{r['n_events']} ev.]")
        for r in [r for r in hit if r["prod_rejected"]][:15]:
            print(f"    '{r['sought']}': production rejected / {tag} {r[tag + '_id']} '{r[tag + '_name']}' ({r[tag + '_stage']})")
    print(f"\nwritten {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
