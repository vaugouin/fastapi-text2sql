"""Live driver for the voice-agent conversational harness benchmark.

Drives the voice-agent `/text-chat` endpoint with scenarios built from the
question bank, captures the tool-call trace, scores the final result with the
canonical assertion DSL, and reports the recovery baseline.

This establishes the BASELINE *without* the diagnostic signals (the voice-agent
runs with complex_question_processing=False, so recovery is the agent's own work).

Dependencies: only `requests` (already in eval/requirements.txt) + what
harness_lib needs (pandas, the eval DSL). No `httpx`, on purpose, so this runs
inside the existing text2sql-eval Docker image with no extra packages.

Prerequisites (your infra / secrets — not bundled):
- the voice-agent running and reachable (default http://127.0.0.1:3000);
- the voice-agent configured with OPENAI_API_KEY and a reachable text2sql API.

Run (locally):
  cd eval
  python harness/run_harness.py --lang en --limit 30

Run (on the VPS, reusing the eval image — see README "Running on the VPS"):
  docker run -it --rm --network=host \
    -e VOICE_AGENT_URL=http://localhost:3000 \
    -v /home/debian/docker/shared_data/text2sql-eval:/shared \
    --entrypoint python text2sql-eval-python-app \
    harness/run_harness.py --lang en --limit 30

Outputs land in $HARNESS_OUT_DIR, else /shared/harness if /shared is mounted,
else harness/results/.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_lib as H

DEFAULT_URL = os.getenv("VOICE_AGENT_URL", "http://127.0.0.1:3000").rstrip("/")


def default_out_dir() -> Path:
    env = os.getenv("HARNESS_OUT_DIR")
    if env:
        return Path(env)
    shared = Path("/shared")
    if shared.is_dir():
        return shared / "harness"
    return Path(__file__).resolve().parent / "results"


def drive_scenario(session: requests.Session, url: str, scenario: dict[str, Any],
                   timeout: float) -> dict[str, Any]:
    """Run one (possibly multi-turn) scenario; classify on the final turn."""
    context: list[dict[str, Any]] = []
    final_text, final_tool_outputs = "", []

    for msg in scenario["turns"]:
        resp = session.post(f"{url}/text-chat", json={"message": msg, "context": context}, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        final_text = body.get("text", "") or ""
        final_tool_outputs = body.get("tool_outputs", []) or []
        # rebuild conversational context the way the browser UI does
        context.append({"type": "user", "text": msg})
        context.append({"type": "assistant", "text": final_text})
        for o in final_tool_outputs:
            context.append({"type": "tool", "tool_name": o.get("name", "tool"), "endpoint": ""})

    trace = H.parse_tool_trace(final_tool_outputs)
    cls = H.classify_run(trace, scenario["assertion"], final_answer_text=final_text)
    cls.pop("details", None)
    return {
        "id": scenario["id"],
        "lang": scenario["lang"],
        "category_id": scenario["category_id"],
        "question": scenario["turns"][0],
        "assertion": scenario["assertion"],
        "final_answer_text": final_text[:240],
        **cls,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Voice-agent harness baseline runner")
    ap.add_argument("--voice-agent-url", default=DEFAULT_URL)
    ap.add_argument("--lang", choices=["en", "fr"], default="en")
    ap.add_argument("--source", choices=["auto", "db", "json"], default="auto",
                    help="question-bank source: auto (DB if DB_HOST set, else JSON), db, or json")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--categories", default="", help="comma-separated category ids to keep")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    args.voice_agent_url = args.voice_agent_url.rstrip("/")  # tolerate trailing slash

    out_dir = Path(args.out_dir) if args.out_dir else default_out_dir()

    cat_ids = None
    if args.categories.strip():
        cat_ids = {int(x) for x in args.categories.split(",") if x.strip()}

    scenarios = H.load_scenarios(lang=args.lang, limit=args.limit, category_ids=cat_ids, source=args.source)
    if not scenarios:
        print("No scenarios matched the filters.")
        return
    print(f"Driving {len(scenarios)} scenarios against {args.voice_agent_url} (lang={args.lang})")

    results: list[dict[str, Any]] = []
    with requests.Session() as session:
        for i, sc in enumerate(scenarios, 1):
            try:
                rec = drive_scenario(session, args.voice_agent_url, sc, args.timeout)
                flag = "PASS" if rec["passed"] else ("REC?" if rec["initial_empty"] else "FAIL")
                print(f"  [{i}/{len(scenarios)}] id={sc['id']:<5} {flag:<4} "
                      f"strategy={rec['strategy']:<22} t2s_calls={rec['n_t2s_calls']}")
            except Exception as e:  # network / HTTP / parse error for this scenario
                rec = {
                    "id": sc["id"], "lang": sc["lang"], "category_id": sc["category_id"],
                    "question": sc["turns"][0], "assertion": sc["assertion"],
                    "run_error": str(e)[:300],
                }
                print(f"  [{i}/{len(scenarios)}] id={sc['id']:<5} ERROR  {str(e)[:80]}")
            results.append(rec)

    out_dir.mkdir(parents=True, exist_ok=True)

    # per-scenario CSV
    cols = ["id", "lang", "category_id", "passed", "initial_empty", "final_empty",
            "recovered", "retry_attempted", "strategy", "answer_without_result",
            "n_t2s_calls", "n_detail_calls", "final_result_count",
            "initial_diagnostic_reason", "final_diagnostic_reason", "run_error",
            "question", "assertion", "final_answer_text"]
    csv_path = out_dir / f"harness_results_{args.lang}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)

    # rollup
    agg = H.aggregate(results)
    txt_path = out_dir / f"harness_global_{args.lang}.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        f.write("Voice-agent harness — recovery BASELINE (no diagnostic signals)\n")
        f.write("=" * 64 + "\n\n")
        f.write(f"Voice-agent URL: {args.voice_agent_url}\n")
        f.write(f"Language: {args.lang}   Scenarios: {len(scenarios)}"
                f"   Categories: {sorted(cat_ids) if cat_ids else 'all'}\n\n")
        f.write(json.dumps(agg, indent=2, ensure_ascii=False) + "\n")

    print()
    print(txt_path.read_text(encoding="utf-8"))
    print(f"Wrote {csv_path}")
    print(f"Wrote {txt_path}")


if __name__ == "__main__":
    main()
