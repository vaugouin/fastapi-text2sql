#!/usr/bin/env python3
"""Prompt-cache bench: how often does a model actually read the text2sql prefix from cache?

PROMPT-CACHING-010. The 2026-09-27 campaign of gpt-6-sol on text2sql read nothing from cache on
57 % of its calls, at about ten requests a minute, where gpt-4o reads 98.7 % of the same prefix
at the same pace. On gpt-5.6 and later a miss is not just an uncached token: the prefix is
written to cache at 1.25 times the input price. At that miss rate Sol costs what gpt-4o costs,
and the whole saving of the GPT-6 line depends on this one number. This bench measures it, and
nothing else, without the API server, the database or the evaluator.

What it sends is what production sends for the text2sql task: the same system prompt, the same
`data/text_to_sql.md` template with its 25 K-token static prefix, a real anonymized question in
the dynamic tail, and the same sampling rule (temperature 0 for gpt-4o, reasoning_effort low for
GPT-6). Output is NOT capped by default, and that is a measured requirement, not a detail: on
2026-09-28, with `max_completion_tokens=400`, gpt-6-sol read nothing from cache on 50 calls out
of 50 and wrote the whole prefix every time (so a capped call is not the same cache entry as a
production call), while the same calls without the cap read 100 %. `--output-cap` keeps the old
behaviour only to reproduce that finding.

Arms run INTERLEAVED, one call of each arm in turn, so the time of day (OpenAI load, which the
Sol campaign showed moving the hit rate from 9 % to 69 % from one hour to the next) hits every
arm alike. An arm is `model:key` or `model:nokey`, optionally `:en` / `:fr` for the value put in
`{ui_language}` (default en); `key` sends `prompt_cache_key`, the routing hint the API now sends
by default. Alternating `:en` and `:fr` arms reproduces what a two-language campaign sends.

Usage:
  uv run --no-project --with openai --with python-dotenv eval/bench-prompt-cache.py \\
      --arms gpt-6-sol:nokey,gpt-6-sol:key,gpt-4o:key --n 30 --rpm 10 --out eval/data/bench/pc-YYYYMMDD.json

Reads OPENAI_API_KEY from the repository .env. Prints a per-arm table: calls, share of calls
served from cache (>= 90 % of the prompt cached), cached share of all prompt tokens, cache-write
tokens, and the cost of the arm at list prices.
"""
import argparse
import glob
import json
import os
import statistics
import sys
import time

from dotenv import load_dotenv
import openai

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
load_dotenv(os.path.join(REPO, ".env"))

SYSTEM_PROMPT = "You are a MariaDB SQL query generator. Respond only with the JSON content, no explanations."
CACHE_BOUNDARY_MARKER = "<!--CACHE_BOUNDARY-->"

# Per million tokens: uncached input, cached input, cache write, output.
# GPT-6 Sol and Luna: OpenAI model pages, read 2026-09-26/27; writes at 1.25x input from gpt-5.6 on.
# gpt-4o: NOT recorded in the repo, public list price assumed; no cache-write charge before gpt-5.6.
PRICES = {
    "gpt-6-sol": (2.00, 0.20, 2.50, 10.00),
    "gpt-6-luna": (0.10, 0.01, 0.125, 0.50),
    "gpt-4o": (2.50, 1.25, 2.50, 10.00),
}


def load_questions(limit):
    """Real anonymized questions from the latest execution exports, deduplicated, in bank order."""
    seen, out = set(), []
    for folder in sorted(glob.glob(os.path.join(HERE, "data", "evaluation_execution", "001.001.019_en_*"))):
        for f in sorted(glob.glob(os.path.join(folder, "*.json"))):
            try:
                o = (json.load(open(f, encoding="utf-8")).get("api_output") or {})
            except Exception:
                continue
            q = (o.get("question_anonymized") or o.get("question") or "").strip()
            if q and q not in seen:
                seen.add(q)
                out.append(q)
            if len(out) >= limit:
                return out
    return out


OUTPUT_CAP = False


def sampling_kwargs(model):
    if model.startswith("gpt-6") or model.startswith("gpt-5") or model.startswith("o"):
        return {"reasoning_effort": "low", **({"max_completion_tokens": 400} if OUTPUT_CAP else {})}
    return {"temperature": 0, **({"max_tokens": 200} if OUTPUT_CAP else {})}


def one_call(client, template, model, key, question, lang="en"):
    prompt = template.replace("{user_question}", question).replace("{ui_language}", lang)
    prompt = prompt.replace(CACHE_BOUNDARY_MARKER, "")
    kwargs = sampling_kwargs(model)
    if key:
        kwargs["extra_body"] = {"prompt_cache_key": "t2s-text2sql"}
    t0 = time.time()
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        **kwargs,
    )
    u = r.usage
    d = getattr(u, "prompt_tokens_details", None)
    od = getattr(u, "completion_tokens_details", None)
    return {
        "model": model, "key": key, "lang": lang, "question": question, "t": time.strftime("%H:%M:%S"),
        "latency": round(time.time() - t0, 2),
        "prompt_tokens": u.prompt_tokens,
        "cached_tokens": (getattr(d, "cached_tokens", 0) or 0) if d else 0,
        "cache_write_tokens": (getattr(d, "cache_write_tokens", 0) or 0) if d else 0,
        "completion_tokens": u.completion_tokens,
        "reasoning_tokens": (getattr(od, "reasoning_tokens", 0) or 0) if od else 0,
    }


def cost(rows, model):
    p_in, p_cached, p_write, p_out = PRICES.get(model, PRICES["gpt-6-sol"])
    total = 0.0
    for r in rows:
        uncached = r["prompt_tokens"] - r["cached_tokens"]
        write = min(r["cache_write_tokens"], uncached)
        total += ((uncached - write) * p_in + write * p_write + r["cached_tokens"] * p_cached
                  + r["completion_tokens"] * p_out) / 1e6
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arms", default="gpt-6-sol:nokey,gpt-6-sol:key,gpt-4o:key")
    ap.add_argument("--n", type=int, default=30, help="Calls per arm.")
    ap.add_argument("--rpm", type=float, default=10.0, help="Calls per minute PER ARM.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--output-cap", action="store_true",
                    help="Cap the output (max_completion_tokens 400 / max_tokens 200). Production sends no cap, "
                         "and on gpt-6-sol a capped call never reads the production cache entry.")
    ap.add_argument("--same-question", action="store_true",
                    help="Repeat the first question: the whole prompt is identical from call to call.")
    args = ap.parse_args()
    global OUTPUT_CAP
    OUTPUT_CAP = args.output_cap

    arms = []
    for a in args.arms.split(","):
        parts = a.strip().split(":")
        model = parts[0]
        k = parts[1] if len(parts) > 1 else "key"
        lang = parts[2] if len(parts) > 2 else "en"
        arms.append((model, k != "nokey", lang))
    template = open(os.path.join(REPO, "data", "text_to_sql.md"), encoding="utf-8").read()
    questions = load_questions(args.n)
    if args.same_question and questions:
        questions = [questions[0]] * args.n
    if len(questions) < args.n:
        sys.exit(f"only {len(questions)} questions found in eval/data/evaluation_execution; need {args.n}")
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    gap = 60.0 / (args.rpm * len(arms))
    print(f"{len(arms)} arms x {args.n} calls, {args.rpm:g}/min per arm, one call every {gap:.1f} s")
    rows = []
    for i in range(args.n):
        for model, key, lang in arms:
            t0 = time.time()
            try:
                r = one_call(client, template, model, key, questions[i], lang)
                rows.append(r)
                ratio = r["cached_tokens"] / r["prompt_tokens"] if r["prompt_tokens"] else 0
                print(f"  {i+1:3d} {model:11s} {'key  ' if key else 'nokey'} {lang} cached {ratio:6.1%} "
                      f"write {r['cache_write_tokens']:6d} out {r['completion_tokens']:4d} {r['latency']:5.1f}s")
            except Exception as e:
                print(f"  {i+1:3d} {model:11s} {'key  ' if key else 'nokey'} ERROR {str(e)[:200]}")
                if i == 0:
                    sys.exit("first call failed, aborting before spending")
            time.sleep(max(0.0, gap - (time.time() - t0)))

    print(f"\n{'arm':20s} {'calls':>5s} {'served from cache':>18s} {'cached tokens':>14s} "
          f"{'cache writes':>13s} {'median latency':>15s} {'cost':>8s} {'per 1,000':>10s}")
    for model, key, lang in arms:
        rs = [r for r in rows if r["model"] == model and r["key"] == key and r["lang"] == lang]
        if not rs:
            continue
        hits = sum(1 for r in rs if r["prompt_tokens"] and r["cached_tokens"] / r["prompt_tokens"] >= 0.9)
        ptok = sum(r["prompt_tokens"] for r in rs)
        ctok = sum(r["cached_tokens"] for r in rs)
        wtok = sum(r["cache_write_tokens"] for r in rs)
        c = cost(rs, model)
        print(f"{model + (':key' if key else ':nokey') + ':' + lang:20s} {len(rs):5d} {hits:9d} ({hits/len(rs):5.1%}) "
              f"{ctok/ptok:13.1%} {wtok:13d} {statistics.median(r['latency'] for r in rs):14.1f}s "
              f"${c:7.3f} ${c/len(rs)*1000:8.2f}")
    print("\nThe first call of each arm is a write by construction. Prices: see PRICES; gpt-4o's is assumed.")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        json.dump(rows, open(args.out, "w", encoding="utf-8"), indent=1)
        print(f"Per-call rows written to {args.out}")


if __name__ == "__main__":
    main()
