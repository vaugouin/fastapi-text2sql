# checks/ - offline checks and benches of the API

These scripts test the API's **internals**: they import its modules (`entity`, `main`, `text2sql`, `rapidfuzz_query`, `json_guardrails`, `response_rounding`) or read its files (`main.py`, `data/*.md`, `data/entity_resolution.json`). That is why they stayed in this repository when the evaluator left `eval/` for its own repository, [text2sql-eval](https://github.com/vaugouin/text2sql-eval), on 2026-10-12. The evaluator is an API client and talks to the API over HTTP only; these scripts are not.

Run them from the repository root (`uv run checks/<script>.py`), so that `sys.path` and the relative paths resolve. Three of them also read the evaluator: `bench-entity-extraction.py` and `test-entity-inference-boundary.py` import its DSL from the sibling folder `../text2sql-eval`, and the benches that need the execution exports read `../shared_data/text2sql-eval` (or `$TEXT2SQL_EVAL_EXPORT_DIR`).

## Families

- `verif-*`: offline or live checks pinned to one ticket (`verif-114.py`, `verif-308.py`, `verif-206.sh`, `verif-275.sh`...). The `.sh` ones run against a deployment, the `.py` ones need neither API nor database unless their docstring says otherwise.
- `check-*`: invariants of the resolution layer (`check-shortlist-gate*.py`, `check-score-metrics.py`, `check-rescue-309.py`) and of the ChromaDB store (`check-chromadb.py`, below).
- `bench-*`: off-production A/B benches of one LLM task or of the resolution thresholds. Their outputs go to `data/` (tracked) or `data/bench/` (local only, it carries the evaluation questions verbatim).
- `eval-309.*`, `replay-rescue-309.py`: the stage evaluation of the typographic rescue (FASTAPI-TEXT2SQL-309), Docker only on the VPS.
- `bench-jev*.{sh,py}` and `Dockerfile.jev`: the Jev answer-entity bench, in its own image.
- `test-*`: offline regression tests (`test-vision-homonyms.py`, `test-entity-inference-boundary.py`).

## The main benches

| File | Purpose |
|---|---|
| [bench-entity-extraction.py](bench-entity-extraction.py) | Off-production A/B bench for entity extraction. Runs two configurations over the same questions in one process and scores both with `ee_eval_two_layer` against `ASSERTIONS_ENTITY_EXTRACTION`. No API server, no execution row, no cache write. `uv run checks/bench-entity-extraction.py [--model-a M] [--model-b M] [--lang en|fr] [--limit N] [--workers N] [--out FILE] [--verbose]`, or `--questions-file PATH` to run one question per line with no database and no scoring. Two uses: compare two models, or pass the **same** model on both sides to measure the noise floor, i.e. how often the configuration disagrees with itself at temperature 0. That number is what tells a real regression from a coin flip: on 2026-08-23 gpt-4o disagreed with itself on 2 of 326 questions, which is how FASTAPI-TEXT2SQL-200 was settled (its candidate lost 11, so the gap was real). For a prompt change, which has no flag, run it before and after the edit with `--out` and diff the two files; `data/entity_extraction.md` hot-reloads, so no restart is needed |
| [bench-prompt-cache.py](bench-prompt-cache.py) | Off-production bench of the **provider prompt cache** on the text2sql prefix (PROMPT-CACHING-010). Sends exactly what production sends (same system prompt, `data/text_to_sql.md` with its 25 K-token static prefix, a real anonymized question, temperature 0 for gpt-4o, `reasoning_effort` low for GPT-6) straight to OpenAI, no server, no database, arms **interleaved** so the time of day hits each alike: `uv run --no-project --with openai --with python-dotenv checks/bench-prompt-cache.py --arms gpt-6-sol:nokey,gpt-6-sol:key,gpt-4o:key --n 25 --rpm 10 --out data/bench/pc-YYYYMMDD.json`. Prints per arm the share of calls served from cache, cached tokens, `cache_write_tokens` (billed 1.25x from gpt-5.6 on) and the cost per 1,000 calls. **Read a hit rate with care**: on gpt-5.6+ the implicit cache only reuses an identical full prompt (FASTAPI-TEXT2SQL-304), and this bench re-sends the same questions in the same order, so re-runs hit and fresh runs miss; measure with questions never sent before. The output cap does not change caching (tested 2026-09-29). With the explicit breakpoint the API now sends on gpt-5.6+, gpt-6-sol reads the 25.7 K static prefix on every new question |
| [bench-result-entity.py](bench-result-entity.py) | Off-production A/B bench for the **answer-entity classifier** (`f_classify_result_entity`), sibling of the row above. Same discipline: two models over the same questions in one process, no API server, no execution row, no cache write. `uv run checks/bench-result-entity.py [--model-a M] [--model-b M] [--lang en|fr] [--limit N] [--workers N] [--run VERSION] [--min-decidable N] [--noise-floor N] [--out FILE]`. **Why it exists rather than a pass-rate comparison:** the classifier is authoritative over the text-to-SQL model's own `result_entity` but only acts on disagreement, so it is inert on most of the bank; an evaluator campaign would spend $86 watching a task do nothing (since FASTAPI-TEXT2SQL-234 such a campaign would at least land in its own folder, but it would still measure a task that does nothing on most questions). **Ground truth is free and needs no database:** an execution that passed its assertions had the right answer type, so its `result_entity` is a label. Run `001.001.018` yields **689 EN** and **643 FR** usable questions after dropping the ones that failed, the ones labelled outside the classifier's 19-word vocabulary (`movie_video`, `movie_serie`, which come from the text-to-SQL model), and duplicates. **Three outcomes, never one accuracy number:** *correct*; *abstained* (`""` or an unknown word, which falls back to the pre-existing behaviour and costs nothing); *confidently wrong* (a different valid label, the only outcome that overrides a query that may have been right). The verdict is built on the confident-error rate alone. **Read the per-class table, not the headline:** `movie`+`person`+`serie` carry 90 % of the labels, so answering "movie" every time already scores ~54 %; the bench prints that majority baseline beside every score, and refuses a percentage for any class under `--min-decidable` (default 30) rather than printing one computed on seven examples. `--limit` samples **round-robin across classes**, rarest first, so a 14-question smoke run touches 14 classes instead of fourteen movies |
| [bench-entity-resolution.py](bench-entity-resolution.py) | Off-production bench for entity **resolution**, the sibling of the one above: what threshold separates a typo from a stranger. Of the fourteen resolvers in `data/entity_resolution.json` exactly one carries a rejection threshold (`Collection_name`, `min_fuzz_ratio` 72), so the other thirteen accept their nearest embeddings neighbour however far it sits: on 2026-08-24 "Wagonlit collection" resolved to "Life Collection". Calibration needs both classes, and the corpus holds only one: with no threshold everything resolved, so no rejection was ever recorded. The bench therefore **manufactures** its negatives, by cross injection (a value of type A fed to the resolver of type B) and by invented names. Its positives come from two sources only: the resolver's **own table** (`--catalogue-per-type`, the strongest, since such a value must resolve to itself) and pairs arbitrated by the assertions. Unscored log values are gathered as `observed-*` and deliberately kept OUT of the arithmetic, a correction made on 2026-08-24: counting them as positives dragged the recommended cut from 84.9 down to 45.5, because many of those resolutions are themselves the defect being hunted ("Collection Criterion" to "Ex Collection" at 18.2). Their low tail is reported separately, as a detector of false acceptances already in production. Every positive is also mutated on purpose (letters swapped, substituted, dropped), which is exactly what a threshold must never break. Pairs that never scored 1 are exported separately as `suspect`, to be triaged by hand. `uv run checks/bench-entity-resolution.py [--limit-per-type N] [--catalogue-per-type N] [--types T,T] [--build-only] [--no-unscored] [--out FILE]`. `--build-only` needs no database and skips the catalogue draw. The report gives an interval rather than a point, classification only changing at observed values, and stays silent on a field whose positive sample is too thin or biased |
| [harvest-archived-entities.py](harvest-archived-entities.py) | Harvests extracted entity values from the archived API logs on the VPS share (23530 files across both colours) into `checks/data/archived-entity-values.json`, with an occurrence count per value. Exists because usage is lopsided: 3 `Network_name` values against 363 `Person_name`, and a threshold calibrated on three examples is a superstition with decimals. It fixed the middle of the distribution (Topic_name 48 to 236, Collection_name 36 to 128) and, measurably, not the tail: across the 24040 archived requests `Network_name` shows **seven** distinct values, because nobody asks about a network by name. The scarcity is in the usage, not in the sampling, which is why the bench draws its thin types from the catalogue instead. The share reads at about 13 files per second, so a full pass takes half an hour: run it in the background, once, and re-run only when the archive has grown. Uses a regex rather than `json.load`, since parsing 23530 documents to reach one small dictionary in each is the expensive way, and a truncated file degrades to "no match" instead of raising. `uv run checks/harvest-archived-entities.py [--dirs D,D] [--limit N] [--out FILE]` |
| [check-chromadb.py](check-chromadb.py) | Consistency checks on the ChromaDB store read by entity resolution. A home for such checks, not a one-shot: `--list`, `--check NAME`, `--selftest`. Reads only, needs no OpenAI key. See section 14. |

## ChromaDB consistency checks (`check-chromadb.py`)

Entity resolution reads documents from ChromaDB, and what those documents contain is decided in
**another repository**. `embedding-update` writes `name + ": " + description` for several
entities; `data/entity_resolution.json` decides, per entity, whether to cut at
`document_name_separator` before scoring lexically. Neither file is wrong alone. Their
**disagreement** is, and nothing used to detect it.

The cost of that silence, measured 2026-08-29: `flamenco trilogy` scored **20** against a
threshold of 72 facing the full document, and **80** facing the name alone. The collections had
been indexed with descriptions for two months, the separator was never declared for them, and
the only symptom was an empty answer for a row that existed.

### Running it

```bash
uv run checks/check-chromadb.py                       # every check
uv run checks/check-chromadb.py --list                # what is available
uv run checks/check-chromadb.py --check separator-agreement
uv run checks/check-chromadb.py --selftest            # thresholds only, offline, no ChromaDB
uv run checks/check-chromadb.py --sample 2000         # bigger sample, slower
```

On the VPS, in Docker, same shape as section 2:

```bash
docker run -it --rm --network="host" \
  --env-file /home/debian/docker/fastapi-text2sql-blue/.env \
  --name fastapi-text2sql-check \
  -v /home/debian/docker/fastapi-text2sql-blue:/app \
  fastapi-text2sql-blue-app \
  python checks/check-chromadb.py
```

**The `-v` mount is required, and rebuilding is not an alternative.** Neither image can run
this script alone: the API image installs `chromadb` but its `Dockerfile` copies only `*.py`
and `./data/`, so `checks/` never enters it; the evaluator image (text2sql-eval repo) has neither
`chromadb` nor `data/`. Mounting the checkout over `/app` gives the API image the script and
a `data/entity_resolution.json` read from disk rather than frozen at build time. Mount the
colour currently serving, since its configuration is the one in force.

Exit code 1 on any ERROR, so it can gate a deployment. Host and port come from `CHROMADB_HOST`
and `CHROMADB_PORT`, defaulting to `localhost:8100`, which is what the VPS serves. Note that
`main.py` defaults the port to 8000 instead; the divergence is deliberate and documented in the
script rather than left to be discovered.

### The two checks it carries today

| Check | What it asserts |
|---|---|
| `separator-agreement` | A collection whose documents carry descriptions must declare `document_name_separator`. Also warns the other way round, a declaration standing while no document contains the separator any more, which is a false landmark for the next reader. |
| `collection-populated` | Every embeddings strategy points at a collection that exists and holds documents. An absent or empty collection makes its placeholder fail in silence. |

### Why it queries the store instead of reading the source

It would be easier to parse `embedding-update.py` and compare with the JSON. It would also be
wrong, for a reason that cost two days in the same week: a hand-written PHP unescaper disagreed
with PHP on the one sequence that mattered and certified a broken page, and a duplicate detector
written with `fuzz.ratio` found none of the three duplicates because it reproduced the very
defect it was hunting. **A checker that reimplements what it checks inherits its bugs.** Reading
the real documents cannot.

### The heuristic, and its honest limit

A name may legitimately contain the separator, `Star Trek: The Next Generation`, which is exactly
why cutting is opt-in per entity and must never be global. From the store alone, only **tail
length** separates a subtitle from a description: measured, subtitles run around 19 characters
while the descriptions appended to `T_WC_T2S_LIST` average 105. Hence
`DESCRIPTION_MIN_TAIL = 40` and `SUSPECT_SHARE = 0.10`.

**A share alone is not enough, and the first real run proved it.** On 2026-08-29 `lists` held
23 documents, 2 of them carrying a description, and reported **9%**, one point under the bar.
The check would have missed the very defect it was written for: on a small collection each
document weighs 4.3 points and a proportion stops being able to decide. Hence a second, softer
band, `WARN_MIN_COUNT = 2` with `WARN_MIN_SHARE = 0.02`: a handful of described documents warns
even when the share is low, while the floor of two keeps it quiet on the large catalogues where
a long subtitle is a legitimate accident. The same run measured `movies` at 3 long tails out of
1000, which is 0.3% and stays silent.

That is a heuristic, so the check never hands down a bare verdict: every line prints the numbers
it measured, and an accusation prints up to three offending documents. A human settles in one
glance what no threshold can. `--selftest` asserts the discrimination offline on four fixtures,
each one a shape measured on the real store: a series catalogue whose names are 40% colons and
must NOT be flagged, a list catalogue full of descriptions that must error, the real 23-document
`lists` at 9% that must warn, and a 1000-document catalogue with 3 long subtitles that must stay
silent.

### First run, 2026-08-29

No error. `topics` came back clean, confirming from the store what SQL had said, its `OVERVIEW`
is empty throughout. `collections`, the entity that started all this, shows 86% long tails with
a median of 227 characters and its separator properly declared. `lists` still carries its four
descriptions, so it doubles as a witness that the re-index has not run yet. And no false
positive on `movies` or `series`, whose colons are subtitles with medians of 17 and 15
characters.

### Adding a check

Decorate a function with `@check("my-name", "one line summary")`. It receives a `Context` (client,
resolution config, sample size) and returns a list of `Finding(level, target, message, evidence)`.
Put the numbers in `evidence`, and keep any threshold as a module constant with the measurement
that justifies it written next to the value.

For open-ended exploration of the same collections rather than assertions, Philippe uses the
separate `embedding-query` repository. This file is for the answers that must stay true.
