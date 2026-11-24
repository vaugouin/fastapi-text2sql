---
name: verify-api
description: Verify the fastapi-text2sql API for real, like a client, before calling a change done or a bug understood. Drives a running instance (blue 8186, green 8187, violet 8188, brown 8189, over Tailscale) with a bundled CLI, reads the response fields that matter, and saves the full JSON as evidence. Use it after any change to prompts, resolvers, cache, SQL guards, representations or endpoints; to reproduce a user report or a 👎; to check an instance before and after a switch; or when asked "does it work", "check the API", "reproduce this question", "is violet healthy", "compare blue and violet", "/verify-api". Not for scoring a whole bank of questions: that is text2sql-eval.
---

# verify-api

The agent checks its own work on the running API instead of handing the check to Philippe. Correctness first (does the answer hold the right rows), quality second. Everything goes through `scripts/verify_api.py`, so every session verifies the same way instead of rebuilding a `curl` each time.

```bash
V="uv run --no-project python .claude/skills/verify-api/scripts/verify_api.py"
$V instances                 # which instance runs which version, which is live, which is ready
$V doctor                    # read-only health of the live instance, no token spent
$V ask "<question>" [--lang fr] [--trace] [--cache] [--extra '{"page": 2}']
$V entity movies 15          # an entity detail endpoint (persons, series, seasons ID N, ...)
$V compare "<question>" --ports 8186 8188
$V smoke [--free] [--feature search languages]
$V upload poster.jpg         # vision path; then ask with --extra '{"image_ref": "..."}'
```

Default port: the live one read from `../reverseproxy/includes/t2s-api-live.conf`, else 8186; `--port N` for another. Keys: `TEXT2SQL_API_KEY` and `OPENAI_API_KEY` from the environment or `../text2sql-eval/.env`; never print them (the CLI shows the last four characters only).

## Workflow

1. **Locate.** Map the change or the report to a feature in `features/README.md` and read that file: how a client reaches it, what to read, the traps.
2. **Doctor.** `$V instances`, then `$V doctor --port N` on the instance that carries the code. Ready means `bktrees_ready: true`; never judge a warming instance.
3. **Drive.** Ask the exact question of the report or the questions the change targets, in both languages when relevant, cache read off (the default). For a fix, run the question **before** the fix (on the serving instance) and **after** (on the instance carrying it), or `compare` the two.
4. **Read the evidence.** Not only `error`: the first rows against the base (entity endpoints), the SQL, `dropped_clause`, `name_ambiguity`, `representation`, `complex_model_used`, the trace (`--trace`). A plausible list can be wrong.
5. **Smoke.** `$V smoke` on the instance carrying the change (paid set about 0.10 USD) or `$V smoke --free` when only the plumbing changed. A FAIL is a regression until proven otherwise; KNOWN marks an open defect named in `smoke.json`.
6. **Report.** Quote the verdicts and the evidence paths (`.verify-api/*.json`). Say what was not run and why (instance down, no key, a write path not exercised).

## Rules

- **Never hand Philippe a check this CLI can run.**
- **Never write to production from here**: cache write stays off, `POST /feedback` is not driven, no SQL is run. A check that needs a write is a question for Philippe.
- **Budget**: about 0.013 USD per question on a warm prompt cache, 0.13 USD for the first after a restart; say so before running more than about ten paid questions.
- **Upload only images that may stay 30 days on the server** (a poster, a still), never a personal photo.
- **Keep the map true**: when a request or response field, an endpoint or an expected answer changes, update the matching `features/*.md` and `smoke.json` in the same commit. A probe whose defect is fixed loses its `known_issue` field and becomes a regression guard.
- A defect found here becomes a backlog ticket and, when it is about answers, `text2sql-eval` questions (the rule "a feature that changes what the API answers starts with its evaluations").

## Maintenance

Once a week, or after a release: run `$V smoke` on the live instance, re-read each `features/*.md` against `main.py` (routes, `Text2SQLRequest`, `Text2SQLResponse`) and `README.md`, fix drift in the map, re-measure expectations that moved. Edit only this skill's folder; a product defect goes to the backlog, not into the skill.
