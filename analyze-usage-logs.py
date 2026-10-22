#!/usr/bin/env python3
"""Rebuild, from the usage logs and the evaluation exports, the measurements of the
harness-bricks backlog topic, and write them as two dated HTML reports.

Why this exists. On 2026-10-10 the HARNESS-BRICKS tickets (Nestor,
`projets/t2s-backlog/topics/harness-bricks.md`) were measured once, by throwaway scripts, over
the whole retained log history and the 1.1.19 evaluation runs. A measurement nobody can replay
is a number with a date on it and nothing else. This script is those scripts, kept: run it again
after a deployment or a campaign and it gives the same view on the logs of the day.

It writes two self-contained pages (inline CSS, no JavaScript, no CDN), in the style of the
data-monitoring reports:

  api-usage-YYYYMMDD.html        how the pipeline actually behaves: caches (-003, -004a),
                                 answer_single_value (-010), the answer-entity guard (-008),
                                 the retry cache guards (-011), SQL execution feedback and
                                 what escalation produces (-009), failures by cause (-001),
                                 and the cost price of a call (-337): list-price dollars per
                                 search, server and CPU time per endpoint, entity routes included.
  vision-evidence-YYYYMMDD.html  what the vision model (gpt-6-astra by default) read in each
                                 image, and what of it reaches `vision_evidence`
                                 (FASTAPI-TEXT2SQL-114 and followers).

Two sources, read-only, never the database:

  logs   `*_text2sql_post_*.json` written by logs.py, loose and in the monthly tarballs that
         archive-logs.sh produces under `logs/archive/<YYYYMM>.tar.gz`; for the cost section,
         every other endpoint's log too (`*_movies_*.json` and so on). The month being
         archived can sit in both places: files are deduplicated by name.
  evals  the per-row JSON exports under `text2sql-eval/evaluation_execution/<run>/`, one folder
         per (version, language, models) run. Optional: without it, the evaluation sections
         say so and the rest of the page is still written.

Read the figures with three facts in mind.
- The evaluator always sends `retrieve_from_cache: false`; voice-agent, tmdb-front and the MCP
  send `true`. That flag is how this report tells a campaign from production traffic, and the
  only way: a test typed by hand in the front counts as production.
- A retried request writes two log files (FASTAPI-TEXT2SQL-241). The inner one carries
  `complex_question_already_resolved: true` and is never counted as a question here.
- A field only exists from the version that shipped it. Where that matters the page prints how
  many records carry the field at all; a zero on a field nobody writes means nothing.

Usage (from the repository root, on the PC or in the VPS clone, same relative layout):
  uv run analyze-usage-logs.py
  uv run analyze-usage-logs.py --logs ../shared_data/fastapi-text2sql/logs \\
      --evals ../shared_data/text2sql-eval/evaluation_execution --out ../shared_data/fastapi-text2sql/reports
  uv run analyze-usage-logs.py --eval-version 001.001.019 --since 20260101
"""
import argparse
import datetime as dt
import glob
import html
import json
import os
import re
import statistics
import sys
import tarfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGS = os.path.normpath(os.path.join(HERE, "..", "shared_data", "fastapi-text2sql", "logs"))
DEFAULT_EVALS = os.path.normpath(os.path.join(HERE, "..", "shared_data", "text2sql-eval", "evaluation_execution"))

FILENAME_RE = re.compile(r"(\d{8}-\d{6})_([a-z0-9]+)_([a-z]+)_([\d.]+)_")
# Any endpoint's log name: 20261021-101500_movies_1.1.19_<md5>.json (FASTAPI-TEXT2SQL-337).
ANY_FILENAME_RE = re.compile(r"(\d{8}-\d{6})_(.+?)_(\d+\.\d+\.\d+)_[0-9a-f]{32}\.json$")

# Message prefixes written by main.py. Matched on the start of the text, as main.py writes them.
GUARD_DISAGREE = "Answer-entity expectation"
GUARD_REGEN = "Answer-entity guard: query did not return the expected entity"
GUARD_FIXED = "Answer-entity guard: regenerated query now returns"
GUARD_KEPT = "Answer-entity guard: regeneration still did not"
GUARD_SKIP = ("Answer-entity guard: single total", "Answer-entity guard: statistics table")
ASV_MARK = "SQL query returned a single-cell result with value 0"
COMPLEX_OUTPUT = "Complex question resolution output: "
VISION_FAILED = "Vision: identification failed"

# A bare single-entity template: what most anonymized-cache hits are (-004a).
BARE_TEMPLATE = re.compile(
    r"^(movie|film|serie|tv serie|series|person)?\s*\{\{[A-Za-z_]+1\}\}"
    r"(\s*\(\{\{Release_year1\}\}\)|\s*released in \{\{Release_year1\}\})?$", re.I)
IMDB_ID = re.compile(r"^(tt|nm)\d+$")

# Mirrors text2sql.VISION_MAX_CANDIDATES and _VISION_ITEM_TYPES. Copied, not imported: importing
# text2sql starts the data watcher and reads the environment, which a log reader must not do.
VISION_MAX_CANDIDATES = 5
VISION_ITEM_TYPES = ("movie", "serie", "person", "collection", "topic",
                     "company", "network", "location", "other")


# ---------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------

def _messages(resp):
    msgs = resp.get("messages") or []
    if not isinstance(msgs, list):
        return []
    return [str(m.get("text") if isinstance(m, dict) else m) for m in msgs]


def log_record(name, raw):
    """One compact record per log file: only what the measurements below read."""
    try:
        d = json.loads(raw)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    m = FILENAME_RE.search(name)
    req = d.get("request") if isinstance(d.get("request"), dict) else {}
    resp = d.get("response") if isinstance(d.get("response"), dict) else {}
    if not resp and "question" in d:
        resp = d
    res = resp.get("result")
    texts = _messages(resp)
    keep = [t[:400] for t in texts if t.startswith((GUARD_DISAGREE, "Answer-entity guard", ASV_MARK, "Vision"))]
    rec = {
        "file": name,
        "ts": m.group(1) if m else "",
        "endpoint": m.group(2) if m else "",
        "ver_file": m.group(4) if m else "",
        "retrieve": req.get("retrieve_from_cache"),
        "store": req.get("store_to_cache"),
        "already": bool(req.get("complex_question_already_resolved")),
        "hashed": bool(req.get("question_hashed")),
        "page": req.get("page") or 1,
        "lang": req.get("ui_language"),
        "req_question": req.get("question"),
        "image_ref": req.get("image_ref") or resp.get("image_ref"),
        "question": resp.get("question"),
        "api_version": resp.get("api_version") or (m.group(4) if m else ""),
        "c_exact": resp.get("cached_exact_question"),
        "c_anon": resp.get("cached_anonymized_question"),
        "c_anon_emb": resp.get("cached_anonymized_question_embedding"),
        "q_anon": resp.get("question_anonymized"),
        "complex": bool(resp.get("complex_model_used")),
        "asv_t": resp.get("answer_single_value_processing_time"),
        "regen": resp.get("sql_regeneration_outcome"),
        "retry_pol": resp.get("complex_retry_cache_policy"),
        "error": resp.get("error"),
        "error_code": resp.get("error_code"),
        "t_total": resp.get("total_processing_time"),
        # FASTAPI-TEXT2SQL-337. Top-level since the request clock; the cost since the API
        # prices its calls. "has_cost" separates "not measured" (older API) from a free hit.
        "server_time": d.get("server_time"),
        "cpu_time": d.get("cpu_time"),
        # FASTAPI-TEXT2SQL-338: the waits on MariaDB and ChromaDB, and the server's share in euros.
        "sql_calls": d.get("sql_calls"),
        "sql_time": d.get("sql_time"),
        "chroma_time": d.get("chroma_time"),
        "server_cost_eur": d.get("server_cost_eur"),
        "has_cost": "llm_cost" in resp,
        "cost_usd": ((resp.get("llm_cost") or {}).get("total_usd") or 0.0) if "llm_cost" in resp else None,
        "emb_tokens": (resp.get("embedding_usage") or {}).get("prompt_tokens"),
        "t2s_model": resp.get("llm_model_text2sql"),
        "nrows": len(res) if isinstance(res, list) else None,
        "answer": str(resp.get("answer") or "")[:300],
        "msgs": keep,
    }
    if rec["image_ref"]:
        rec["vision_evidence"] = resp.get("vision_evidence")
        rec["vision_model"] = resp.get("llm_model_vision") if isinstance(resp.get("llm_model_vision"), str) else None
        rec["vision_t"] = resp.get("vision_identification_processing_time")
    return rec


def timing_record(name, raw):
    """Endpoint, server time and CPU time of a non-search log (FASTAPI-TEXT2SQL-337)."""
    m = ANY_FILENAME_RE.search(name)
    if not m:
        return None
    try:
        d = json.loads(raw)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    return {"ts": m.group(1), "endpoint": m.group(2),
            "server_time": d.get("server_time"), "cpu_time": d.get("cpu_time"),
            "sql_calls": d.get("sql_calls"), "sql_time": d.get("sql_time"),
            "chroma_time": d.get("chroma_time"), "server_cost_eur": d.get("server_cost_eur")}


def scan_logs(logs_dir, since="", others=None):
    """Text-to-SQL records; with `others` (a list), every other endpoint's timing too."""
    seen, out = set(), []

    def take(name, raw):
        base = os.path.basename(name)
        if base in seen:
            return
        if since and base[:8] < since:
            return
        if "_text2sql_post_" not in base:
            if others is not None and base.endswith(".json"):
                seen.add(base)
                rec = timing_record(base, raw)
                if rec:
                    others.append(rec)
            return
        seen.add(base)
        rec = log_record(base, raw)
        if rec:
            out.append(rec)

    pattern = "*.json" if others is not None else "*_text2sql_post_*.json"
    for path in sorted(glob.glob(os.path.join(logs_dir, pattern))):
        with open(path, "rb") as fh:
            take(path, fh.read().decode("utf-8", "replace"))
    for archive in sorted(glob.glob(os.path.join(logs_dir, "archive", "*.tar.gz"))):
        month = os.path.basename(archive)[:6]
        if since and month < since[:6]:
            continue
        try:
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    if member.isfile() and member.name.endswith(".json"):
                        fh = tar.extractfile(member)
                        if fh is not None:
                            take(member.name, fh.read().decode("utf-8", "replace"))
        except Exception as e:
            print(f"  (skipped {archive}: {e})", file=sys.stderr)
        print(f"  read {os.path.basename(archive)}, {len(out)} records so far", file=sys.stderr)
    out.sort(key=lambda r: r["ts"])
    return out


def load_eval_rows(evals_dir, version):
    """Rows of every run of one API version, the latest execution kept per (run, evaluation)."""
    runs = {}
    for folder in sorted(glob.glob(os.path.join(evals_dir, version + "_*"))):
        run = os.path.basename(folder)[len(version) + 1:]
        best = {}
        for path in glob.glob(os.path.join(folder, "*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    j = json.load(fh)
            except Exception:
                continue
            key = j.get("evaluation_id")
            if key not in best or str(j.get("tim_execution")) > str(best[key].get("tim_execution")):
                best[key] = j
        runs[run] = list(best.values())
    return runs


def latest_eval_version(evals_dir):
    versions = sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(evals_dir, "*_*"))})
    return versions[-1] if versions else None


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------

def pct(a, b):
    return f"{100 * a / b:.1f} %" if b else "n/a"


def med(values):
    v = [x for x in values if isinstance(x, (int, float))]
    return round(statistics.median(v), 2) if v else None


def p90(values):
    v = sorted(x for x in values if isinstance(x, (int, float)))
    return round(v[int(0.9 * (len(v) - 1))], 2) if v else None


def score_of(row):
    return (row.get("scoring") or {}).get("assertions_total_score")


def is_pass(row):
    return score_of(row) == 1


def full_and_partial(runs):
    """A run under half the size of the largest one of its version is partial: shown, not pooled."""
    biggest = max((len(v) for v in runs.values()), default=0)
    full = {k: v for k, v in runs.items() if len(v) >= biggest / 2}
    partial = {k: v for k, v in runs.items() if k not in full}
    return full, partial


def esc(x):
    return html.escape("" if x is None else str(x))


# ---------------------------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------------------------

CSS = """
  :root { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
  body { margin: 0; background: #f5f7f9; color: #263238; }
  header { background: #263238; color: #fff; padding: 20px 28px; }
  header h1 { margin: 0 0 4px; font-size: 20px; }
  header .meta { font-size: 12px; color: #b0bec5; }
  header a { color: #90caf9; }
  .intro { padding: 16px 28px 0; font-size: 14px; color: #455a64; max-width: 90ch; line-height: 1.5; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; padding: 16px 28px; }
  .card { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; }
  .card h3 { margin: 0; font-size: 14px; }
  .card .key { font-size: 11px; color: #90a4ae; font-family: ui-monospace, monospace; }
  .big { font-size: 28px; font-weight: 700; margin: 8px 0 4px; }
  .sub { font-size: 12px; color: #607d8b; line-height: 1.4; }
  section.block { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; margin: 16px 28px; padding: 16px 20px; overflow-x: auto; }
  section.block h2 { margin: 0 0 4px; font-size: 16px; }
  section.block .ticket { font-size: 11px; color: #90a4ae; font-family: ui-monospace, monospace; }
  section.block p { font-size: 13px; color: #455a64; line-height: 1.5; max-width: 100ch; }
  table { border-collapse: collapse; font-size: 12px; margin: 8px 0 12px; }
  th, td { border-bottom: 1px solid #eceff1; padding: 4px 8px; text-align: left; vertical-align: top; }
  th { background: #eceff1; font-weight: 600; }
  td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .bar { display: inline-block; height: 8px; background: #1976d2; border-radius: 2px; vertical-align: middle; }
  .warn { color: #d9534f; font-weight: 600; }
  .ok { color: #388e3c; font-weight: 600; }
  .muted { color: #90a4ae; }
  code { font-family: ui-monospace, monospace; font-size: 11px; }
  img.thumb { max-width: 90px; max-height: 120px; border-radius: 3px; }
  footer { padding: 16px 28px; font-size: 11px; color: #90a4ae; }
"""


def table(headers, rows, numeric=()):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            raw = isinstance(c, Raw)
            text = c.s if raw else esc(c)
            cls = ' class="n"' if i in numeric else ""
            cells.append(f"<td{cls}>{text}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


class Raw:
    """A cell already rendered as HTML."""
    def __init__(self, s):
        self.s = s


def bar(value, maximum, width=160):
    w = int(width * value / maximum) if maximum else 0
    return Raw(f'<span class="bar" style="width:{w}px"></span>')


def card(title, key, big, sub=""):
    return (f'<div class="card"><h3>{esc(title)}</h3><span class="key">{esc(key)}</span>'
            f'<div class="big">{esc(big)}</div><div class="sub">{sub}</div></div>')


def block(title, ticket, body):
    return (f'<section class="block"><h2>{esc(title)}</h2><span class="ticket">{esc(ticket)}</span>'
            f'{body}</section>')


def page(title, slug, generated, sources, intro, cards, blocks, links):
    nav = " · ".join(f'<a href="{esc(h)}">{esc(t)}</a>' for t, h in links)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - {esc(generated[:10])}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>{esc(title)}</h1>
  <div class="meta">Generated {esc(generated)} · {esc(sources)} · report slug <code>{esc(slug)}</code></div>
  <div class="meta">{nav}</div>
</header>
<div class="intro">{intro}</div>
<div class="grid">{''.join(cards)}</div>
{''.join(blocks)}
<footer>fastapi-text2sql · analyze-usage-logs.py · read-only over the usage logs and the evaluation
exports, no database access. Production means <code>retrieve_from_cache: true</code>, which includes the
tests typed by hand in a front; campaign means the evaluator.</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------------------------
# api-usage: measurements over the logs
# ---------------------------------------------------------------------------------------------

def outer(records):
    """Questions, not files: the inner file of a retried request is skipped (Gotcha #8d)."""
    return [r for r in records if r["endpoint"] == "text2sql" and not r["already"]]


def traffic_block(T):
    by_month = defaultdict(Counter)
    for r in T:
        k = "production" if r["retrieve"] is True else "campaign" if r["retrieve"] is False else "unknown"
        by_month[r["ts"][:6]][k] += 1
    mx = max((sum(c.values()) for c in by_month.values()), default=0)
    rows = [(m, c["production"], c["campaign"], c["unknown"], bar(sum(c.values()), mx))
            for m, c in sorted(by_month.items())]
    by_ver = Counter(r["api_version"] for r in T)
    rows_v = [(v, n) for v, n in sorted(by_ver.items(), key=lambda x: str(x[0]))]
    body = ("<p>Every outer text-to-SQL request in the logs, by month and by kind of caller. "
            "<em>unknown</em> is a log written before the request was logged.</p>"
            + table(["month", "production", "campaign", "unknown", ""], rows, numeric=(1, 2, 3))
            + table(["API version", "requests"], rows_v, numeric=(1,)))
    return block("Traffic", "context", body)


def _usd(x):
    return f"${x:.4f}" if isinstance(x, (int, float)) else "n/a"


def _p90(values):
    v = sorted(values)
    return v[int(0.9 * (len(v) - 1))] if v else None


def cost_block(T, others):
    """Cost price of a call (FASTAPI-TEXT2SQL-337): provider dollars and server time."""
    cards = []
    priced = [r for r in T if r.get("has_cost")]
    rows = []
    for label, rr in (("production", [r for r in priced if r["retrieve"] is True]),
                      ("campaign", [r for r in priced if r["retrieve"] is False])):
        if not rr:
            continue
        costs = [r["cost_usd"] for r in rr]
        free = sum(1 for c in costs if not c)
        paid = [c for c in costs if c]
        mean = sum(costs) / len(costs)
        rows.append((label, len(rr), pct(free, len(rr)), _usd(mean),
                     _usd(statistics.median(paid) if paid else None), _usd(_p90(paid)), f"${1000 * mean:.2f}"))
        if label == "production":
            cards.append(card("Search cost, production", "llm_cost.total_usd", _usd(mean),
                              f"mean over {len(rr)} searches, cache hits at $0 included"))
    by_model = defaultdict(list)
    for r in priced:
        if r["cost_usd"]:
            kind = "production" if r["retrieve"] is True else "campaign"
            by_model[(r["t2s_model"] or "?", kind)].append(r["cost_usd"])
    rows_m = [(m, k, len(v), _usd(sum(v) / len(v)), _usd(statistics.median(v)))
              for (m, k), v in sorted(by_model.items())]
    emb = [r["emb_tokens"] for r in priced if r.get("emb_tokens")]
    timed = [r for r in T + others if isinstance(r.get("server_time"), (int, float))]
    by_ep = defaultdict(list)
    for r in timed:
        by_ep[r["endpoint"]].append(r)
    def _p50(rr, key, fmt="{:.3f}"):
        v = [r[key] for r in rr if isinstance(r.get(key), (int, float))]
        return fmt.format(statistics.median(v)) if v else "n/a"

    rows_t = []
    for ep, rr in sorted(by_ep.items(), key=lambda x: -len(x[1])):
        st = [r["server_time"] for r in rr]
        ct = [r["cpu_time"] for r in rr if isinstance(r.get("cpu_time"), (int, float))]
        eur = [r["server_cost_eur"] for r in rr if isinstance(r.get("server_cost_eur"), (int, float))]
        rows_t.append((ep, len(rr), f"{statistics.median(st):.3f}", f"{_p90(st):.3f}",
                       f"{statistics.median(ct):.3f}" if ct else "n/a", f"{sum(ct):.1f}" if ct else "n/a",
                       _p50(rr, "sql_calls", "{:.0f}"), _p50(rr, "sql_time"), _p50(rr, "chroma_time"),
                       f"{1000 * sum(eur) / len(eur):.4f} €" if eur else "n/a"))
    entity = [r for r in others if isinstance(r.get("server_time"), (int, float))]
    if entity:
        cards.append(card("Other calls, server time", "server_time",
                          f"{statistics.median([r['server_time'] for r in entity]):.3f} s",
                          f"median over {len(entity)} calls of every non-search endpoint"))
    body = (f"<p>{len(priced)} of {len(T)} logged questions carry <code>llm_cost</code>, the list-price estimate "
            "the API computes from its price table <code>llm_costs.py</code> (provider fees only: LLM tasks and "
            "embeddings). A cache hit calls nothing and counts at $0; the mean includes them, the median and p90 are "
            "over the paid searches. Older logs have no <code>llm_cost</code> and are left out, not counted at zero.</p>"
            + table(["traffic", "searches", "free (cache)", "mean", "median paid", "p90 paid", "per 1,000"], rows,
                    numeric=(1, 3, 4, 5, 6))
            + "<p>Paid searches by text-to-SQL model:</p>"
            + table(["text2sql model", "traffic", "searches", "mean", "median"], rows_m, numeric=(2, 3, 4))
            + (f"<p>Embeddings: median {statistics.median(emb):.0f} tokens per search over {len(emb)} searches.</p>"
               if emb else "")
            + "<p>Server time is the wall time inside the API (NGINX and network excluded), CPU time the process CPU "
            "meanwhile, all threads, so it also counts any request served at the same moment. Both are stamped in "
            "every log written during a request; logs older than the request clock have neither and are left out. "
            "CPU total is the API's CPU seconds over the period. Since FASTAPI-TEXT2SQL-338 the logs also carry "
            "the API's waits on MariaDB (SQL) and ChromaDB, which run in other containers and whose own CPU the API "
            "cannot read, and <code>server_cost_eur</code>: CPU plus both waits at the VPS rate of "
            "<code>llm_costs.py</code> (93.50 € excl. VAT a month, 8 vCores), an upper bound of the server's share. "
            "The VPS is a fixed, committed cost: these euros allocate it, a call does not add them to the bill.</p>"
            + table(["endpoint", "calls", "server p50 (s)", "server p90 (s)", "CPU p50 (s)", "CPU total (s)",
                     "SQL p50", "SQL p50 (s)", "Chroma p50 (s)", "server € / 1,000"], rows_t,
                    numeric=(1, 2, 3, 4, 5, 6, 7, 8, 9)))
    return cards, block("Cost price of a call", "FASTAPI-TEXT2SQL-337", body)


def cache_block(T):
    P = [r for r in T if r["retrieve"] is True and r["c_exact"] is not None]
    p1 = [r for r in P if r["page"] == 1 and not r["hashed"]]
    later = [r for r in P if r not in p1]

    def rates(rows):
        n = len(rows)
        e = sum(bool(r["c_exact"]) for r in rows)
        a = sum(bool(r["c_anon"]) and not r["c_exact"] for r in rows)
        m = sum(bool(r["c_anon_emb"]) and not r["c_exact"] for r in rows)
        anyh = sum(bool(r["c_exact"] or r["c_anon"] or r["c_anon_emb"]) for r in rows)
        return n, e, a, m, anyh

    def row(label, rows):
        n, e, a, m, anyh = rates(rows)
        return (label, n, f"{e} ({pct(e, n)})", f"{a} ({pct(a, n)})", f"{m} ({pct(m, n)})", f"{anyh} ({pct(anyh, n)})")

    hdr = ["slice", "requests", "exact hits", "anonymized, text", "anonymized, embedding", "any hit"]
    main_rows = [row("page 1, question in clear", p1), row("page 2+ or hashed question", later)]
    months = [row(m, [r for r in p1 if r["ts"][:6] == m]) for m in sorted({r["ts"][:6] for r in p1})]
    versions = [row(str(v), [r for r in p1 if r["api_version"] == v]) for v in sorted({r["api_version"] for r in p1}, key=str)]

    lat = []
    for lab, f in [("exact hit", lambda r: r["c_exact"]),
                   ("anonymized hit, text", lambda r: r["c_anon"] and not r["c_exact"]),
                   ("anonymized hit, embedding", lambda r: r["c_anon_emb"] and not r["c_exact"]),
                   ("miss", lambda r: not (r["c_exact"] or r["c_anon"] or r["c_anon_emb"]))]:
        rr = [r for r in p1 if f(r)]
        lat.append((lab, len(rr), med([r["t_total"] for r in rr]), p90([r["t_total"] for r in rr])))

    A = [r for r in p1 if (r["c_anon"] or r["c_anon_emb"]) and not r["c_exact"] and r.get("q_anon")]
    bare = sum(bool(BARE_TEMPLATE.match(r["q_anon"].strip())) for r in A)
    templates = Counter((r["q_anon"], "embedding" if r["c_anon_emb"] else "text") for r in A).most_common(20)
    last_emb = max((r["ts"] for r in p1 if r["c_anon_emb"] and not r["c_exact"]), default="never")
    exact_top = Counter(r["question"] for r in p1 if r["c_exact"]).most_common(15)

    n, e, a, m, anyh = rates(p1)
    cards = [
        card("Exact cache, page 1", "HARNESS-BRICKS-003", pct(e, n), f"{e} of {n} production page-1 requests"),
        card("Anonymized cache, text", "HARNESS-BRICKS-004a", pct(a, n), f"{a} hits; {pct(a, n - e)} of the exact misses"),
        card("Anonymized cache, embedding", "HARNESS-BRICKS-004a", pct(m, n), f"last hit {last_emb[:8] if last_emb != 'never' else 'never'}"),
        card("Bare single-entity templates", "HARNESS-BRICKS-004a", pct(bare, len(A)), f"{bare} of {len(A)} anonymized hits with a known template"),
    ]
    span = f"{p1[0]['ts'][:8]} to {p1[-1]['ts'][:8]}" if p1 else "no data"
    body = (f"<p>Production requests that asked for the cache (<code>retrieve_from_cache: true</code>), {span}. "
            "Hits are exclusive from left to right: an anonymized hit is counted only when the exact cache missed. "
            "Page 2 and hashed questions are paging through a result already computed, so they hit almost always and are kept apart. "
            "Caveat: the logs cannot tell your own tests from other users, and the most frequent exact hits usually are tests.</p>"
            + table(hdr, main_rows, numeric=(1,))
            + "<p>Latency, in seconds, page 1. An anonymized hit still pays extraction and resolution; it saves the text-to-SQL call.</p>"
            + table(["outcome", "requests", "median", "p90"], lat, numeric=(1, 2, 3))
            + "<p>By month and by API version (page 1). The cache is keyed on the version, so it starts empty after each bump.</p>"
            + table(hdr, months, numeric=(1,)) + table(hdr, versions, numeric=(1,))
            + f"<p>Most frequent anonymized templates served ({len({r['q_anon'] for r in A})} distinct).</p>"
            + table(["hits", "template", "match"], [(c, t, k) for (t, k), c in templates], numeric=(0,))
            + "<p>Most frequent exact hits.</p>"
            + table(["hits", "question"], [(c, q) for q, c in exact_top], numeric=(0,)))
    return cards, block("SQL caches: exact and anonymized", "HARNESS-BRICKS-003, -004a", body)


def asv_block(T):
    hits = [r for r in T if (isinstance(r["asv_t"], (int, float)) and r["asv_t"] > 0)
            or any(t.startswith(ASV_MARK) for t in r["msgs"])]
    kind = lambda r: "production" if r["retrieve"] is True else "campaign" if r["retrieve"] is False else "unknown"
    by_ver = Counter((r["api_version"], kind(r)) for r in hits)
    prod = [r for r in hits if kind(r) != "campaign"]
    rows = [(r["ts"][:8], r["api_version"], kind(r), r["question"], r["answer"][:160]) for r in prod]
    cards = [card("answer_single_value outside campaigns", "HARNESS-BRICKS-010", str(len(prod)),
                  f"{len({(r['question'] or '').lower() for r in prod})} distinct questions; {len(hits)} triggers in all")]
    body = ("<p>The direct-answer path fires when the SQL returns a single cell equal to 0 and asks the stronger model "
            "to answer from memory. Counted from <code>answer_single_value_processing_time</code> and its message.</p>"
            + table(["API version", "caller", "triggers"], [(v, k, n) for (v, k), n in sorted(by_ver.items(), key=lambda x: str(x[0]))], numeric=(2,))
            + "<p>Every trigger outside campaigns.</p>"
            + table(["date", "version", "caller", "question", "answer"], rows))
    return cards, block("answer_single_value: the answer from memory", "HARNESS-BRICKS-010", body)


def guard_logs(T):
    prod = [r for r in T if r["retrieve"] is not False]
    c = Counter()
    by_ver = defaultdict(Counter)
    for r in prod:
        reg = any(t.startswith(GUARD_REGEN) for t in r["msgs"])
        fix = any(t.startswith(GUARD_FIXED) for t in r["msgs"])
        if reg:
            c["regen"] += 1
            by_ver[r["api_version"]]["regen"] += 1
        if fix:
            c["fixed"] += 1
            by_ver[r["api_version"]]["fixed"] += 1
    return c, by_ver


def regen_block(T):
    c = Counter(r["regen"] for r in T if r["regen"])
    carriers = sum(1 for r in T if r["regen"] is not None)
    body = ("<p>Execution feedback for a failed SQL query (FASTAPI-TEXT2SQL-262): the error goes back to the same generator for one more try. "
            f"{carriers} logged responses carry the field <code>sql_regeneration_outcome</code>; the table counts those where it is not empty. "
            "There is no such loop for an empty result: that is the gap Test 2 of -009 would fill.</p>"
            + table(["outcome", "requests"], c.most_common(), numeric=(1,)))
    return block("SQL execution feedback", "HARNESS-BRICKS-009 (fact)", body)


def retry_policy_logs(T):
    return Counter((r["retry_pol"] or "").split(" (")[0] for r in T if r["retry_pol"])


# ---------------------------------------------------------------------------------------------
# api-usage: measurements over the evaluation exports
# ---------------------------------------------------------------------------------------------

def complex_output(o):
    res = None
    for t in _messages(o):
        if t.startswith(COMPLEX_OUTPUT):
            raw = t[len(COMPLEX_OUTPUT):].replace('\\"', '"')
            try:
                res = json.loads(raw)
            except Exception:
                res = "unparsable"
    return res


def classify_escalation(o):
    res = complex_output(o)
    if res is None:
        return "no output logged"
    if not isinstance(res, dict):
        return "unparsable"
    if res.get("authoritative_empty"):
        return "authoritative_empty"
    if res.get("error") and not (res.get("question") or res.get("items")):
        return "error"
    items = [i for i in (res.get("items") or []) if isinstance(i, dict) and str(i.get("value") or "").strip()]
    if len(items) >= 2:
        return "item list recalled from memory"
    if str(res.get("question") or "").strip() or items:
        return "single key, question rewritten"
    return "empty"


def failure_tag(o):
    fp = o.get("first_pass_failure_code") or ""
    if (o.get("error") or "").strip() or o.get("error_code") or "error" in fp:
        return "error (SQL or pipeline)"
    if o.get("complex_retry_intent_dropped"):
        return "intent dropped in the rewrite"
    if (o.get("entity_raw_fallback_count") or 0) > 0 or any(k in fp for k in ("raw_fallback", "unmatchable", "unresolved_placeholder", "unbacked")):
        return "resolution"
    res = o.get("result")
    if isinstance(res, list) and len(res) == 0:
        return "empty result, names resolved"
    return "wrong or incomplete rows"


def eval_blocks(runs, version, guard_prod, guard_prod_ver, pol_logs):
    if not runs:
        return [], [block("Evaluation runs", "HARNESS-BRICKS-001, -008, -009, -011",
                          f"<p class='warn'>No evaluation export found for {esc(version)}: these sections are empty.</p>")]
    full, partial = full_and_partial(runs)
    blocks, cards = [], []

    # -- runs overview
    rows = []
    for run, rr in sorted(runs.items()):
        s = [r for r in rr if score_of(r) is not None]
        p = sum(map(is_pass, s))
        rows.append((run, len(rr), pct(p, len(s)), "partial, not pooled" if run in partial else ""))
    blocks.append(block(f"Evaluation runs of {version}", "context",
                        "<p>One folder per (language, models) run. Executions are deduplicated by evaluation, the latest kept, "
                        "so a rerun does not count twice. A run under half the size of the largest is partial: listed, never pooled.</p>"
                        + table(["run", "rows", "pass", ""], rows, numeric=(1, 2))))

    # -- -009 escalation outputs
    allesc = []
    rows = []
    for run, rr in sorted(full.items()):
        e = [r for r in rr if r["api_output"].get("complex_model_used")]
        cls = Counter(classify_escalation(r["api_output"]) for r in e)
        rows.append((run, len(rr), len(e), "; ".join(f"{k} {v}" for k, v in cls.most_common())))
        allesc += e
    pooled = []
    for k, n in Counter(classify_escalation(r["api_output"]) for r in allesc).most_common():
        rr = [r for r in allesc if classify_escalation(r["api_output"]) == k]
        s = [r for r in rr if score_of(r) is not None]
        pooled.append((k, n, pct(sum(map(is_pass, s)), len(s)),
                       med([(r.get("timings") or {}).get("total_processing_time") or r["api_output"].get("total_processing_time") for r in rr])))
    blocks.append(block("What escalation produces", "HARNESS-BRICKS-009, Test 1",
                        "<p>Every escalated row, sorted by what the stronger model returned (read from the "
                        "<em>Complex question resolution output</em> message). Escalation never writes the answer itself: it returns a "
                        "rewritten question, a list of items recalled from memory, an authoritative empty, or an error.</p>"
                        + table(["run", "rows", "escalated", "outputs"], rows, numeric=(1, 2))
                        + "<p>Pooled over the full runs.</p>"
                        + table(["output", "rows", "pass", "median s"], pooled, numeric=(1, 2, 3))))
    cards.append(card("Escalated rows", "HARNESS-BRICKS-009", str(len(allesc)),
                      f"over {sum(len(v) for v in full.values())} rows of {len(full)} full runs"))

    # -- -008 answer-entity guard
    rows = []
    tot = Counter()
    for run, rr in sorted(runs.items()):
        c = Counter()
        for r in rr:
            mt = _messages(r["api_output"])
            fix = any(t.startswith(GUARD_FIXED) for t in mt)
            kept = any(t.startswith(GUARD_KEPT) for t in mt)
            c["rows"] += 1
            c["disagree"] += any(t.startswith(GUARD_DISAGREE) for t in mt)
            c["regen"] += any(t.startswith(GUARD_REGEN) for t in mt)
            c["fixed"] += fix
            c["kept"] += kept
            c["skipped"] += any(t.startswith(GUARD_SKIP) for t in mt)
            c["fixed_pass"] += fix and is_pass(r)
        rows.append((run, c["rows"], c["disagree"], c["skipped"], c["regen"], c["fixed"], c["fixed_pass"], c["kept"],
                     pct(c["regen"], c["rows"])))
        tot += c
    rows.append(("all runs", tot["rows"], tot["disagree"], tot["skipped"], tot["regen"], tot["fixed"], tot["fixed_pass"], tot["kept"], pct(tot["regen"], tot["rows"])))
    ver_rows = [(v, c["regen"], c["fixed"]) for v, c in sorted(guard_prod_ver.items(), key=lambda x: str(x[0]))]
    blocks.append(block("Answer-entity guard", "HARNESS-BRICKS-008 (2)",
                        "<p>The guard compares the entity the answer should be about with what the query returns, and regenerates once on a "
                        "disagreement. <em>fixed, pass</em> is the upper bound of what the guard is worth on a run: those rows would maybe "
                        "have passed anyway.</p>"
                        + table(["run", "rows", "disagreements", "skipped (aggregates)", "regenerated", "fixed", "fixed, pass", "kept original", "regen rate"],
                                rows, numeric=(1, 2, 3, 4, 5, 6, 7, 8))
                        + f"<p>Outside campaigns (logs): {guard_prod['regen']} regenerations, {guard_prod['fixed']} fixed.</p>"
                        + table(["API version", "regenerated", "fixed"], ver_rows, numeric=(1, 2))))
    cards.append(card("Guard regenerations, campaigns", "HARNESS-BRICKS-008", pct(tot["regen"], tot["rows"]),
                      f"{tot['regen']} of {tot['rows']} rows; {tot['fixed_pass']} fixed rows pass"))

    # -- -011 retry cache policy
    pol = Counter()
    for run, rr in full.items():
        for r in rr:
            p = r["api_output"].get("complex_retry_cache_policy") or ""
            if p:
                pol[p.split(" (")[0]] += 1
    # `not_requested` is the client declining the write, not a guard deciding against it.
    n = sum(v for k, v in pol.items() if k != "skipped:not_requested")
    stored = sum(v for k, v in pol.items() if k.startswith("stored"))
    blocks.append(block("Cache guards on retries", "HARNESS-BRICKS-011",
                        "<p>What happened to the cache write of every retried request, as written in "
                        "<code>complex_retry_cache_policy</code>. Anything but <em>stored</em> is a rewrite the guards kept out of the cache "
                        "(a year the user never typed, a dropped intent, an empty result).</p>"
                        + "<p>Evaluation, full runs.</p>"
                        + table(["policy", "retries", "share of retries asked to store"],
                                [(k, v, pct(v, n) if k != "skipped:not_requested" else "") for k, v in pol.most_common()], numeric=(1, 2))
                        + "<p>Logs, every caller.</p>"
                        + table(["policy", "retries"], pol_logs.most_common(), numeric=(1,))))
    cards.append(card("Retries kept out of the cache", "HARNESS-BRICKS-011", pct(n - stored, n), f"{n - stored} of {n} retries asked to store, campaigns"))

    # -- -001 failures by cause
    rows = []
    for run, rr in sorted(full.items()):
        fails = [r for r in rr if score_of(r) is not None and not is_pass(r)]
        c = Counter(failure_tag(r["api_output"]) for r in fails)
        rows.append((run, len(fails), "; ".join(f"{k} {v} ({pct(v, len(fails))})" for k, v in c.most_common())))
    blocks.append(block("Failures by cause", "HARNESS-BRICKS-001",
                        "<p>Each failed row tagged from the response fields alone, in this order: error, dropped intent, resolution, empty "
                        "result, and what is left, <em>wrong or incomplete rows</em>. That last bucket cannot be split further from the "
                        "row: a model fault and an evaluation debt look the same. The noise margin needs two runs of the same configuration "
                        "on the same build, which this report looks for and does not find unless you ran one.</p>"
                        + table(["run", "failures", "tags"], rows, numeric=(1,))))
    return cards, blocks


# ---------------------------------------------------------------------------------------------
# vision-evidence
# ---------------------------------------------------------------------------------------------

def normalization_losses(raw):
    """What the normalized fields lose of the raw payload. Only computable once
    `raw_identification` is logged (from the version after 1.1.19's patch)."""
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return None
    c = Counter()
    works = people = 0
    for it in items:
        if not isinstance(it, dict) or not str(it.get("value") or "").strip():
            c["empty or malformed item"] += 1
            continue
        t = str(it.get("type") or "").strip().lower()
        if t not in VISION_ITEM_TYPES:
            c["type coerced to other"] += 1
        if str(it.get("year") or "").strip() and not re.fullmatch(r"\d{4}", str(it.get("year")).strip()):
            c["year blanked"] += 1
        kc = it.get("known_credits")
        if t not in ("movie", "serie") and isinstance(kc, dict) and any(kc.values()):
            c["known_credits dropped (not a work)"] += 1
        if t == "person":
            people += 1
        else:
            works += 1
    c["work over the cap"] += max(0, works - VISION_MAX_CANDIDATES)
    c["person over the cap"] += max(0, people - VISION_MAX_CANDIDATES)
    if str(raw.get("image_answer") or "").strip():
        c["image_answer written"] += 1
    return c


def vision_report(records, out_dir, uploads_dir):
    V = [r for r in records if r["image_ref"] and not r["already"]]
    ok = [r for r in V if isinstance(r.get("vision_evidence"), dict) and "hints" in r["vision_evidence"]]
    failed = [r for r in V if any(t.startswith(VISION_FAILED) for t in r["msgs"])]
    cached = [r for r in ok if r["vision_evidence"].get("cached")]
    fresh = [r for r in ok if not r["vision_evidence"].get("cached")]
    with_raw = [r for r in V if isinstance(r.get("vision_evidence"), dict) and "raw_identification" in r["vision_evidence"]]

    ev = [r["vision_evidence"] for r in ok]
    hints = [e.get("hints") or {} for e in ev]
    sel = [e.get("selected") for e in ev]
    cards = [
        card("Image requests", "FASTAPI-TEXT2SQL-114", str(len(V)),
             f"{V[0]['ts'][:8] if V else ''} to {V[-1]['ts'][:8] if V else ''}; {len(failed)} failed reads"),
        card("Recognition cache", "vision_cache.py", pct(len(cached), len(ok)), f"{len(cached)} of {len(ok)} readings served from the cache"),
        card("Reading time, fresh", "vision_identification_processing_time", f"{med([r.get('vision_t') for r in fresh]) or 'n/a'} s",
             f"median; p90 {p90([r.get('vision_t') for r in fresh]) or 'n/a'} s"),
        card("Raw payload logged", "vision_evidence.raw_identification", f"{len(with_raw)} of {len(V)}",
             "<span class='ok'>deployed</span>" if with_raw else "<span class='warn'>not yet in any log: the API in service predates the patch</span>"),
    ]
    blocks = []

    by_month = Counter(r["ts"][:6] for r in V)
    by_ver = Counter((r["api_version"], r.get("vision_model") or "?") for r in V)
    nonempty = sum(1 for r in ok if (r["nrows"] or 0) > 0)
    unread = [r for r in V if r not in ok]
    unread_html = (table(["date", "error code", "error", "vision messages"],
                         [(r["ts"][:8], r["error_code"], str(r["error"] or "")[:160], " / ".join(t[:120] for t in r["msgs"] if t.startswith("Vision"))) for r in unread])
                   if unread else "")
    blocks.append(block("Volume and outcome", "context",
                        f"<p>{len(ok)} readings reached a question; {nonempty} of them ({pct(nonempty, len(ok))}) returned rows. "
                        f"{len(failed)} reads failed, and before the 1.1.19 patch a failed read left <code>vision_evidence</code> null, "
                        "so its raw output is lost for those.</p>"
                        + table(["month", "requests"], sorted(by_month.items()), numeric=(1,))
                        + table(["API version", "vision model", "requests"], [(v, m, n) for (v, m), n in sorted(by_ver.items(), key=lambda x: str(x))], numeric=(2,))
                        + (f"<p>{len(unread)} image requests carry no reading at all.</p>" + unread_html if unread else "")))

    def dist(values):
        c = Counter(values)
        n = sum(c.values())
        return [(k if k != "" else "(empty)", v, pct(v, n)) for k, v in c.most_common()]

    faces = Counter(min(len(h.get("faces") or []), 5) for h in hints)
    blocks.append(block("What the model read in the image: hints", "vision_evidence.hints",
                        "<p>The free reading made before any identification: the kind of image, the title and credits as printed, the faces it "
                        "recognised, and the cues of era and genre.</p>"
                        + table(["kind", "readings", "share"], dist(h.get("kind") or "" for h in hints), numeric=(1, 2))
                        + table(["printed text language", "readings", "share"], dist(h.get("text_language") or "" for h in hints), numeric=(1, 2))
                        + table(["field", "non-empty", "share"], [
                            ("title_text", sum(bool(str(h.get("title_text") or "").strip()) for h in hints), pct(sum(bool(str(h.get("title_text") or "").strip()) for h in hints), len(hints))),
                            ("credits_block", sum(bool(str(h.get("credits_block") or "").strip()) for h in hints), pct(sum(bool(str(h.get("credits_block") or "").strip()) for h in hints), len(hints))),
                            ("faces", sum(bool(h.get("faces")) for h in hints), pct(sum(bool(h.get("faces")) for h in hints), len(hints))),
                            ("era_cues", sum(bool(h.get("era_cues")) for h in hints), pct(sum(bool(h.get("era_cues")) for h in hints), len(hints))),
                            ("genre_cues", sum(bool(h.get("genre_cues")) for h in hints), pct(sum(bool(h.get("genre_cues")) for h in hints), len(hints))),
                        ], numeric=(1, 2))
                        + table(["faces named (5 = five or more)", "readings"], sorted(faces.items()), numeric=(0, 1))))

    ncand = Counter(len(e.get("candidates") or []) for e in ev)
    ctypes = Counter(c.get("type") for e in ev for c in (e.get("candidates") or []) if isinstance(c, dict))
    conf_bins = Counter()
    for s in sel:
        if isinstance(s, dict):
            c = s.get("confidence") or 0
            conf_bins["0.95+" if c >= 0.95 else "0.80-0.95" if c >= 0.8 else "0.70-0.80" if c >= 0.7 else "below 0.70"] += 1
    flags = [("dominant", sum(bool(e.get("dominant")) for e in ev)),
             ("answered_from_faces", sum(bool(e.get("answered_from_faces")) for e in ev)),
             ("about_image", sum(bool(e.get("about_image")) for e in ev)),
             ("authoritative_empty", sum(bool(e.get("authoritative_empty")) for e in ev)),
             ("selected work carries known_credits", sum(isinstance(s, dict) and bool(s.get("known_credits")) for s in sel)),
             ("composed question is an IMDb id", sum(bool(IMDB_ID.match(str(e.get("composed_question") or ""))) for e in ev))]
    blocks.append(block("What the model identified: candidates", "vision_evidence.candidates, selected, people",
                        "<p>The ranked candidates after normalization, capped at "
                        f"{VISION_MAX_CANDIDATES} works and {VISION_MAX_CANDIDATES} people. <em>selected</em> is the one the question is built "
                        "from; it is dominant when its confidence is at least 0.70 and 0.20 above the runner-up.</p>"
                        + table(["candidates in the reading", "readings"], sorted(ncand.items()), numeric=(0, 1))
                        + table(["candidate type", "candidates"], ctypes.most_common(), numeric=(1,))
                        + table(["selected type", "readings", "share"], dist((s or {}).get("type") or "none" for s in sel), numeric=(1, 2))
                        + table(["confidence of the selected", "readings"], sorted(conf_bins.items()), numeric=(1,))
                        + table(["flag", "readings", "share"], [(k, v, pct(v, len(ev))) for k, v in flags], numeric=(1, 2))))

    idc = Counter((e.get("identity_check") or {}).get("decision") or "absent" for e in ev)
    cc = Counter()
    removed = 0
    for e in ev:
        c = e.get("credits_check")
        if not isinstance(c, dict):
            cc["absent"] += 1
        elif c.get("checked"):
            cc["checked"] += 1
            removed += len(c.get("removed") or [])
        else:
            cc["not checked: " + str(c.get("reason"))] += 1
    blocks.append(block("Checks against the database", "identity_check (-307), credits_check (-321)",
                        "<p><em>identity_check</em> picks among the works sharing the read title and year, using the credits the model knows. "
                        "<em>credits_check</em> removes from the evidence the people the returned works do not credit.</p>"
                        + table(["identity decision", "readings"], idc.most_common(), numeric=(1,))
                        + table(["credits check", "readings"], cc.most_common(), numeric=(1,))
                        + f"<p>{removed} person names removed by the credits check in all.</p>"))

    keys = Counter(k for e in ev for k in e.keys())
    rows = [(k, v, pct(v, len(ev))) for k, v in sorted(keys.items())]
    losses = Counter()
    for r in with_raw:
        c = normalization_losses(r["vision_evidence"].get("raw_identification"))
        if c:
            losses += c
    loss_html = (table(["what the normalization dropped", "occurrences"], losses.most_common(), numeric=(1,)) if losses
                 else "<p class='muted'>Nothing to compare yet: no log carries <code>raw_identification</code>.</p>")
    blocks.append(block("Field coverage of vision_evidence", "API output",
                        "<p>Which keys the logged <code>vision_evidence</code> carries, and how often. A key added by a later version appears "
                        "with a share below 100 %. Once <code>raw_identification</code> is in service, the second table counts what the "
                        "normalized fields lose of the model's output: items over the per-kind cap, types turned into <em>other</em>, "
                        "malformed years blanked, credits dropped outside movie and series, and <code>image_answer</code>, which the normalized "
                        "fields never carry.</p>"
                        + table(["key", "readings", "share"], rows, numeric=(1, 2)) + loss_html))

    rows = []
    for r in reversed(V[-60:]):
        e = r.get("vision_evidence") if isinstance(r.get("vision_evidence"), dict) else {}
        h = e.get("hints") or {}
        s = e.get("selected") or {}
        ref = r["image_ref"]
        img = os.path.join(uploads_dir, "vision", ref) if uploads_dir else ""
        thumb = (Raw(f'<img class="thumb" src="{esc(os.path.relpath(img, out_dir).replace(os.sep, "/"))}" alt="">')
                 if img and os.path.isfile(img) else Raw('<span class="muted">purged</span>'))
        people = ", ".join(str(p.get("value")) for p in (e.get("people") or []) if isinstance(p, dict))
        sel_txt = f"{s.get('type', '')}: {s.get('value', '')} {s.get('year') or ''} ({s.get('confidence', '')})" if s else ("failed read" if not e else "none")
        rows.append((thumb, r["ts"][:8] + " " + r["ts"][9:13], r["api_version"], h.get("kind", ""), h.get("title_text", ""),
                     sel_txt, people, (e.get("identity_check") or {}).get("decision", ""), e.get("user_question", ""),
                     e.get("composed_question", ""), r["nrows"], "yes" if e.get("cached") else ""))
    blocks.append(block("The last 60 image requests", "one row per request",
                        "<p>Newest first. The thumbnail comes from <code>uploads/</code> while the deposit is still there.</p>"
                        + table(["image", "date", "version", "kind", "title read", "selected", "people", "identity", "user question",
                                 "composed question", "rows", "cached"], rows, numeric=(10,))))
    return cards, blocks


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--logs", default=DEFAULT_LOGS, help=f"usage logs folder (default {DEFAULT_LOGS})")
    ap.add_argument("--evals", default=DEFAULT_EVALS, help=f"evaluation exports folder (default {DEFAULT_EVALS})")
    ap.add_argument("--eval-version", default=None, help="API version of the runs to read, formatted (default: the latest exported)")
    ap.add_argument("--out", default=None, help="output folder (default: <logs>/../reports)")
    ap.add_argument("--uploads", default=None, help="vision deposits, for thumbnails (default: <logs>/../uploads)")
    ap.add_argument("--since", default="", help="read only logs from this day on, YYYYMMDD")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.logs)), "reports")
    uploads = args.uploads or os.path.join(os.path.dirname(os.path.abspath(args.logs)), "uploads")
    os.makedirs(out_dir, exist_ok=True)

    print(f"reading logs in {args.logs}", file=sys.stderr)
    others = []
    records = scan_logs(args.logs, args.since, others)
    T = outer(records)
    version = args.eval_version or (latest_eval_version(args.evals) if os.path.isdir(args.evals) else None)
    runs = load_eval_rows(args.evals, version) if version else {}
    print(f"{len(records)} log records, {len(T)} outer questions; {len(runs)} runs of {version}", file=sys.stderr)

    now = dt.datetime.now()
    stamp = now.strftime("%Y%m%d")
    generated = now.strftime("%Y-%m-%d %H:%M")
    sources = f"{len(T)} logged questions, {len(runs)} runs of {version or 'no version'}"
    usage_name, vision_name = f"api-usage-{stamp}.html", f"vision-evidence-{stamp}.html"
    links = [("API usage", usage_name), ("Vision evidence", vision_name)]

    cards, blocks = [], [traffic_block(T)]
    c, b = cost_block(T, others)
    cards += c
    blocks.append(b)
    c, b = cache_block(T)
    cards += c
    blocks.append(b)
    c, b = asv_block(T)
    cards += c
    blocks.append(b)
    blocks.append(regen_block(T))
    guard_prod, guard_ver = guard_logs(T)
    c, bs = eval_blocks(runs, version, guard_prod, guard_ver, retry_policy_logs(T))
    cards += c
    blocks += bs
    intro = ("Measurements of the HARNESS-BRICKS tickets (Nestor, <code>projets/t2s-backlog/topics/harness-bricks.md</code>), "
             "rebuilt from the usage logs and the evaluation exports each time this script runs. Each section names its ticket. "
             "Figures are facts about the logs; what they mean for a ticket is argued in the backlog, not here.")
    with open(os.path.join(out_dir, usage_name), "w", encoding="utf-8") as fh:
        fh.write(page("fastapi-text2sql: API usage", "api-usage", generated, sources, intro, cards, blocks, links))

    c, bs = vision_report(records, out_dir, uploads)
    intro = ("What the vision model read in each image and what of it reaches the API result. Everything here is read from "
             "<code>vision_evidence</code> in the logged responses: <code>hints</code> is the reading, <code>candidates</code>, "
             "<code>selected</code> and <code>people</code> are the normalized identification, <code>identity_check</code> and "
             "<code>credits_check</code> are the checks against the database, and <code>raw_identification</code> (from the patch "
             "after 1.1.19) is the model's output untouched. The <code>messages</code> list only repeats a summary.")
    with open(os.path.join(out_dir, vision_name), "w", encoding="utf-8") as fh:
        fh.write(page("fastapi-text2sql: vision evidence", "vision-evidence", generated, sources, intro, c, bs, links))

    print(os.path.join(out_dir, usage_name))
    print(os.path.join(out_dir, vision_name))


if __name__ == "__main__":
    main()
