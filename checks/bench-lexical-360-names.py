"""FASTAPI-TEXT2SQL-360, second wave: offline bench of the lexical candidate generator for
Company_name, Network_name and Collection_name against what production returned.

Scope decided by Philippe on 2026-11-05: every entity type but topics leaves ChromaDB. Companies
and networks resolve through ChromaDB today (`companies`, `networks`, documents = the bare name);
collections through the RapidFuzz strategy first (`T_WC_T2S_COLLECTION`, BK-tree and FULLTEXT on
the database) with ChromaDB (`collections`) as fallback.

Inputs
------
- The name pool exported by ``doc/sql/check-360-export-name-pool.sql`` (voie 1), parsed to
  ``names.tsv`` (FAM c/n/k, ID, POP, MOVIES, SERIES, NAME, NAME_FR). Default location:
  ``../shared_data/fastapi-text2sql/bench-360/names.tsv`` (not versioned).
- Mentions, from two sources: the evaluation execution exports of every version
  (``../shared_data/text2sql-eval/evaluation_execution``), which carry the evaluation id and so a
  gold when the bank's ``query_result`` assertion names the entity id; and the API logs
  (``../shared_data/fastapi-text2sql/logs``), which add the questions asked outside the bank.
- The evaluation bank (``../text2sql-eval/data/evaluation``) for the gold ids.

What it measures
----------------
For each distinct (type, folded mention), the production lexicon ``title_lexicon.TitleLexicon``
on the names (no year; ranking: exact before article-only, then credits count, then popularity),
in two variants: ``lex`` on NAME (and NAME_FR for collections), and ``lexd`` which adds a form with
the descriptors stripped (legal forms for companies, franchise words for collections, the list of
``data/entity_resolution.json``). Production's pick is mapped to an id through ``candidate_id``
(ChromaDB documents ``companyid_<id>_<lang>``) or, for the RapidFuzz strategy, through its name.

Usage (from the repository root)::

    uv run checks/bench-lexical-360-names.py [--pool PATH] [--out DIR] [--no-logs]

Writes ``bench-lexical-360-names.csv`` (one row per distinct mention) and a summary on stdout.
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = os.path.dirname(ROOT)
BENCH = os.path.join(CODE, "shared_data", "fastapi-text2sql", "bench-360")
EXPORTS = os.environ.get("TEXT2SQL_EVAL_EXPORT_DIR") or os.path.join(
    CODE, "shared_data", "text2sql-eval", "evaluation_execution")
LOGS = os.path.join(CODE, "shared_data", "fastapi-text2sql", "logs")
BANK = os.path.join(CODE, "text2sql-eval", "data", "evaluation")

sys.path.insert(0, ROOT)
import title_lexicon as tl  # noqa: E402

TYPES = {"Company_name": "c", "Network_name": "n", "Collection_name": "k"}
ID_COL = {"Company_name": "ID_COMPANY", "Network_name": "ID_NETWORK", "Collection_name": "ID_T2S_COLLECTION"}


def thresholds():
    cfg = json.load(open(os.path.join(ROOT, "data", "entity_resolution.json"), encoding="utf-8"))
    out, stop = {}, {}
    for e in cfg:
        typ = e.get("placeholder_prefix")
        if typ in TYPES:
            ss = e.get("search_list") or []
            lx = [s for s in ss if s.get("search_mode") == "lexicon"]
            out[typ] = (lx[0] if lx else ss[0]).get("min_fuzz_ratio", 85)   # the lexicon's own gate
            stop[typ] = sorted({tl.fold(w) for s in ss for w in (s.get("score_stopwords") or [])})
    return out, stop


# Legal forms and trade words a company name often carries or drops ("Warner Bros. Pictures",
# "Pixar Animation Studios", "Gaumont SA"). Stripped only at the end of the name, and never down to
# nothing, so "Pictures" alone stays itself.
COMPANY_TAIL = {"ltd", "limited", "inc", "incorporated", "llc", "corp", "corporation", "co", "company",
                "sa", "sas", "sarl", "gmbh", "ag", "srl", "spa", "bv", "nv", "plc", "pty", "kk",
                "pictures", "picture", "films", "film", "studios", "studio", "productions", "production",
                "entertainment", "animation", "media", "group", "international", "distribution",
                "television", "tv", "filmproduktion", "produzioni", "producciones", "production company"}


def strip_tail(folded: str, words: set) -> str:
    toks = folded.split()
    while len(toks) > 1 and toks[-1] in words:
        toks.pop()
    return " ".join(toks)


def strip_any(folded: str, words: set) -> str:
    toks = [t for t in folded.split() if t not in words]
    return " ".join(toks) if toks else folded


def pool(path, fam, descriptors=None, mode="tail"):
    """Rows for TitleLexicon: (id, year, votes, pop, NAME, NAME_FR[, stripped NAME, stripped FR])."""
    with open(path, encoding="utf-8") as fh:
        fh.readline()
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if f[0] != fam:
                continue
            credits = int(f[3] or 0) + int(f[4] or 0)
            row = [f[1], "", credits, f[2], f[5], f[6]]
            if descriptors is not None:
                cut = strip_tail if mode == "tail" else strip_any
                row += [cut(tl.fold(f[5]), descriptors), cut(tl.fold(f[6]), descriptors) if f[6] else ""]
            yield row


# --------------------------------------------------------------------------- mentions

def bank_ids(eid, id_col):
    out = set()
    for p in glob.glob(os.path.join(BANK, f"{eid}_*.json")):
        try:
            a = (json.load(open(p, encoding="utf-8")).get("assertions") or {}).get("query_result") or ""
        except ValueError:
            continue
        for m in re.finditer(id_col + r"\s*(?:IN\s*\(([^)]*)\)|=\s*(\d+))", a):
            out |= {int(x) for x in re.findall(r"\d+", m.group(1) or m.group(2))}
    return out


def events_of(ao):
    for e in ao.get("entity_match_scores") or []:
        ph = (e.get("placeholder") or "").strip("{}")
        typ = re.sub(r"\d+$", "", ph)
        if typ in TYPES and e.get("sought"):
            yield typ, e


def harvest(use_logs=True):
    rows = []
    for d in sorted(glob.glob(os.path.join(EXPORTS, "0*"))):
        for p in glob.glob(os.path.join(d, "*.json")):
            raw = open(p, encoding="utf-8").read()
            if not any(t in raw for t in TYPES):
                continue
            j = json.loads(raw)
            ao = j.get("api_output") or {}
            passed = (j.get("scoring") or {}).get("assertions_total_score") == 1
            for typ, e in events_of(ao):
                rows.append(dict(src="eval", eid=j["evaluation_id"], passed=passed, type=typ, e=e,
                                 question=ao.get("question") or ""))
    if use_logs:
        for p in glob.glob(os.path.join(LOGS, "*text2sql_post*.json")):
            raw = open(p, encoding="utf-8", errors="replace").read()
            if not any(t in raw for t in TYPES):
                continue
            try:
                j = json.loads(raw)
            except ValueError:
                continue
            ao = j.get("response") or {}
            if not isinstance(ao, dict):
                continue
            for typ, e in events_of(ao):
                rows.append(dict(src="log", eid=None, passed=None, type=typ, e=e,
                                 question=ao.get("question") or ""))
    return rows


def prod_id(e, name_ids):
    cid = e.get("candidate_id") or ""
    m = re.search(r"_(\d+)_", cid)
    if m:
        return int(m.group(1))
    cand = e.get("candidate")
    if cand:
        ids = name_ids.get(tl.fold(cand))
        if ids:
            return ids[0]
    return None


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default=os.path.join(BENCH, "names.tsv"))
    ap.add_argument("--out", default=BENCH)
    ap.add_argument("--no-logs", action="store_true")
    ap.add_argument("--ratio", type=float, default=None, help="fuzzy gate for companies (default: the config's)")
    args = ap.parse_args()
    t0 = time.time()
    ratio, stop = thresholds()

    lex, names, name_ids = {}, {}, {}
    for typ, fam in TYPES.items():
        lex[(typ, "lex")] = tl.TitleLexicon(pool(args.pool, fam), ["NAME", "NAME_FR"])
        desc = set(COMPANY_TAIL) if fam == "c" else (set(stop[typ]) if fam == "k" else None)
        if desc:
            # The production class with its descriptor handling (title_lexicon.TitleLexicon
            # strip_words / lookup), so the bench measures the shipped algorithm.
            lex[(typ, "lexd")] = tl.TitleLexicon(pool(args.pool, fam), ["NAME", "NAME_FR"],
                                                 strip_words=desc, strip_mode="tail" if fam == "c" else "any")
        else:
            lex[(typ, "lexd")] = lex[(typ, "lex")]
        ni = collections.defaultdict(list)
        nm = {}
        for r in pool(args.pool, fam):
            nm[int(r[0])] = r[4]
            for form in (r[4], r[5]):
                if form:
                    ni[tl.fold(form)].append(int(r[0]))
        names[typ], name_ids[typ] = nm, ni
        print(f"lexicon {typ}: {len(lex[(typ, 'lex')])} rows, {len(lex[(typ, 'lex')].keys)} forms, "
              f"stripped variant {len(lex[(typ, 'lexd')].keys)} forms, build {lex[(typ, 'lex')].build_seconds}s"
              f" + {lex[(typ, 'lexd')].build_seconds}s")

    def look(typ, tag, sought):
        if args.ratio and typ == "Company_name":
            ratio[typ] = args.ratio
        return lex[(typ, tag)].lookup(sought, None, ratio[typ])

    events = harvest(not args.no_logs)
    print(f"{len(events)} mention events ({sum(r['src'] == 'eval' for r in events)} from evaluation "
          f"exports) ({time.time() - t0:.0f}s)")

    groups = collections.OrderedDict()
    for r in events:
        groups.setdefault((r["type"], tl.fold(r["e"]["sought"])), []).append(r)

    out_rows, lat = [], []
    for (typ, _), evs in groups.items():
        r0 = evs[0]
        sought = r0["e"]["sought"]
        gold = set()
        for r in evs:
            if r["eid"] is not None:
                gold |= bank_ids(r["eid"], ID_COL[typ])
        # production: the last accepted pick among the events (modes may differ across versions)
        accepted = [r for r in evs if not r["e"].get("rejected")]
        pe = (accepted or evs)[-1]["e"]
        pid = prod_id(pe, name_ids[typ]) if accepted else None
        row = dict(type=typ, sought=sought, n_events=len(evs),
                   n_eval=sum(r["src"] == "eval" for r in evs),
                   eids=" ".join(sorted({str(r["eid"]) for r in evs if r["eid"] is not None})),
                   prod_mode=pe.get("search_mode") or "", prod_name=pe.get("candidate") or "",
                   prod_ratio=pe.get("fuzz_ratio"), prod_rejected=not accepted,
                   prod_id=pid if pid is not None else "")
        for tag in ("lex", "lexd"):
            t1 = time.perf_counter()
            res = look(typ, tag, sought)
            lat.append(time.perf_counter() - t1)
            ids = [m[0] for m in res["matches"]]
            row[f"{tag}_stage"] = res["stage"]
            row[f"{tag}_score"] = round(res["score"], 1)
            row[f"{tag}_id"] = ids[0] if ids else ""
            row[f"{tag}_name"] = names[typ].get(ids[0], "") if ids else ""
            row[f"{tag}_col"] = res["matches"][0][1] if ids else ""
            row[f"{tag}_n"] = res.get("n_candidates", 0)
        row["gold"] = " ".join(map(str, sorted(gold)))
        for tag in ("prod", "lex", "lexd"):
            row[f"{tag}_ok"] = "" if not gold else int(row[f"{tag}_id"] in gold)
        row["agree"] = int(row["prod_id"] == row["lexd_id"])
        row["question"] = r0["question"][:160]
        out_rows.append(row)

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "bench-lexical-360-names.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)

    for typ in TYPES:
        rs = [r for r in out_rows if r["type"] == typ]
        gs = [r for r in rs if r["gold"]]
        print(f"\n== {typ}: {len(rs)} distinct mentions ({sum(r['n_eval'] > 0 for r in rs)} in evaluations), "
              f"{len(gs)} with gold")
        for tag in ("prod", "lex", "lexd"):
            print(f"  {tag:5s} P@1 on gold: {sum(r[tag + '_ok'] == 1 for r in gs)}/{len(gs)}")
        print(f"  production accepted {sum(not r['prod_rejected'] for r in rs)}, rejected {sum(r['prod_rejected'] for r in rs)}")
        for tag in ("lex", "lexd"):
            print(f"  {tag} stages: {dict(collections.Counter(r[tag + '_stage'] for r in rs))}")
        both = [r for r in rs if not r["prod_rejected"] and r["lexd_id"] != ""]
        print(f"  both answer: {len(both)}, same id {sum(r['agree'] for r in both)}, different {sum(not r['agree'] for r in both)}")
        print(f"  production only: {sum(1 for r in rs if not r['prod_rejected'] and r['lexd_id'] == '')}, "
              f"lexicon only: {sum(1 for r in rs if r['prod_rejected'] and r['lexd_id'] != '')}")
    lat.sort()
    print(f"\nlexicon search latency: median {lat[len(lat) // 2] * 1000:.1f} ms, p95 {lat[int(len(lat) * .95)] * 1000:.1f} ms, "
          f"max {lat[-1] * 1000:.1f} ms")
    print(f"written {path} ({time.time() - t0:.0f}s)")
    robustness(args.pool, look, names, args.out)
    return 0


# --------------------------------------------------------------------------- robustness

def _typo(f: str) -> str:
    """Swap two adjacent letters in the middle of the longest word (a typing slip)."""
    toks = f.split()
    i = max(range(len(toks)), key=lambda j: len(toks[j]))
    w = toks[i]
    if len(w) < 5:
        return ""
    k = len(w) // 2
    toks[i] = w[:k - 1] + w[k] + w[k - 1] + w[k + 1:]
    return " ".join(toks)


def variants(name: str, fam: str):
    """(kind, mention) pairs whose right answer is the entity the name belongs to."""
    f = tl.fold(name)
    out = [("lower", name.lower())]
    if fam == "c":
        cut = strip_tail(f, COMPANY_TAIL)
        if cut != f:
            out.append(("no_legal_tail", cut))
        else:
            out.append(("added_tail", f + " pictures"))
    if fam == "k":
        cut = strip_any(f, {"collection", "saga", "trilogy", "series"})
        if cut != f:
            out += [("no_franchise_word", cut), ("trilogie_fr", "trilogie " + cut), ("x_movies", cut + " movies")]
    t = _typo(f)
    if t:
        out.append(("typo", t))
    return out


def robustness(path, look, names, out_dir, top=200):
    """Variants of the most credited names; gold = the source id, or any id sharing its folded
    name (homonyms are the ranking's business, not the generator's)."""
    print("\n== robustness: variants of the most credited names (gold = the source entity)")
    rows = []
    for typ, fam in TYPES.items():
        ents = sorted(pool(path, fam), key=lambda r: -int(r[2]))[:top]
        same = collections.defaultdict(set)
        for i, n in names[typ].items():
            same[tl.fold(n)].add(i)
        stats = collections.defaultdict(lambda: [0, 0, 0])   # kind -> [n, right, wrong]
        for r in ents:
            sid = int(r[0])
            for kind, m in variants(r[4], fam):
                res = look(typ, "lexd", m)
                pick = res["matches"][0][0] if res["matches"] else None
                ok = pick is not None and (pick == sid or pick in same[tl.fold(r[4])])
                st = stats[kind]
                st[0] += 1
                st[1] += ok
                st[2] += (pick is not None and not ok)
                rows.append(dict(type=typ, kind=kind, source=r[4], source_id=sid, credits=r[2], mention=m,
                                 stage=res["stage"], score=round(res["score"], 1), pick=pick or "",
                                 pick_name=names[typ].get(pick, "") if pick else "", ok=int(ok)))
        print(f"  {typ} (top {len(ents)}):")
        for kind, (n, ok, wrong) in stats.items():
            print(f"    {kind:18s} {ok:4d}/{n:<4d} right, {wrong:3d} wrong, {n - ok - wrong:3d} miss")
    p = os.path.join(out_dir, "bench-lexical-360-names-robustness.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"  written {p}")


if __name__ == "__main__":
    sys.exit(main())
