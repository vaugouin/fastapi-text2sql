"""FASTAPI-TEXT2SQL-360: offline bench of a lexical candidate generator for Movie_title and
Serie_title against what ChromaDB returned in real campaigns.

Inputs
------
- The title pool exported by ``doc/sql/check-360-export-title-pool.sql`` (voie 1), parsed to
  ``pool.tsv`` (one row per living movie or series: TMDb EN/FR/original titles, Wikidata labels
  en/fr/mul and aliases en/fr). Default location:
  ``../shared_data/fastapi-text2sql/bench-360/pool.tsv`` (not versioned: about 90 MB).
- The execution exports of a campaign version (``../shared_data/text2sql-eval/evaluation_execution``
  or ``$TEXT2SQL_EVAL_EXPORT_DIR``): every Movie_title / Serie_title mention the extraction produced,
  with what the embeddings path accepted (``entity_match_scores``) and whether the evaluation passed.
- The evaluation bank (``../text2sql-eval/data/evaluation``): the ``query_result`` assertion gives
  the expected ids (``ID_MOVIE`` / ``ID_SERIE``) that serve as gold when one candidate carries them.

What it measures
----------------
For each distinct (type, mention, year), the production resolver ``title_lexicon.TitleLexicon``
(see its docstring for the stages, folding and ranking) on the TMDb forms (EN, FR, original), and
the same with a second tier of Wikidata labels and aliases tried only when the first misses. The
embeddings pick is mapped to an id through the exported ``candidate_id`` when present, otherwise
through its title (same ranking). Gold is the set of candidates (lexical top 10 or embeddings)
whose id appears in the evaluation's ``query_result`` assertion; a pick inside it counts as right.
Mentions without gold are listed in the CSV for a manual read.

Usage (from the repository root)::

    uv run checks/bench-lexical-360.py [--version 001.001.019] [--pool PATH] [--out DIR]

Writes ``bench-lexical-360-<version>.csv`` (one row per mention) and a summary on stdout.
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
import time

from rapidfuzz import fuzz, process

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = os.path.dirname(ROOT)
DEFAULT_POOL = os.path.join(CODE, "shared_data", "fastapi-text2sql", "bench-360", "pool.tsv")
EXPORTS = os.environ.get("TEXT2SQL_EVAL_EXPORT_DIR") or os.path.join(
    CODE, "shared_data", "text2sql-eval", "evaluation_execution")
BANK = os.path.join(CODE, "text2sql-eval", "data", "evaluation")

# Thresholds of data/entity_resolution.json today (embeddings strategies), reused for the
# lexical ratio gate so the comparison isolates the candidate source.
MIN_RATIO = {"Movie_title": 85.85, "Serie_title": 87.85}
FAMILY = {"Movie_title": "m", "Serie_title": "s"}
YEAR_KEY = {"Movie_title": "Release_year", "Serie_title": "First_air_year"}
ID_COL = {"Movie_title": "ID_MOVIE", "Serie_title": "ID_SERIE"}

sys.path.insert(0, ROOT)
import title_lexicon as tl  # noqa: E402

COLUMNS = {"m": ["MOVIE_TITLE", "MOVIE_TITLE_FR", "ORIGINAL_TITLE"],
           "s": ["SERIE_TITLE", "SERIE_TITLE_FR", "ORIGINAL_TITLE"]}


def fold(s):
    return tl.fold(s)


def pool_rows(path, family, wikidata=False):
    """TMDb rows (id, year, votes, pop, en, fr, orig), or with ``wikidata`` one row per Wikidata
    label or alias (id, year, votes, pop, form)."""
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        col = {c: i for i, c in enumerate(header)}
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if f[col["FAM"]] != family:
                continue
            head = (f[col["ID"]], f[col["YR"]], f[col["VOTES"]], f[col["POP"]])
            if not wikidata:
                yield head + (f[col["T_EN"]], f[col["T_FR"]], f[col["T_ORIG"]])
                continue
            forms = [f[col["WL_EN"]], f[col["WL_FR"]], f[col["WL_MUL"]]]
            for c in ("WA_EN", "WA_FR"):
                if f[col[c]].startswith("["):
                    try:
                        forms += json.loads(f[col[c]])
                    except ValueError:
                        pass
            for form in dict.fromkeys(x for x in forms if x):
                yield head + (form,)


# --------------------------------------------------------------------------- mentions

def bank_ids(eid: int, id_col: str):
    out = set()
    for p in glob.glob(os.path.join(BANK, f"{eid}_*.json")) + glob.glob(os.path.join(BANK, f"{eid}.json")):
        try:
            a = (json.load(open(p, encoding="utf-8")).get("assertions") or {}).get("query_result") or ""
        except ValueError:
            continue
        for m in re.finditer(id_col + r"\s*(?:IN\s*\(([^)]*)\)|=\s*(\d+))", a):
            out |= {int(x) for x in re.findall(r"\d+", m.group(1) or m.group(2))}
    return out


def harvest(version: str):
    rows = []
    for d in sorted(glob.glob(os.path.join(EXPORTS, version + "_*"))):
        camp = os.path.basename(d)
        latest = {}
        for p in glob.glob(os.path.join(d, "*.json")):
            j = json.load(open(p, encoding="utf-8"))
            eid, t = j["evaluation_id"], j.get("tim_execution") or ""
            if eid not in latest or t > latest[eid][0]:
                latest[eid] = (t, j)
        for eid, (_, j) in latest.items():
            ao = j.get("api_output") or {}
            ee = ao.get("entity_extraction") or {}
            passed = ((j.get("scoring") or {}).get("assertions_total_score") == 1)
            for e in ao.get("entity_match_scores") or []:
                ph = (e.get("placeholder") or "").strip("{}")
                typ = re.sub(r"\d+$", "", ph)
                if typ not in FAMILY:
                    continue
                year = tl.year_for_title(ee, ph, YEAR_KEY[typ])   # same rule as the API
                rows.append(dict(campaign=camp, eid=eid, type=typ, sought=e.get("sought") or "",
                                 year=year, chroma_title=e.get("candidate") or "",
                                 chroma_rejected=bool(e.get("rejected")),
                                 chroma_id=e.get("candidate_id") or "", passed=passed,
                                 question=ao.get("question") or ""))
    return rows


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="001.001.019")
    ap.add_argument("--pool", default=DEFAULT_POOL)
    ap.add_argument("--out", default=os.path.join(CODE, "shared_data", "fastapi-text2sql", "bench-360"))
    args = ap.parse_args()

    t0 = time.time()
    events = harvest(args.version)
    print(f"{len(events)} mention events from {args.version} exports")
    groups = collections.OrderedDict()
    for r in events:
        groups.setdefault((r["type"], fold(r["sought"]), r["year"]), []).append(r)

    lex = {}
    for typ, fam in FAMILY.items():
        lex[(typ, False)] = tl.TitleLexicon(pool_rows(args.pool, fam), COLUMNS[fam])
        lex[(typ, True)] = tl.TitleLexicon(pool_rows(args.pool, fam, wikidata=True), ["WIKIDATA"])
        print(f"lexicon {typ}: {len(lex[(typ, False)])} rows, {len(lex[(typ, False)].keys)} TMDb forms, "
              f"{len(lex[(typ, True)].keys)} Wikidata forms ({time.time() - t0:.0f}s)")

    out_rows = []
    for (typ, _, year), evs in groups.items():
        r0 = evs[0]
        gold_ids = set()
        for r in evs:
            gold_ids |= bank_ids(r["eid"], ID_COL[typ])
        row = dict(type=typ, sought=r0["sought"], year=year or "", n_events=len(evs),
                   eids=" ".join(sorted({str(r["eid"]) for r in evs})),
                   passed_share=round(sum(r["passed"] for r in evs) / len(evs), 2),
                   chroma_title=r0["chroma_title"],
                   chroma_rejected_share=round(sum(r["chroma_rejected"] for r in evs) / len(evs), 2))
        # embeddings pick -> id
        base = lex[(typ, False)]
        cid = next((r["chroma_id"] for r in evs if r["chroma_id"]), "")
        m = re.search(r"_(\d+)_", cid)
        if m:
            chroma_ids = [int(m.group(1))]
        else:
            k = base._exact(fold(r0["chroma_title"])) if r0["chroma_title"] else None
            codes = {}
            if k is not None:
                base._add(codes, base._codes_of_key(k))
            chroma_ids = [base.ids[e] for e, _ in base._rank(codes, year, set())][:10]
        row["chroma_id"] = chroma_ids[0] if chroma_ids and row["chroma_rejected_share"] < 1 else ""
        cand_ids = set(chroma_ids)
        for tag in ("tmdb", "wd"):
            res = base.search(r0["sought"], year, MIN_RATIO[typ])
            if tag == "wd" and res["stage"] == "miss":
                res = lex[(typ, True)].search(r0["sought"], year, MIN_RATIO[typ])
                if res["stage"] != "miss":
                    res["stage"] += "_wd"
            ids = [mm[0] for mm in res["matches"]]
            cand_ids |= set(ids)
            row[f"{tag}_stage"] = res["stage"]
            row[f"{tag}_score"] = round(res["score"], 1)
            row[f"{tag}_id"] = ids[0] if ids else ""
            row[f"{tag}_col"] = res["matches"][0][1] if ids else ""
            row[f"{tag}_n"] = res.get("n_candidates", 0)
            row[f"{tag}_ids10"] = " ".join(map(str, ids))
        g = sorted(cand_ids & gold_ids)
        row["gold"] = " ".join(map(str, g))
        row["gold_note"] = "single" if len(g) == 1 else ("none_in_candidates" if not g else "several")
        for tag in ("chroma", "tmdb", "wd"):
            pick = row[f"{tag}_id"]
            row[f"{tag}_ok"] = "" if not g else int(pick in g)
        row["question"] = r0["question"][:160]
        out_rows.append(row)

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"bench-lexical-360-{args.version}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)

    # summary
    for typ in FAMILY:
        rs = [r for r in out_rows if r["type"] == typ]
        gs = [r for r in rs if r["gold"]]
        print(f"\n== {typ}: {len(rs)} distinct mentions, {len(gs)} with gold")
        for tag in ("chroma", "tmdb", "wd"):
            ok = sum(r[f"{tag}_ok"] == 1 for r in gs)
            print(f"  {tag:6s} P@1 on gold: {ok}/{len(gs)}")
        for tag in ("tmdb", "wd"):
            print(f"  {tag} stages: {dict(collections.Counter(r[tag + '_stage'] for r in rs))}")
        print("  gold notes:", dict(collections.Counter(r["gold_note"] for r in rs)))
    print(f"\nwritten {path} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
