# LLM tasks, costs, benches and model changes

The six LLM tasks, what each costs and how that was measured, the provider prompt cache, the reasoning-family block, how an evaluation declares its resolution path, and how to add a measured indicator to the response.

Moved out of the root `AGENTS.md` on 2026-10-31 so that file keeps only the rules. A section name in italics refers to this document, to its siblings in `doc/` (`pipeline-internals.md`, `llm-tasks-and-costs.md`, `vision-pre-stage.md`), or to the rules left in [../AGENTS.md](../AGENTS.md) (the numbered *Gotchas* among them).

## The six LLM tasks, and what each one actually costs

There are **six** LLM calls in this pipeline, not the three the `llm_model_*` parameters
suggested until FASTAPI-TEXT2SQL-232. Five route through `text2sql._call_chat_llm` and the
sixth, which reads an image, through `text2sql._call_vision_llm`; each is tagged with a
`cache_label` that is also its key in the prompt-cache log and its default reasoning effort.
Since -232 each has its own request selector, its own response field naming the model that
served it, and since -233 its own wall clock.

| # | Task (`cache_label`) | Call site | Fires on | Selector |
|---|---|---|---|---|
| 1 | `entity_extraction` | `entity.py:269` | 100 % | `llm_model_entity_extraction` |
| 2 | `text2sql` | `text2sql.py:518` | 100 % | `llm_model_text2sql` |
| 3 | `result_entity` | `text2sql.py:629` | 99.9 % | `llm_model_result_entity` |
| 4 | `complex_question` | `text2sql.py:663` | ~1 % | `llm_model_complex` |
| 5 | ~~`answer_single_value`~~ | removed 2026-10-15 (FASTAPI-TEXT2SQL-331): it answered a single cell worth 0 from memory | never | `llm_model_answer_single_value`, accepted and ignored |
| 6 | `vision_identification` | `text2sql._call_vision_llm` | only with an `image_ref` | `llm_model_vision` |

Line numbers move; the `cache_label` does not. `grep -n 'cache_label="' text2sql.py entity.py`
is the durable way to find them (five since -331 removed task 5).

**Task 6 is priced apart from the five, and it is not in the table below.** It fires only on a
request carrying an image, so it has no frequency in a text campaign; it costs about **4 cents
a photo** (1229 tokens of image at `detail: "high"` plus the reasoning output, at gpt-6-astra's
$10 / $50 per million), which is two orders of magnitude above any other task per call. That is
what the recognition cache of *The vision pre-stage* exists to spend once rather than twice.

### Measured token profile (gpt-4o, v1.1.17–1.1.18)

Not estimates. Prompt and cache figures come from the 424 `Prompt cache (…)` records in
`logs/`; frequencies and latencies from the 1,690 executions of eval run `001.001.018`
(EN + FR). Reproduce with:

```bash
grep -rho "Prompt cache ([a-z0-9_]*): provider=[a-z]*, model=[^,]*, prompt_tokens=[0-9]*, cached_tokens=[0-9]*" logs/
```

Note the `[a-z0-9_]` character class: `text2sql` carries a digit, and a `[a-z_]` class
silently drops the single most expensive task in the pipeline from the tally.

**Output and reasoning tokens are measured since FASTAPI-TEXT2SQL-296 (2026-09-26).** The
"Output tok" column below was estimated because the logger threw that half of the usage
object away. Now every `Prompt cache (…)` message ends with `completion_tokens=` and
`reasoning_tokens=`, and every response carries **`llm_usage`**, per task:
`{task: {model, calls, prompt_tokens, cached_tokens, completion_tokens, reasoning_tokens}}`,
summed over the request's calls, both passes of a retried request included. As OpenAI bills
them, `prompt_tokens` includes `cached_tokens` and `completion_tokens` includes
`reasoning_tokens`. The accumulator is a `ContextVar` like the cache buffer, but it is only
read, never drained, because the inner pass of a retry ends before the outer one. On a
reasoning model (GPT-6) the reasoning tokens bill at the output price: read them before
comparing list prices. The evaluator stores the request totals in `LLM_PROMPT_TOKENS`,
`LLM_CACHED_TOKENS`, `LLM_COMPLETION_TOKENS`, `LLM_REASONING_TOKENS` and prints the per-task
table at the end of phase 20. Anthropic folds thinking into its output count, so its
`reasoning_tokens` stays 0 (unknown, not absent); OpenRouter is not counted at all. Its cache
writes are passed as `cache_write_tokens` since FASTAPI-TEXT2SQL-337, inside `prompt_tokens`
like OpenAI's.

| Task | Prompt tok | Cache hit | Uncached in | Output tok |
|---|---:|---:|---:|---:|
| `entity_extraction` | 8,555 | 73.9 % | 2,339 | ~25 |
| `text2sql` | 19,146 | 62.0 % | 7,378 | ~217 |
| `result_entity` | 577 | 0 % | 577 | ~2 |
| `complex_question` | 1,107 | 3.3 % | 1,073 | ~120 (est.) |
| `answer_single_value` | ~60 | 0 % | 60 | ~5 (est.) |

**`result_entity` never caches, and that is not a bug to fix by tuning.** At 577 tokens it
sits under OpenAI's ~1,024-token caching floor. Making it cacheable would mean padding the
prompt, which costs more than it saves.

**Tasks 1 and 2 carry 97 % of the bill.** Anything spent optimising 3, 4 and 5 is rounding
error, so measure before moving them. On gpt-4o the whole pipeline costs about **$50.69 per
1,000 requests**, which puts a full 1,690-execution evaluator run at roughly **$86**.

Latency baseline from the same run, for comparing any model swap against:

| Phase | mean | p50 | p90 | max |
|---|---:|---:|---:|---:|
| `entity_extraction` | 1.06 s | 0.91 s | 1.34 s | 7.65 s |
| `text2sql` | 3.61 s | 3.23 s | 5.39 s | 36.24 s |
| embeddings | 0.38 s | 0.02 s | 0.56 s | 99.09 s |
| query execution | 0.08 s | 0.00 s | 0.07 s | 10.66 s |
| **total** | **6.04 s** | **5.45 s** | **8.26 s** | **114.09 s** |

### What a call costs: `llm_cost`, `embedding_usage` and the request clock (FASTAPI-TEXT2SQL-337)

Since 2026-10-21 every response prices itself, and every log says how long the server worked.
Before, the tokens were there but each analysis script carried its own copy of the prices, the
embeddings were neither counted nor priced, Claude's cache writes were folded into its uncached
input (priced $4 instead of $5 per million on Opus 5.5), and the entity endpoints had no timing.

- **`llm_cost`** = `{total_usd, llm_usd, embeddings_usd, unpriced_models}`, and a `cost_usd` in
  each `llm_usage` entry, computed by `t2s.snapshot_usage_fields()` from [llm_costs.py](../llm_costs.py).
  A list-price estimate: the invoice stays the reference, and a campaign is how the two are
  checked against each other. Flex is counted at half price only when every call of the task was
  served Flex. **A model missing from `PRICES` is named in `unpriced_models` and left out of the
  totals, never priced at zero**: add its row (with source and date) when you add a model.
- **`embedding_usage`** = `{model, calls, prompt_tokens, cost_usd}`, filled by
  `OpenAIEmbeddingFunction._record_usage` through `t2s.record_embedding_usage`. **It is not a task
  of `llm_usage`, on purpose**: the evaluator's token columns, `analyze-usage-logs.py` and
  pipeline-3d sum the entries of `llm_usage` as chat calls. Do not merge them.
- **The construction sites call `**t2s.snapshot_usage_fields()`**, which fills the three fields
  at once; the complex retry assigns them with `setattr`. A new response site does the same.
- **`server_time` and `cpu_time`** follow `ts` in every log written during an HTTP request:
  wall seconds since the request entered the API, and process CPU seconds meanwhile (all
  threads, so concurrent requests leak in: read medians). The `_RequestClock` middleware is
  pure ASGI on purpose: with `BaseHTTPMiddleware` the endpoint would run in a child task and
  the clock would still be visible, but a pure ASGI layer makes it certain and costs nothing.
- **Where to read them over a period:** the *Cost price of a call* section of
  `analyze-usage-logs.py` (search cost in production and campaign, by text-to-SQL model; server
  and CPU time per endpoint, entity routes included); per campaign, the cost block the evaluator
  prints at the end of phase 20 (text2sql-eval 2.14.0).
- **The server's share (FASTAPI-TEXT2SQL-338).** Every log of a request also carries, after
  `cpu_time`, `sql_calls`, `sql_time`, `sql_rows`, `chroma_calls`, `chroma_time` and
  `server_cost_eur`; `/search/text2sql` returns the same block as `server_usage`, filled on a
  cache hit too. MariaDB and ChromaDB run in other containers and expose no per-query CPU, so
  the API times its **waits** on them: `_TimedDictCursor`, the cursor class of
  `get_db_connection`, times every statement (no call site to touch; **a new connection must
  come from `get_db_connection`** or it escapes the count), and `logs.chroma_call()` wraps each
  ChromaDB call, **minus the OpenAI embedding round trip** it makes client-side
  (`OpenAIEmbeddingFunction` reports it through `logs.record_embedding_wait`). **A new ChromaDB
  call site goes inside `with logs.chroma_call():`.** `server_cost_eur` = (`cpu_time` +
  `sql_time` + `chroma_time`) × `llm_costs.EUR_PER_CPU_SECOND`: an upper bound (a wait
  includes the network, and PyMySQL's row decoding is in both `sql_time` and `cpu_time`), and
  an allocation of a fixed, committed bill, not a marginal cost.
- **Measured up to the log line.** The entity endpoints call `log_usage` before their
  localization queries (`apply_localized_related_images`, `apply_localized_text`, `ui_language`
  other than `en` only), and the `?collection=` path writes no log: those few statements are
  not in the log's figures.

### Who can drive the six, and the two gaps

| client | how it selects | state |
|---|---|---|
| **evaluator** (`text2sql-eval/text2sql-eval.py`) | `--entity-extraction-model`, `--text2sql-model`, `--complex-model`, `--result-entity-model`, `--answer-single-value-model` | five of six; it cannot send an image at all, which is FASTAPI-TEXT2SQL-277 |
| **tmdb-front** | request params / cookies `eemodel`, `t2smodel`, `complexmodel`, `resultentitymodel`, `answermodel`, radio groups on the settings page | five of six; it sends `image_ref` but no vision-model selector (TMDB-FRONT-088) |
| **Claude, via MCP** | the six arguments of `sql_search`, `llm_model_vision` included | all six |
| **voice-agent** | does not send any; takes the server defaults | unchanged |

**The gap is closed (FASTAPI-TEXT2SQL-234, 2026-09-25).** `T_WC_T2S_EVALUATION_EXECUTION`
now stores all five models: `RESULT_ENTITY_MODEL` and `ANSWER_SINGLE_VALUE_MODEL` were added by
`text2sql-eval/archive/migrate-evaluation-execution-late-models.sql`, which must run before the evaluator of the
same commit. The folder suffix (`_re-<model>`, `_asv-<model>`) is built from the ROW, never from
the CLI, and only when the value differs from `gpt-4o`, so a re-export never labels an old row
with today's setting and the three-model folders keep their names. Rows older than the columns
hold NULL, matched as the default and exported as null; never backfill them.

### Measuring a model change on one task

Two off-production benches exist, one per classification task, and they follow the same
discipline: two configurations over the same questions in one process, no API server, no
execution row, no cache write.

| bench | task | ground truth |
|---|---|---|
| `checks/bench-entity-extraction.py` | 1, entity extraction | `ASSERTIONS_ENTITY_EXTRACTION` in the bank |
| `checks/bench-result-entity.py` | 3, answer-entity classifier | `result_entity` of executions that PASSED |

**Always measure the noise floor first, by running one model against itself.** At
temperature 0 a configuration still disagrees with itself, and until that number exists a
small delta cannot be told from a coin flip. Measured for the classifier on 2026-08-30,
`gpt-4o` against `gpt-4o`, 689 EN questions: **1 confident error on the 631 questions in
decidable classes, and 13 self-disagreements out of 689**. Eleven of those thirteen are an
abstention appearing or vanishing, which costs nothing; the run repeated a day apart gave
11 then 13, so treat the disagreement count as approximate and the confident-error floor,
1, as the number the verdict uses. Latency was identical on both sides, median 0.59 s.

So the bar for a challenger on this task is exact: **adopt it if it makes at most one more
confident error than `gpt-4o` on the decidable classes**. The FR floor has not been
measured.

**Result, `gpt-5.6-luna` against `gpt-4o`, 689 EN questions, 2026-08-30: HOLD.**

| | correct | abstained | **wrong** |
|---|---:|---:|---:|
| gpt-4o | 659 | 28 | **2** |
| gpt-5.6-luna | 678 | 5 | **6** |

On decidable classes only, which is what the verdict uses: 1 against 3, so **+2 against a
floor of 1**. Latency is a wash (median 0.59 s against 0.64 s; Luna's worst case is
actually better, 3.16 s against 13.58 s).

**This is the case the three-outcome design exists for.** A single accuracy number would
read "98.4 % against 95.6 %, adopt it", because Luna is right more often overall. It is
right more often because it abstains 23 times less, and an abstention costs nothing: the
caller falls back to the text-to-SQL model's own answer. What Luna actually does is convert
those abstentions into answers, most of them right and four of them **confidently wrong**,
and a confident error overrides a query that may have been correct. More correct and more
dangerous at the same time.

**The qualitative signal is worse than the count.** Of Luna's six, one is the known bad
label on evaluation 948, two are defensible readings of genuinely ambiguous questions
("Documentaries", "What talk shows are in the database?", both answered `genre`), and one
is the exact failure the classifier exists to prevent: **"Which people died from a heart
attack?" answered `death`**, taking the filter for the answer, when the prompt gives that
very shape as a worked example. `gpt-4o` gets it right.

**And the upside was never large.** This task costs $1.46 per 1,000 requests against Luna's
$0.12: the swap saves **$1.34 per 1,000, 2.7 % of the pipeline's $50.69**. Four extra
confident errors per 689 questions is a bad price for 2.7 %. Worth remembering when
sequencing the remaining swaps: `text2sql` ($35.33) and `entity_extraction` ($13.87) hold
97 % of the bill, so they are where a model change is worth the risk of measuring.

**French, 643 questions, floor 2: HOLD more clearly still.**

| | correct | abstained | **wrong** | wrong, decidable classes |
|---|---:|---:|---:|---:|
| gpt-4o | 618 | 23 | 2 | **0** |
| gpt-5.6-luna | 630 | 6 | 7 | **5** |

Same shape as English, wider gap: +5 against a floor of 2, and `gpt-4o` makes **no**
confident error at all on the decidable classes in French (both of its errors are in the
unscored tail). Latency again a wash.

**The FR floor is 2 where the EN floor is 1**, and `gpt-4o` is a little less accurate in
French across the board. That is the documented EN/FR gap showing up in this task too, and
it means a French comparison tolerates more slack before it means anything.

**Running both languages is what turns the result from a count into a diagnosis.** Three of
Luna's failures reproduce in both:

| eval | question | truth | Luna |
|---|---|---|---|
| 2467 | "Which people died from a heart attack?" / "Quelles personnes sont mortes d'une crise cardiaque ?" | person | **death** |
| 2321 | "Documentaries" / "Documentaires" | movie | **genre** |
| 825 | the Gendarme de Saint-Tropez collection | (differs, see below) | wrong both ways |

Eval 2467 in both languages is the finding. It is not noise, it is not an ambiguous label,
and it is exactly the confusion this classifier exists to prevent: the cause of death is the
**filter**, the people are the answer, and the prompt gives that shape as a worked example.
Luna takes the filter for the answer in both languages; `gpt-4o` gets it right in both.
Together with the `-> genre` pair, the failure mode is systematic: **a weaker model
generalises "the words in the question" into "the type of the answer"**, which is the single
thing this task must not do.

**A ground-truth caveat the two runs expose, and it is new.** The same evaluation carries a
**different label in EN and FR on 5 of 622** shared questions (825, 948, 2179, 2323, 2457).
The labels come from two separate executions, so this is the pipeline's own EN/FR divergence
leaking into the ground truth. Half of Luna's raw errors land on those five. The verdict is
unaffected, because only one of them (825) sits in a decidable class and the FR gap is +5
against a floor of 2 with or without it, but any future reading of a small delta must check
whether it rests on one of these.

**Where to look next on this task, if it is worth revisiting:** the `-> genre` and
`-> death` errors all say the same thing, that the prompt's "a genre used to scope a search
is a filter, not the answer" guidance is not emphatic enough for a weaker model. That prompt
is inline in `text2sql.f_classify_result_entity`, not a hot-reloaded file, so testing a
rewrite means a code change and four bench runs, before and after in both languages. Given
the task is 2.7 % of the bill, that is a poor use of the next hour compared with benching
`entity_extraction` or `text2sql`.

**Three outcomes, never one accuracy number**, and this is the part that transfers to any
future classifier. *Correct*; *abstained*, where the caller falls back to the pre-existing
behaviour so nothing is lost; and *confidently wrong*, a different valid label, which is
the only outcome that overrides a query that may have been right. A model that abstains
more is not a model that errs more, and one accuracy figure hides exactly that difference.

**The label distribution decides how the result can be read.** `movie`, `person` and
`serie` carry 90 % of the classifier's ground truth, so answering "movie" every time
already scores 55.2 %. Eleven classes have fewer than 30 examples. The bench therefore
prints the majority baseline beside every score and refuses a percentage below
`--min-decidable`, listing those classes as counted-but-unscored instead. Same lesson as
the ChromaDB `lists` check that returned OK at 9 % on 23 documents: a proportion computed
on a handful of rows cannot discriminate, and a check that reports "fine" from too little
data is worse than no check.

**`--limit` samples round-robin across classes, rarest first, not off the top.** The
exports open on a long run of `movie` questions, so a head slice of 12 was twelve movies
and a perfect score. The stratified version surfaced something on its first 14-question
run that the head slice could never have reached, and it turned out to be about the
ground truth rather than about the model. See below.

**A passing execution proves its assertions were satisfied, NOT that its `result_entity`
is the label a human would pick.** That distinction is the one real weakness of harvesting
labels this way, and it showed up immediately. Evaluation 948 is the single `serie_image`
row in the EN set; its question is `Serie game of thrones`, which asks for nothing about
images, yet the execution ran against `T_WC_T2S_SERIE_IMAGE` and passed. `gpt-4o` answers
`serie`, which is defensible, and the bench scores it a confident error. So a
confident-error line on a class with n=1 is a prompt to go read the case, never a verdict
on the model. This is also why `--min-decidable` exists: at n=1 a single questionable
label is 100 % of the class.

**Bench artefacts are gitignored** (`checks/data/bench/`), for the same reason as the
execution exports: they carry the evaluation questions verbatim.

**Both benches preflight one call per model and abort before spending anything.** The
failure they guard against is not a crash but a plausible-looking report: the classifier
turns an exception into `""`, which scores as an abstention, and entity extraction turns
one into `{"error": ...}`, which `score()` maps to `None` and which therefore leaves the
DENOMINATOR rather than counting against the model. A configuration failing on every call
reads as "abstained a lot" in one and "scored: 0" in the other; failing on half reads as a
perfect record on the survivors. The entity bench now also states, at the top of its report
rather than at the bottom, how many questions were dropped and warns past a tenth.

**They do not run in the same places.** `bench-result-entity.py` reads its ground truth
from the execution exports on disk and needs **no database**, so it runs anywhere the repo
is checked out. `bench-entity-extraction.py` reads the bank from MariaDB and therefore only
runs where the database is reachable, which is not a developer laptop. Plan the entity work
on the VPS or behind a tunnel.

## The provider prompt cache decides the price of a GPT-6 model (PROMPT-CACHING-010)

Every OpenAI call now sends `prompt_cache_key = "t2s-<task label>"` through `extra_body`
(`OPENAI_PROMPT_CACHE_KEY=0` turns it off), and the usage logger records `cache_write_tokens`
beside `cached_tokens`, in the `Prompt cache (...)` message and in `llm_usage`. Why it matters:
from gpt-5.6 on, a cache miss is not an uncached token but a **cache write at 1.25x** the input
price, and the only retention is 30 minutes (`prompt_cache_options.ttl`, no 24 h option on GPT-6).
On the 25 K-token text2sql prefix, gpt-6-sol costs about $8 per 1,000 calls when the cache holds
and $34 to $41 when it misses: the whole saving of the GPT-6 line is the hit rate.

**Why gpt-6-sol missed, established 2026-09-29 (FASTAPI-TEXT2SQL-304).** From gpt-5.6 on,
OpenAI's default *implicit* cache writes its entry at the **end of the latest message**, which in
our requests is the varying question. A later request can only reuse it if the **whole prompt is
identical**; a new question never reads the 25.7 K static prefix and pays a full-prompt write at
1.25x. gpt-4o, on the older prefix-interval rule, reads 97-99 % whatever the question. OpenAI's
guide names the case ("a shared prefix is not always a cached prefix") and the remedy: an explicit
`prompt_cache_breakpoint` after the static content, with `prompt_cache_options.mode = "explicit"`.
`_openai_user_content` (text2sql.py) now sends, on gpt-5.6+ and when the prompt has a
`<!--CACHE_BOUNDARY-->`, a user message in two text parts, the static one carrying the breakpoint;
older models keep the plain string. Measured on Chat Completions: three new questions each read
25,729 tokens with 0 written; without it, two new questions wrote the full prompt twice.
`OPENAI_EXPLICIT_CACHE_BREAKPOINT=0` turns it off. The design note with the sources is
`t2s-backlog/gpt6-sol-prompt-cache-misses.md` in Nestor.

**What the earlier explanations got wrong, so nobody repeats them.** The "streaks", the
`max_completion_tokens` "effect" and the English/French "eviction" were all the same rule seen
through a flawed bench: it resent the same questions in the same order, so runs that re-sent
already-sent questions hit and runs that sent new ones missed. Tested 2026-09-29: a capped call
wrote, and the uncapped call on the same new prompt read 25,753 tokens; the cap plays no part.
`prompt_cache_key` changed nothing (OpenAI keeps it for accounting on 5.6+). Keep `{ui_language}`
and anything else that varies below the boundary: that part of the note still stands. Read the
hit rate of every campaign from the per-task table of phase 20 before reading its cost, and bench
the cache with NEW questions only.

**The evaluator now stops a run whose cache does not hold** (`PromptCacheGuard` in
`text2sql-eval/text2sql-eval.py`, 2026-09-28). After each stored execution it reads `llm_usage`; for every
cacheable task (>= 1,024 prompt tokens per call) it ignores the first 3 calls, then stops the run
with exit code 3 when fewer than 70 % of the last 20 calls read at least 90 % of their prompt from
cache. Rows already written are kept and the same command resumes. Replayed on the 2026-09-27
gpt-6-sol exports it stops at question 23 in both languages; on gpt-4o it never fires.
`CACHE_GUARD_MIN_HIT` (script) / `--cache-guard-min-hit` (evaluator), 0 disables it.

## An evaluation declares the path that must resolve it (FASTAPI-TEXT2SQL-257)

`complex_model_used` was an **observation**: it described what happened and could never
fail. Since -257 the bank declares, per question, which path *must* resolve it, in
`T_WC_T2S_EVALUATION.RESOLUTION_MODE`.

| value | meaning | verdict |
|---|---|---|
| `standard` | must resolve without escalation | escalation fired = **regression of the normal path**, even when the final answer is right |
| `complex` | cannot resolve without escalation | resolved without it = the assertion is too loose, or the question is easier than thought |
| `any` or NULL | no expectation | never judged |

**NULL is not `any` in disguise.** Both are judged the same way, which is not at all, but
only NULL lets you find what is still unqualified. Do not backfill the 1445 existing rows
for tidiness: NULL says "this question was never examined under this angle".

**The verdict stays out of `ASSERTIONS_TOTAL_SCORE`, and that is the important design
decision.** That score is the one thing that makes a campaign comparable to the previous
one. Folding a new failure reason into it would make 1.1.19 incomparable with 1.1.18,
which is precisely the mistake this whole line of work exists to avoid. The mode verdict
lives in its own column, `RESOLUTION_MODE_RESPECTED`, and the end-of-run recap prints the
escalation rate per declared mode beside the assertion score. Two measures, two readings.

**A `complex` evaluation tests the model, not the database.** *Groundhog Day* is not found
by a join; it is named by the LLM from its parametric memory and then looked up. So its
assertion must bear on the resolved title or id, never on a row set that depends on the
read-model, and it is inherently unstable across a model swap. That is a feature for the
GPT-5.6 comparison: descriptive questions are the most discriminating ground available,
where gpt-4o already plateaus above 96 % on factual ones.

**Why two extra columns shipped with it.** The verdict is computed on what the campaign
records, and the recording was a quarter short. Measured 2026-09-14 on `001.001.018`:
`complex_model_used` true on **46** executions, `COMPLEX_QUESTION_PROCESSING_TIME` positive
on **34**. The missing 12 go through the direct scalar answer, which banks into
`answer_single_value_processing_time`. Both are now persisted columns, so a campaign is
sliced in SQL and never by reopening `JSON_RESULT`.

**The schema change is applied since 2026-09-20 at 13:24:33**, and the output sits in
`maintenance/eval-mode-de-resolution-20260920.txt`. All five columns exist. Two of them,
`T_WC_T2S_EVALUATION.RESOLUTION_MODE` and `T_WC_T2S_EVALUATION_EXECUTION.COMPLEX_MODEL_USED`,
answered `ERROR 1060 Duplicate column name`, so they had been added by an earlier, unrecorded
run: this file was never as unapplied as its header claimed. The run used `--force`, so the
statements after each error still went through.

**And the figure quoted just above no longer reproduces.** Its own verification query, rerun on
2026-09-20 over the same campaign `001.001.018` with the same `DELETED = 0`, returns **26
escalations seen by the JSON against 15 seen by the time column**, on 1704 rows, where
2026-09-14 recorded 46 against 34. The gap the columns exist to close is still there, and wider
in proportion; the population underneath moved, which points at rows retired or re-executed
since. Both measurements are kept, dated, because nothing here says which population is the
right one to quote.

### The cause of the escalation, not only its existence (FASTAPI-TEXT2SQL-271)

-257 answers *did this row escalate, and was it allowed to*. It cannot answer *why*, and the
three causes that raise `requires_complex_resolution` do not carry the same verdict at all:
`descriptive_identification` is the dispositif doing its job, `requires_complex_resolution` is
Text2SQL admitting defeat, `unbacked_entity_literal` is a hallucination being caught. Two of
them used to reach `first_pass_failure_code` under the **same** label, distinguishable only by
the free-text `first_pass_failure_reason`, which no campaign can group by. `main.py` now sets
`complex_resolution_code` at each point of decision, and `descriptive_identification` is a value
of the closed vocabulary in its own right. Rows written before that carry the mixed label, and
it was not a harmless one: measured 2026-09-17 on the 505 local logs, **35** retries filed under
`requires_complex_resolution` and all 35 were descriptive routings, none from Text2SQL. The
shared label carried the name of the case never observed, which does not look like an error, it
looks like a statistic.

Two columns follow, `FIRST_PASS_FAILURE_CODE` and `QUERY_MODE`, in
`maintenance/eval-executions-cause-escalade.sql`, not applied either.

**`QUERY_MODE` must be read from `first_pass_entity_extraction`, never from
`entity_extraction`.** On a retried row the second describes the inner pass over the *rewritten*
question, so it reads `named_entity_query`: measured 2026-09-17 on the 505 local logs, 30 rows
classified `descriptive_identification` in the first pass, of which 27 show `named_entity_query`
in `entity_extraction` and 3 show nothing. Reading the convenient field would have made the
campaign report almost no descriptive questions at all, which is the failure mode this whole
column exists to prevent.

**`FIRST_PASS_FAILURE_CODE` NULL with `COMPLEX_MODEL_USED = 1` is a cause, not a gap.** It is
the signature of the direct scalar answer, the only path that escalates without going through
the retry helper. And `QUERY_MODE` is the only denominator available, since the failure code
exists on retried rows alone: a rate of "descriptive questions that escalated" needs a
classification on every row, escalated or not.

## The reasoning-family block in `text2sql.py` (FASTAPI-TEXT2SQL-231, -274)

`README.md` states the user-visible rule: reasoning models reject `temperature` and get
`reasoning_effort` instead, `_openai_sampling_kwargs` builds that half of the call per family,
`gpt-4o` is unchanged, and effort is the real cost knob. What it cannot say is how the block fails
when you extend it.

**There is no allowlist, so an undeclared family does not bounce, it leaves.** `_call_chat_llm`
routes on the prefix, anything starting with `gpt-` goes to OpenAI, and the five `llm_model_*`
fields of `Text2SQLRequest` are `Optional[str]` with no validator. Before -274,
`llm_model_text2sql: "gpt-6-astra"` was accepted, sent with `temperature=0` attached, and answered
400; on a route that tolerates the parameter it would instead have run at the model's default
effort with nobody able to read or set it. A family that is not declared here is a family that
spends silently.

**The four things a new family needs**, all in the same block and all four or none: the prefix in
`_REASONING_MODEL_PREFIXES` (or `temperature` stays attached), a row in `_EFFORT_BY_FAMILY` (or
the effort resolution falls back to the o-series vocabulary), a rung for every `cache_label` in
`_DEFAULT_EFFORT_TIER`, and an endpoint decision via `_CHAT_COMPLETIONS_REASONING_PREFIXES`.

**Note the indirection**: `_DEFAULT_EFFORT_TIER` holds a **tier name**, not a provider value, and
`_EFFORT_BY_FAMILY` turns it into one, because the families share no vocabulary (`minimal` was a
GPT-5.0-era value and exists nowhere now). **GPT-6 has no `none` rung**, and that one cell decides
the bill: copying the GPT-5 row would 400 on every call, while "fixing" it to `medium` would
quietly buy a thinking budget on the three tasks that fire on 100 % of requests. Only the two
rungs this pipeline selects are declared, because a rung nobody selects is a rung nobody has
measured. `vision_identification` sits in the table at the cheapest rung ahead of the task itself
(-114), so the family table is complete the day it lands.

**Four things NOT to assume.**

- **The `responses.create` branch is restricted to the o-series.** GPT-5.x and GPT-6 both go
  through `chat.completions`, which is also where the prompt-cache accounting this pipeline
  reports was measured; the two routes name their usage fields differently, so a campaign compared
  against the `gpt-4o` baseline needs both on the same route.
- **The o-series was never getting its effort**, a defect found while deciding that branch.
  `responses.create` takes `reasoning={"effort": "low"}`, not the flat `reasoning_effort="low"` of
  `chat.completions`. The flat form was passed, rejected, and swallowed by the `try/except` that
  falls back, so the o-series reached the fallback on **every** call and ran at its default
  effort. `_as_responses_api_kwargs` now translates. Neither GPT-5.x nor GPT-6 uses that path.
- **The cached prefix is 24.2 K tokens, not the 14.8 K measured in June.** Any cost estimate
  starting from the old figure is a third too low. Full protocol and figures:
  `%USERPROFILE%/Nestor/projets/t2s-backlog/topics/prompt-caching.md` PROMPT-CACHING-009.
- **Function tools combined with `reasoning_effort` are refused for `gpt-5.6-sol`** on
  `/v1/chat/completions`. It does not bite today, since this pipeline uses neither tools nor
  `response_format`. It will the moment someone adds structured outputs.

**Offline check:** `uv run checks/verif-274.py` (31 cases, no API and no database). It reads the
family block out of `text2sql.py` and executes it in isolation, so it runs on a machine without
the full stack.

**Not done, and deliberately so: no evaluation campaign has been run on `gpt-6-astra`.** The
family is selectable and its cache behaviour is measured; whether its SQL is as good as
`gpt-4o`'s is unknown. `T_WC_T2S_EVALUATION_EXECUTION` already carries the model columns, so the
comparison is mechanical when someone wants to spend the run.

## Adding an indicator to the response

The measurement chain is already generic, and knowing that saves most of the work.
`text2sql-eval/text2sql-eval.py` stores the **entire** HTTP response body in
`T_WC_T2S_EVALUATION_EXECUTION.JSON_RESULT`, and the export phase copies that JSON verbatim
into `api_output` in `/shared/evaluation_execution/`. So:

1. **Add the field to `Text2SQLResponse` and populate it.** That alone puts it in the API
   answer, in the database and in the export. Give it a default so the early-return response
   sites (cache miss, bare-identifier fast path, complex-question retry) keep working.
2. **Add a dedicated column only if you need to aggregate it in SQL.** The columns are a
   duplicate of what `JSON_RESULT` already holds, kept so a campaign can be sliced without
   `JSON_EXTRACT` on every row (the PHP graphs under `text2sql-eval/lib/` rely on them). That step is
   four edits, not one: [doc/sql/T2S_EVALUATION-tables.sql](sql/T2S_EVALUATION-tables.sql)
   for the reference DDL, a migration under [maintenance/](../maintenance/) for the live table,
   the write in `text2sql-eval/text2sql-eval.py`, and the `timings` block of the export in that same
   file. That fourth one is a hand-kept list and does **not** inherit from `JSON_RESULT` the
   way `api_output` does, so forgetting it is invisible: the export keeps writing, simply
   without the column. It happened, and 1.1.18 exports described a five-step pipeline while
   six columns existed. `text2sql-eval/README.md` shows the block, so it drifts too.
3. **Document it in `README.md`**, which describes the response in three separate places: the
   example JSON, the detailed field list and the summary list. All three drift on their own.

Rows written before an indicator existed keep `NULL`. That is the point: `NULL` says "not
measured then", `0` would claim "measured at zero".

A new numeric field is rounded on the way out by its name (next section): a timing ending in
`_time` gets the millisecond, a distance four decimals, anything else two. Check that the
default suits it, and add a rule to `response_rounding.py` if it does not.

## Replaying the usage measurements: `analyze-usage-logs.py`

The HARNESS-BRICKS tickets (Nestor, `projets/t2s-backlog/topics/harness-bricks.md`) were first measured on 2026-10-10 by throwaway scripts. This script is those scripts kept, so the figures can be rebuilt after any deployment or campaign. It reads, never writes, and touches no database.

```bash
uv run analyze-usage-logs.py                     # defaults below, from the repo root, PC or VPS clone
uv run analyze-usage-logs.py --since 20261001    # only the recent logs
uv run analyze-usage-logs.py --eval-version 001.001.018
```

- **Inputs.** `../shared_data/fastapi-text2sql/logs` (loose files plus `archive/*.tar.gz`, deduplicated by file name because the month being archived sits in both) and `../shared_data/text2sql-eval/evaluation_execution` (one folder per run, latest execution kept per evaluation). The same relative layout holds on the PC and in `~/docker/fastapi-text2sql-<colour>`.
- **Outputs**, in `../shared_data/fastapi-text2sql/reports/` by default: `api-usage-YYYYMMDD.html` (caches -003/-004a, `answer_single_value` -010, SQL execution feedback and escalation outputs -009, answer-entity guard -008, retry cache guards -011, failures by cause -001) and `vision-evidence-YYYYMMDD.html` (what the vision model read, the candidates, the identity and credits checks, field coverage of `vision_evidence`, the last 60 image requests with thumbnails from `uploads/vision/` while the deposit lasts). Inline CSS, no script, in the style of data-monitoring.
- **Campaign versus production** is `retrieve_from_cache`: the evaluator sends `false`, the clients `true`. A test typed by hand in a front counts as production; nothing in a log can tell it apart.
- **Message prefixes are the contract.** The guard, `answer_single_value` and escalation counts match the start of messages written by `main.py` (`Answer-entity guard: ...`, `SQL query returned a single-cell result with value 0`, `Complex question resolution output: `). Rewording one of those messages silently zeroes its section: grep the script before changing the text.
- **`raw_identification`** only appears in logs written by an API that carries the patch. Until then the vision page says so, and its normalization-loss table stays empty.
