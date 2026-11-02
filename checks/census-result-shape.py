"""Offline census of the result-shape hint: the committed module against the working copy.

Before committing a change to result_shape.py (AGENTS.md, "The representation hint has two
consumers"), recompute the representation of every export of a campaign with the module as
committed (`git show HEAD:result_shape.py`, or --old) and with the working copy, and print:
the counts per representation under each, every evaluation whose representation flips, the
rankings the new module emits grouped by the column marked `ordered`, and the out-of-score
result-shape assertions of the bank (text2sql-eval/data/evaluation) checked against the new
module. No database, no API, no LLM: the rows and the SQL are on disk in the exports.

Usage, from the repository root:
    uv run --no-project python checks/census-result-shape.py <exec_dir> [<exec_dir> ...]
        [--old PATH] [--eval-dir PATH]
    # <exec_dir>: a campaign tuple folder under shared_data/text2sql-eval/evaluation_execution
    # --old: a result_shape.py to compare against (default: the HEAD version, via git)
    # --eval-dir: the text2sql-eval clone (default: ../text2sql-eval)

Written for FASTAPI-TEXT2SQL-351 (2026-11-02); the first census, for -350, was ad hoc.
"""
import argparse
import glob
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _head_module():
    """The committed result_shape.py, written to a temp file and imported."""
    src = subprocess.run(["git", "-C", ROOT, "show", "HEAD:result_shape.py"],
                         capture_output=True, text=True, check=True, encoding="utf-8").stdout
    fd, path = tempfile.mkstemp(suffix="_result_shape_head.py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(src)
    return _load("result_shape_head", path)


def _api_output(d):
    api = d.get("api_output") or {}
    if isinstance(api, str):
        try:
            api = json.loads(api)
        except Exception:
            api = {}
    return api


def _question(d, api):
    inp = d.get("api_input") or {}
    if isinstance(inp, str):
        try:
            inp = json.loads(inp)
        except Exception:
            inp = {}
    q = (inp.get("question") if isinstance(inp, dict) else None) or api.get("question") or ""
    return str(q)


def _assertions(eval_dir):
    out = {}
    for p in glob.glob(os.path.join(eval_dir, "data", "evaluation", "*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        spec = (d.get("assertions") or {}).get("result_shape")
        if spec and str(spec).strip():
            out[d.get("evaluation_id")] = str(spec)
    return out


def census(exec_dir, old, new, assertions, rsa):
    flips, fails = [], []
    ranked = defaultdict(list)
    counts_old, counts_new = Counter(), Counter()
    n = n_pass = n_fail = 0
    for path in sorted(glob.glob(os.path.join(exec_dir, "*.json"))):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        api = _api_output(d)
        rows = api.get("result") or []
        if "sql_query" not in api or not rows:
            continue
        n += 1
        eid, lang = d.get("evaluation_id"), d.get("language") or "?"
        sql, ent = api.get("sql_query") or "", api.get("result_entity") or ""
        o = old.classify_result(sql, rows, ent)
        c = new.classify_result(sql, rows, ent)
        counts_old[o["representation"]] += 1
        counts_new[c["representation"]] += 1
        ordered = [(x["name"], x.get("ordered")) for x in c["columns"] if x.get("ordered")]
        q = _question(d, api)
        if o["representation"] != c["representation"]:
            flips.append((eid, lang, o["representation"], c["representation"], ordered, q[:90], len(rows)))
        if c["representation"] == "ranked-bars":
            ranked[ordered[0][0] if ordered else "(no ordered column)"].append((eid, q[:70]))
        spec = assertions.get(eid)
        if spec and rsa is not None:
            resp = {"result_kind": c["result_kind"], "result_columns": c["columns"],
                    "representation": c["representation"]}
            passed, details = rsa.check_response(spec, resp)
            if passed:
                n_pass += 1
            else:
                n_fail += 1
                fails.append((eid, lang, [x["message"] for x in details if not x["passed"]]))
    print("=" * 100)
    print(f"{os.path.basename(exec_dir.rstrip(os.sep))}: {n} exports with rows")
    print("old:", dict(sorted(counts_old.items())))
    print("new:", dict(sorted(counts_new.items())))
    print(f"\nFLIPS ({len(flips)}):")
    for f in flips:
        print("  ", f)
    print("\nranked-bars under the new module, by ordered column:")
    for k, v in sorted(ranked.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k} ({len(v)}):")
        for eid, q in v[:12]:
            print(f"      {eid}  {q}")
        if len(v) > 12:
            print(f"      ... {len(v) - 12} more")
    if rsa is not None:
        print(f"\nresult-shape assertions with the new module: PASS {n_pass}  FAIL {n_fail}")
        for eid, lang, msgs in fails:
            print(f"  {eid} [{lang}]")
            for m in msgs:
                print(f"     {m}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exec_dirs", nargs="+")
    ap.add_argument("--old", default="", help="result_shape.py to compare against (default: HEAD)")
    ap.add_argument("--eval-dir", default=os.path.join(os.path.dirname(ROOT), "text2sql-eval"))
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    old = _load("result_shape_old", args.old) if args.old else _head_module()
    new = _load("result_shape_new", os.path.join(ROOT, "result_shape.py"))
    assertions = _assertions(args.eval_dir)
    rsa = None
    if os.path.isfile(os.path.join(args.eval_dir, "result_shape_assertions.py")):
        sys.path.insert(0, args.eval_dir)
        import result_shape_assertions as rsa  # noqa: E402
    for exec_dir in args.exec_dirs:
        if not os.path.isdir(exec_dir):
            print(f"not a directory: {exec_dir}", file=sys.stderr)
            continue
        census(exec_dir, old, new, assertions, rsa)
    return 0


if __name__ == "__main__":
    sys.exit(main())
