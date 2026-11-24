"""verify-api: drive a running fastapi-text2sql instance like a client, and keep the evidence.

Standard library only, so it runs anywhere with `uv run --no-project python <this file>`.
Every command prints a short verdict and writes the full JSON it saw under `.verify-api/`
(git-ignored), so a claim in a report can point at the file instead of a paraphrase.

Secrets: the API key and the OpenAI key are read from the environment, else from
`../text2sql-eval/.env` (the evaluator's file on Philippe's PC). They are sent as headers
and never printed; `fingerprint` shows the last four characters only, to tell two keys apart.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SKILL_DIR.parent.parent.parent
EVIDENCE_DIR = REPO_DIR / ".verify-api"
DEFAULT_HOST = "100.113.161.122"  # the VPS over Tailscale; every instance answers there
INSTANCE_PORTS = [8186, 8187, 8188, 8189]
LIVE_CONF = REPO_DIR.parent / "reverseproxy" / "includes" / "t2s-api-live.conf"
DEFAULT_ENV_FILE = REPO_DIR.parent / "text2sql-eval" / ".env"
FAST_PATH_QUESTION = "tt0033467"  # a bare IMDb id: answered without any LLM call or cache write


# ---------------------------------------------------------------- configuration

def load_env(path: Path) -> dict:
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$", line)
            if m:
                values[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return values


def secret(name: str, env_file: Path) -> str:
    return os.environ.get(name) or load_env(env_file).get(name, "")


def fingerprint(value: str) -> str:
    return f"...{value[-4:]}" if value else "(missing)"


def live_port() -> int | None:
    """The port NGINX sends public traffic to, read from the reverseproxy checkout if present."""
    if LIVE_CONF.is_file():
        m = re.search(r"server\s+[\d.]+:(\d+)", LIVE_CONF.read_text(encoding="utf-8"))
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------- HTTP

class Client:
    def __init__(self, host: str, port: int, env_file: Path, timeout: float):
        self.base = f"http://{host}:{port}"
        self.port = port
        self.timeout = timeout
        self.api_key = secret("TEXT2SQL_API_KEY", env_file)
        self.openai_key = secret("OPENAI_API_KEY", env_file)
        if not self.api_key:
            sys.exit(f"No TEXT2SQL_API_KEY in the environment nor in {env_file}.")

    def call(self, method: str, path: str, body: dict | None = None, openai: bool = False):
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        if openai and self.openai_key:
            headers["X-OpenAI-Key"] = self.openai_key
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return None, {"transport_error": str(e)}, time.perf_counter() - t0
        elapsed = time.perf_counter() - t0
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            payload = {"non_json_body": raw[:2000].decode("utf-8", "replace")}
        return status, payload, elapsed


def save_evidence(kind: str, port: int, payload) -> Path:
    EVIDENCE_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", kind.lower()).strip("-")[:60]
    path = EVIDENCE_DIR / f"{stamp}-{port}-{slug}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------- response reading

def result_rows(resp: dict) -> list:
    """`result` is a list of {"index": n, "data": {column: value}}; return the data dicts."""
    result = resp.get("result")
    if not isinstance(result, list):
        return []
    return [r.get("data", r) if isinstance(r, dict) else r for r in result]


def summarize_search(resp: dict) -> dict:
    """The fields a verifier reads first. Rows are counted, not printed."""
    cost = resp.get("llm_cost")
    if isinstance(cost, dict):
        cost = cost.get("total_usd", cost.get("total", cost))
    cache = ("exact" if resp.get("cached_exact_question") else
             "anonymized" if resp.get("cached_anonymized_question") else
             "embedding" if resp.get("cached_anonymized_question_embedding") else None)
    return {
        "api_version": resp.get("api_version"),
        "error": resp.get("error") or None,
        "error_code": resp.get("error_code"),
        "rows_on_page": len(result_rows(resp)),
        "result_kind": resp.get("result_kind"),
        "representation": resp.get("representation"),
        "result_entity": resp.get("result_entity") or None,
        "cache_hit": cache,
        "complex_model_used": resp.get("complex_model_used"),
        "llm_cost": cost,
        "total_processing_time": resp.get("total_processing_time"),
        "sql_query": " ".join((resp.get("sql_query") or "").split())[:400],
    }


LABEL_KEYS = ("MOVIE_TITLE", "SERIE_TITLE", "PERSON_NAME", "TITLE", "NAME", "ORIGINAL_TITLE", "DESCRIPTION")


def first_row_labels(resp: dict, n: int = 5) -> list:
    labels = []
    for row in result_rows(resp)[:n]:
        if isinstance(row, dict):
            label = next((row[k] for k in LABEL_KEYS if row.get(k)), None)
            if label is None:
                label = next((v for k, v in row.items() if k.endswith(("_TITLE", "_NAME")) and v), None)
            labels.append(label if label is not None else {k: row[k] for k in list(row)[:3]})
    return labels


def print_block(title: str, data) -> None:
    print(f"== {title}")
    if isinstance(data, dict):
        for k, v in data.items():
            print(f"   {k}: {v}")
    else:
        print(f"   {data}")


# ---------------------------------------------------------------- commands

def cmd_instances(args) -> int:
    live = live_port()
    print(f"host {args.host}, live port per reverseproxy: {live or 'unknown (no reverseproxy checkout)'}")
    rows = []
    for port in INSTANCE_PORTS:
        status, payload, elapsed = Client(args.host, port, args.env_file, 10).call("GET", "/")
        if status != 200:
            reason = "connection refused" if "10061" in str(payload) or "refused" in str(payload) else str(payload.get("transport_error", status))[:60]
            rows.append((port, "down", "", "", reason))
            continue
        rows.append((port, payload.get("instance"), payload.get("api_version"),
                     "ready" if payload.get("bktrees_ready") else "WARMING UP",
                     f"{elapsed*1000:.0f} ms" + ("  <= live" if port == live else "")))
    for r in rows:
        print("  {:<6} {:<8} {:<8} {:<11} {}".format(*[str(x) for x in r]))
    return 0


def cmd_doctor(args) -> int:
    """Read-only health check: identity, readiness, fast path, one entity endpoint, samples."""
    c = Client(args.host, args.port, args.env_file, args.timeout)
    ok = True
    evidence = {}
    status, hello, ms = c.call("GET", "/")
    evidence["hello"] = hello
    if status != 200:
        print_block("GET /", f"FAIL status={status} {hello}")
        return 2
    ready = bool(hello.get("bktrees_ready"))
    ok &= ready
    print_block("GET /", {"instance": hello.get("instance"), "api_version": hello.get("api_version"),
                          "bktrees_ready": ready, "latency_ms": round(ms * 1000),
                          "lexicons": len(hello.get("lexicons") or {})})
    if not ready:
        print("   warming up: do not judge this instance yet (the BK-tree warm-up takes minutes).")

    status, fast, ms = c.call("POST", "/search/text2sql",
                              {"question": FAST_PATH_QUESTION, "retrieve_from_cache": False, "store_to_cache": False})
    evidence["fast_path"] = fast
    s = summarize_search(fast) if status == 200 else {"status": status}
    fast_ok = status == 200 and not fast.get("error") and (s.get("rows_on_page") or 0) >= 1
    ok &= fast_ok
    print_block(f"fast path {FAST_PATH_QUESTION} ({'ok' if fast_ok else 'FAIL'})",
                {"rows_on_page": s.get("rows_on_page"), "first": first_row_labels(fast, 1),
                 "llm_cost": s.get("llm_cost"), "latency_ms": round(ms * 1000)})

    status, movie, ms = c.call("GET", "/movies/15")
    evidence["movie_15"] = movie
    movie_ok = status == 200 and isinstance(movie, dict) and not movie.get("detail")
    ok &= movie_ok
    print_block(f"GET /movies/15 ({'ok' if movie_ok else 'FAIL'})",
                {"status": status, "title": (movie or {}).get("MOVIE_TITLE"),
                 "latency_ms": round(ms * 1000)})

    status, samples, ms = c.call("GET", "/samples?ui_language=en")
    evidence["samples"] = {"status": status, "top_level_keys": list(samples)[:10] if isinstance(samples, dict) else type(samples).__name__}
    samples_ok = status == 200
    ok &= samples_ok
    print_block(f"GET /samples ({'ok' if samples_ok else 'FAIL'})", {"status": status, "latency_ms": round(ms * 1000)})

    key = c.openai_key
    print_block("keys", {"api_key": fingerprint(c.api_key), "openai_key": fingerprint(key)})
    path = save_evidence("doctor", args.port, evidence)
    print(f"evidence: {path}")
    print("VERDICT:", "HEALTHY" if ok else "NOT HEALTHY")
    return 0 if ok else 1


def run_question(c: Client, question: str, lang: str, use_cache: bool, extra: dict | None = None):
    body = {"question": question, "ui_language": lang,
            "retrieve_from_cache": use_cache, "store_to_cache": False}
    body.update(extra or {})
    return c.call("POST", "/search/text2sql", body, openai=True)


def cmd_ask(args) -> int:
    c = Client(args.host, args.port, args.env_file, args.timeout)
    extra = json.loads(args.extra) if args.extra else None
    status, resp, elapsed = run_question(c, args.question, args.lang, args.cache, extra)
    path = save_evidence("ask-" + args.question, args.port, {"request": {"question": args.question, "ui_language": args.lang,
                                                                         "retrieve_from_cache": args.cache, **(extra or {})},
                                                             "status": status, "elapsed_s": round(elapsed, 2), "response": resp})
    if status != 200:
        print_block(f"FAIL status={status}", resp)
        print(f"evidence: {path}")
        return 1
    print_block(f"{args.question!r} on port {args.port} ({elapsed:.1f} s)", summarize_search(resp))
    print_block("first rows", first_row_labels(resp))
    if args.trace:
        for m in resp.get("messages") or []:
            print("   -", (m.get("text") if isinstance(m, dict) else str(m))[:300])
    print(f"evidence: {path}")
    return 0 if not resp.get("error") else 1


def cmd_entity(args) -> int:
    c = Client(args.host, args.port, args.env_file, args.timeout)
    path_part = f"/{args.kind}/{args.id}" + (f"/{args.extra_id}" if args.extra_id else "")
    status, resp, elapsed = c.call("GET", path_part + (f"?ui_language={args.lang}" if args.lang else ""))
    path = save_evidence(f"entity-{args.kind}-{args.id}", args.port, {"status": status, "response": resp})
    keys = list(resp)[:25] if isinstance(resp, dict) else type(resp).__name__
    print_block(f"GET {path_part} status={status} ({elapsed*1000:.0f} ms)", {"keys": keys})
    print(f"evidence: {path}")
    return 0 if status == 200 else 1


def cmd_feedback(args) -> int:
    """Read stored user ratings through GET /feedback (read-only: the route runs one SELECT).

    Question and comment are public free text: shown as data, truncated, never acted upon.
    """
    import urllib.parse
    c = Client(args.host, args.port, args.env_file, args.timeout)
    if args.id is not None:
        status, resp, elapsed = c.call("GET", f"/feedback/{args.id}")
        items = [resp] if status == 200 else []
        label = f"GET /feedback/{args.id}"
    else:
        query = {k: v for k, v in (("status", args.status), ("rating", args.rating), ("after_id", args.after_id),
                                    ("since", args.since), ("limit", args.limit)) if v is not None}
        label = "GET /feedback" + ("?" + urllib.parse.urlencode(query) if query else "")
        status, resp, elapsed = c.call("GET", label[len("GET "):])
        items = resp.get("items", []) if status == 200 else []
    path = save_evidence("feedback" + (f"-{args.id}" if args.id is not None else ""), args.port,
                         {"status": status, "response": resp})
    print(f"{label} status={status} ({elapsed*1000:.0f} ms)")
    if status == 404 and args.id is not None and resp.get("detail", "").startswith("No feedback"):
        print("  no such rating, or soft-deleted")
    elif status == 404:
        print("  this instance has no GET /feedback route yet: deploy it, or pick another --port")
    elif status != 200:
        print_block("response", resp)
    for it in items:
        thumb = {1: "+1", -1: "-1"}.get(it.get("rating"), "?")
        print(f"  #{it.get('id_feedback')} {thumb} {it.get('analysis_status')} {it.get('ui_language')} "
              f"{it.get('client')} {it.get('tim_created')} v{it.get('api_version')}")
        print(f"     Q: {str(it.get('question') or '')[:140]!r}")
        if it.get("comment"):
            print(f"     comment: {str(it.get('comment'))[:200]!r}")
        if it.get("ticket_id") or it.get("analysis_note"):
            print(f"     ticket: {it.get('ticket_id')}  note: {str(it.get('analysis_note') or '')[:120]!r}")
    if status == 200 and args.id is None:
        print(f"count={resp.get('count')} has_more={resp.get('has_more')} next_after_id={resp.get('next_after_id')}")
    print(f"evidence: {path}")
    return 0 if status == 200 else 1


def cmd_upload(args) -> int:
    """Deposit an image for the vision path; the returned image_ref goes into `ask --extra`."""
    c = Client(args.host, args.port, args.env_file, args.timeout)
    data = Path(args.file).read_bytes()
    req = urllib.request.Request(c.base + "/uploads/vision", data=data, method="POST",
                                 headers={"X-API-Key": c.api_key, "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=c.timeout) as resp:
            status, payload = resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        status, payload = e.code, {"body": e.read()[:500].decode("utf-8", "replace")}
    print_block(f"POST /uploads/vision status={status}", payload)
    if status == 200:
        print(f"next: ask \"what is this?\" --extra '{{\"image_ref\": \"{payload.get('image_ref')}\"}}'")
    return 0 if status == 200 else 1


def cmd_compare(args) -> int:
    """Same question on two instances: the check before and after a switch."""
    out = {}
    for port in args.ports:
        c = Client(args.host, port, args.env_file, args.timeout)
        status, resp, elapsed = run_question(c, args.question, args.lang, args.cache)
        out[port] = {"status": status, "elapsed_s": round(elapsed, 2), "summary": summarize_search(resp) if status == 200 else resp,
                     "first": first_row_labels(resp) if status == 200 else None, "response": resp}
    a, b = args.ports
    print(f"== {args.question!r}")
    for field in ("api_version", "error", "rows_on_page", "result_kind", "representation", "cache_hit", "llm_cost"):
        va, vb = out[a]["summary"].get(field), out[b]["summary"].get(field)
        print(f"   {field:<16} {str(va):<24} {str(vb):<24} {'' if va == vb else '<== differs'}")
    print(f"   first rows {a}: {out[a]['first']}")
    print(f"   first rows {b}: {out[b]['first']}")
    sa, sb = out[a]["summary"].get("sql_query"), out[b]["summary"].get("sql_query")
    print("   sql:", "identical" if sa == sb else "DIFFERENT (see evidence)")
    path = save_evidence("compare-" + args.question, a, out)
    print(f"evidence: {path}")
    return 0


def check_expectation(exp: dict, status: int, resp: dict) -> list:
    """Return the list of failed expectations (empty means pass)."""
    fails = []
    if status != 200:
        return [f"status {status}"]
    s = summarize_search(resp)
    if exp.get("no_error", True) and resp.get("error"):
        fails.append(f"error: {resp.get('error')[:120]}")
    if "min_rows" in exp and (s["rows_on_page"] or 0) < exp["min_rows"]:
        fails.append(f"rows {s['rows_on_page']} < {exp['min_rows']}")
    if "max_rows" in exp and (s["rows_on_page"] or 0) > exp["max_rows"]:
        fails.append(f"rows {s['rows_on_page']} > {exp['max_rows']}")
    for field in ("representation", "result_kind", "error_code"):
        if field in exp and s.get(field) != exp[field]:
            fails.append(f"{field} {s.get(field)!r} != {exp[field]!r}")
    if "first_row_contains" in exp:
        blob = json.dumps(first_row_labels(resp, exp.get("within_first", 5)), ensure_ascii=False).lower()
        if exp["first_row_contains"].lower() not in blob:
            fails.append(f"{exp['first_row_contains']!r} not in the first rows")
    if "sql_contains" in exp and exp["sql_contains"].lower() not in (resp.get("sql_query") or "").lower():
        fails.append(f"SQL lacks {exp['sql_contains']!r}")
    return fails


def cmd_smoke(args) -> int:
    """Run the probes of features/smoke.json; `--free` keeps the ones that spend no token."""
    probes = json.loads((SKILL_DIR / "features" / "smoke.json").read_text(encoding="utf-8"))["probes"]
    if args.free:
        probes = [p for p in probes if p.get("free")]
    if args.feature:
        probes = [p for p in probes if p["feature"] in args.feature]
    c = Client(args.host, args.port, args.env_file, args.timeout)
    results, failed = [], 0
    for p in probes:
        if p.get("method", "POST") == "GET":
            status, resp, elapsed = c.call("GET", p["path"])
            fails = [] if status == 200 else [f"status {status}"]
        else:
            status, resp, elapsed = run_question(c, p["question"], p.get("lang", "en"), p.get("cache", False), p.get("extra"))
            fails = check_expectation(p.get("expect", {}), status, resp)
        known = bool(fails) and p.get("known_issue")
        failed += bool(fails) and not known
        mark = "PASS" if not fails else ("KNOWN" if known else "FAIL")
        label = p.get("question") or p.get("path")
        detail = "" if not fails else "  -> " + "; ".join(fails) + (f"  (known: {p['known_issue']})" if known else "")
        print(f"  {mark:<5} [{p['feature']}] {label}  ({elapsed:.1f} s){detail}")
        results.append({"probe": p, "status": status, "elapsed_s": round(elapsed, 2), "fails": fails, "response": resp})
    path = save_evidence("smoke", args.port, results)
    print(f"evidence: {path}")
    print(f"VERDICT: {len(probes) - failed}/{len(probes)} passed or known" + (", NEW FAILURES" if failed else ""))
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------- entry point

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=None, help="instance port; default: the live one per reverseproxy, else 8186")
    ap.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    ap.add_argument("--timeout", type=float, default=180.0)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("instances", help="identity and readiness of every instance")
    sub.add_parser("doctor", help="read-only health check of one instance, no token spent")

    p = sub.add_parser("ask", help="one question, like a client; cache read off and write off by default")
    p.add_argument("question")
    p.add_argument("--lang", default="en")
    p.add_argument("--cache", action="store_true", help="allow reading the cache (writing stays off)")
    p.add_argument("--trace", action="store_true", help="print the messages trace")
    p.add_argument("--extra", help="JSON merged into the request body, e.g. '{\"page\": 2}'")

    p = sub.add_parser("entity", help="GET an entity detail endpoint, e.g. entity movies 15")
    p.add_argument("kind")
    p.add_argument("id")
    p.add_argument("extra_id", nargs="?", help="season number for 'seasons'")
    p.add_argument("--lang")

    p = sub.add_parser("feedback", help="read stored user ratings (GET /feedback, read-only); default: status new")
    p.add_argument("--id", type=int, help="one rating by id")
    p.add_argument("--status", help="comma list of new, analysed, fixed, not_a_defect, no_action, or all")
    p.add_argument("--rating", type=int, choices=(1, -1))
    p.add_argument("--after-id", type=int)
    p.add_argument("--since", help="YYYY-MM-DD or 'YYYY-MM-DD HH:MM', Paris time")
    p.add_argument("--limit", type=int)

    p = sub.add_parser("upload", help="deposit an image (JPEG, PNG, WEBP) for the vision path")
    p.add_argument("file")

    p = sub.add_parser("compare", help="same question on two instances")
    p.add_argument("question")
    p.add_argument("--ports", type=int, nargs=2, required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("--cache", action="store_true")

    p = sub.add_parser("smoke", help="run the probes of features/smoke.json")
    p.add_argument("--free", action="store_true", help="only probes that spend no token")
    p.add_argument("--feature", nargs="*", help="restrict to these feature names")

    args = ap.parse_args()
    if args.port is None:
        args.port = live_port() or 8186
    return {"instances": cmd_instances, "doctor": cmd_doctor, "ask": cmd_ask, "entity": cmd_entity,
            "compare": cmd_compare, "smoke": cmd_smoke, "upload": cmd_upload,
            "feedback": cmd_feedback}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
