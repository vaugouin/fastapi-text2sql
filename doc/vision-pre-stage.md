# The vision pre-stage

What breaks when you edit the image path of `/search/text2sql` (FASTAPI-TEXT2SQL-114 and its follow-ups). The client contract is in [../README.md](../README.md).

Moved out of the root `AGENTS.md` on 2026-10-31 so that file keeps only the rules. A section name in italics refers to this document, to its siblings in `doc/` (`pipeline-internals.md`, `llm-tasks-and-costs.md`, `vision-pre-stage.md`), or to the rules left in [../AGENTS.md](../AGENTS.md) (the numbered *Gotchas* among them).

## The vision pre-stage: an image becomes a question (FASTAPI-TEXT2SQL-114)

`README.md` documents what a client sends and gets back: the optional `image_ref`, the
`llm_model_vision` selector, and the five response fields. Below is only what breaks when you
edit this path.

**It is a PRE-STAGE, not a recursive re-entry, and that is the whole design.** The
complex-question retry re-enters `search_text2sql`, which is why it has to merge and renumber
two message arrays (`main.py`) and why it writes **two** log files per request (Gotcha #8d).
The vision path composes the question in place and falls through to the ordinary pipeline: one
message counter, **one** log file, and nothing new to teach whatever counts questions over
`logs/`. Do not "harmonise" it with the retry helper.

**The model identifies; the CODE composes the question.** `f_identify_from_image` returns
`items[]` and never a question, and `compose_vision_question` builds the question from those
items. That split is what makes the recognition cache sound: the identification of an image
does not depend on the question asked about it, so it is stored under the MD5 of the bytes and
reused on later turns. If the model composed the question, a cached turn and a fresh turn
would produce **different questions for the same photo**, and the divergence would only show
up on the second turn in production. `checks/verif-114.py` asserts the invariant directly: the
identification round-tripped through the cache composes the same question as the fresh one.

**Two shapes of composition, and the second one is the one to protect.** A lone photo goes
through `f_build_retry_question_from_reasoning`, the same deterministic composer the
complex-question retry uses. A photo carrying a question keeps the question and has the entity
substituted into it (`who directed this film?` -> `who directed the movie Blade Runner
(1982)?`). Flattening the second case into an entity card returns the film and answers
nothing, which is the defect recorded as **-263**, and the vision prompt inherits that rule in
so many words.

**A question about the people IN the image is answered by the faces, not by the cast**
(FASTAPI-TEXT2SQL-281, arbitrage of 2026-09-20, explicitly "let us try it and see"). The vision
task declares the people it recognises as `person` items beside the `movie` item, and
`compose_vision_question` prefers them when `question_targets_the_people_shown()` fires. Measured
before the change: "who are the actors on this picture?" returned the 32 names of *The Big
Sleep*, Dorothy Malone at rank 11, while the model had already read and named both visible faces
in `hints.faces` and the pipeline threw that away.

Three properties of that branch are worth knowing before touching it. It is **gated on a role
verb being absent**, so "who directed this?" is never answered from faces, the director not being
in the frame; the first draft of that list contained the stem `film`, which would have disabled
the whole feature in French, since "qui sont les acteurs de ce film ?" contains it. It **falls
back to the cast when no face was read**, so the behaviour is not uniform and that is the thing
to watch in use. And it is what finally answers a **portrait with no work in it**, which had no
answer at all before: with only `person` items, the composer builds `Person X`.

**The cap is applied per kind, and that is not cosmetic.** `select_vision_candidates` keeps up to
`VISION_MAX_CANDIDATES` works AND up to as many people. A single cap over a confidence-sorted
list would let five recognised faces evict the film, and the photo would then be answered as if
it showed nobody's film.

**Three outcomes never reach the catalogue**, and none of them is an error: a question about
the pixels (`about_image`, answered from the image), an image with nothing of cinema in it,
and an image the model could not read. All three return an `answer`, an empty `result`, no SQL
and `error: ""`, which is the `authoritative_empty` shape of **-221**: an affirmative
emptiness. Do not turn them into errors to make them easier to spot.

**`question_targets_the_image()` is a may-call gate, not a verdict.** It decides whether the
vision model is called on an image the cache already holds, because a question about the
pixels cannot be answered from a stored identification. When it is wrong in one direction it
costs one cached turn; it cannot produce a wrong answer, because the model has the final word
through `about_image` whenever it is actually called. Add markers to it freely; do not build a
decision on it.

**The two confidence constants are PROVISIONAL and unmeasured.** `VISION_CONFIDENCE_DOMINANT`
(0.70) and `VISION_CONFIDENCE_MARGIN` (0.20) decide whether one candidate opens its entry with
the alternative reported beside it, or whether all candidates are searched so the client can
ask which one is meant (rule VOICE-AGENT-093). The ticket is explicit that the threshold is
settled **on the twenty-image bench** and not guessed; that bench is FASTAPI-TEXT2SQL-277 and
it does not exist yet. They are named constants so the measurement has somewhere to land.

**`gpt-6-astra` is the default here, and it is the only default in this repository that is not
`gpt-4o`.** It is the model the feature was tried on, it is the one the ~4 cents a photo figure
was computed from, and its family is declared in the reasoning block (**-274**) with
`vision_identification` at the cheapest rung, `reasoning_effort: "low"`. Raise the rung only if
recognition weakens on the bench.

**`_call_vision_llm` is OpenAI only, deliberately.** It is not folded into `_call_chat_llm`
because that dispatcher takes a string and every provider encodes an image differently.
Anthropic and Gemini both read images and neither is wired: an untested branch that formats
bytes for a provider nobody has exercised is a liability. A non-OpenAI model name raises an
error that says exactly that.

**Structured outputs degrade once.** The contract is sent as a strict `json_schema`, which
OpenAI documents as compatible with `reasoning_effort` on `chat.completions`. On a refusal
`_VISION_STRUCTURED_OUTPUTS_AVAILABLE` flips and the rest of the process uses the plain-JSON
contract the other five tasks use, cleaned and validated by `json_guardrails`. The fallback is
there because a neighbouring combination IS refused (function tools with `reasoning_effort` on
gpt-5.6-sol, see *The reasoning-family block*) and because this repository has never sent a
`response_format` to the live API before.

### The identity check: namesakes of the same title and year (FASTAPI-TEXT2SQL-307)

Title plus year is not a unique key. On 2026-09-30 a still from Scorsese's *Taxi Driver*,
recognised at 0.98, returned two cards, because the Turkish *Taksi Şoförü* (1976) carries the
English title "Taxi Driver" on TMDb. The harvest of that day counts 7,788 such movie groups,
433 of them with a film of 10,000 votes or more (`text2sql-eval/harvest-title-year-homonyms-20260930.txt`).

- **The prompt** asks, for every `movie` / `serie` item, a `known_credits` block (directors or
  creators, up to three leads, original title, original language): what the model KNOWS, never
  a `person` item. Required in the strict schema, emitted empty for other types, dropped by
  `_normalize_vision_items` when empty.
- **The check** runs in the pre-stage when one work dominates (`identity_check_applies`) and the
  question is not answered from faces. `_fetch_vision_identity_candidates` (main.py) lists the
  rows sharing the title (the three title columns the generated SQL compares) and the exact year,
  with their makers and cast; `vision_identity.pick_vision_identity` scores them against the
  faces read and the known credits. It only chooses among the rows, never returns zero, and
  never uses popularity.
- **Photo alone, one winner**: the composed question becomes the winner's `ID_IMDB`, answered by
  the bare-identifier fast path (-137) with no LLM call, and the answer names the work
  ("Here is the movie Taxi Driver (1976), directed by Martin Scorsese.").
  **Photo plus question**: the substituted phrase carries the credit that decided
  ("the movie Taxi Driver (1976) directed by Martin Scorsese").
- **Undecided** (no score, or a tie): the composed question is unchanged and all rows come back.
- Traced in `vision_evidence.identity_check` (decision, discriminators, candidates, scores).
- Offline check: `uv run checks/test-vision-homonyms.py`.
- **Shipped on 1.1.19 without a version bump** (Philippe, 2026-09-30), so the version scope of
  the recognition cache does not retire the rows written before it. `vision_cache.predates_known_credits`
  spots them (a movie or serie item without the `known_credits` key) and the pre-stage reads
  the image again once, the write then replacing the row; if the image is already purged, the
  old identification is served as before. `identification_payload` stamps an empty block on
  every new row, so a model that omits it is not re-read on every request.
- Capability probe, since `api_version` does not move: a vision response carrying
  `vision_evidence.identity_check` is the new code.

### The recognition cache (`vision_cache.py`, `T_WC_T2S_VISION_CACHE`)

No tier of `T_WC_T2S_CACHE` indexes bytes: its key is the question. Without this module the
image path caches the **cheap** half of the work and repays the expensive one, about 4 cents,
on every re-deposit. The key costs nothing because it already exists: `f_getuploadfilename`
hashes the raw bytes into the deposit filename, so the same photo yields a new timestamp and
the **same** MD5.

- **Its own table**, not a column on `T_WC_T2S_CACHE`, whose contract is question to SQL.
- **Scoped by formatted API version**, because the prompt is hot-reloaded: without the scope a
  prompt correction shipped with no bump would keep serving identifications made by the old
  one.
- **Only the question-independent half is stored** (`hints`, `items`, `authoritative_empty`,
  `justification`). `about_image` and `image_answer` are dropped by
  `vision_cache.identification_payload`, and that function is the contract: adding a
  question-dependent field to it makes the cache serve yesterday's answer to today's question.
- **An `authoritative_empty` IS cached**, unlike the empty SQL result of Gotcha #8b. A photo of
  a meal will still be a photo of a meal tomorrow.
- **`retrieve_from_cache` and `store_to_cache` govern it** like every other tier, which is how
  a model comparison switches it off without a new flag.
- **The 30-day image purge does not invalidate a row**: the key is the fingerprint of the
  bytes, not the file. The row then serves the identification and never the pixels.
- The migration is `maintenance/vision-recognition-cache.sql`, **run in production on
  2026-09-20 at 12:53:25**; its output sits beside it in
  `maintenance/vision-recognition-cache-20260920.txt` and matches the DDL column for column and
  index for index. The graceful degradation stays, for the day a deployment points at another
  database: `vision_cache` flips to disabled on the first `Table doesn't exist` and the vision
  path works, uncached. **That flag never flips back**, so a process that met the missing table
  once stays uncached until it is restarted.

**Offline check:** `uv run checks/verif-114.py` (62 cases, no API, no database and no image). It
covers everything deterministic on this path: the may-call gate, the confidence rule, both
shapes of composition, the cache round-trip invariant, the guardrail, the `image_ref` refusals
and the Pydantic contract the two front clients depend on.

**Before editing `data/vision_identification.md`, read [data/AGENTS.md](../data/AGENTS.md).** Three
of its rules have a twin in `complex_question.md`; they agree on the motive and disagree on the
instruction, because the two tasks fill opposite fields. The confidence guard is the one place
where letting them drift apart is dangerous rather than merely untidy.

**Not done, and deliberately so: no bench, no evaluation campaign.** The twenty-image bench of
FASTAPI-TEXT2SQL-277 does not exist, so recognition quality is unmeasured, the two confidence
constants are unmeasured, and `T_WC_T2S_EVALUATION_EXECUTION` still has no column for a sixth
model. Everything above is verified offline or by reading; nothing here was run against a live
model.

## `T_WC_T2S_VISION_CACHE`

- `T_WC_T2S_VISION_CACHE` : the recognition cache of the vision path, keys `IMAGE_MD5` (the
  fingerprint of the deposited bytes, read off the `image_ref`) and `API_VERSION`
  (`XXX.YYY.ZZZ`), payload `IDENTIFICATION` (JSON), plus `IMAGE_REF`, `VISION_MODEL`,
  `AUTHORITATIVE_EMPTY`, `VISION_IDENTIFICATION_PROCESSING_TIME`, `DELETED` and the two
  timestamps. Read and written by [vision_cache.py](../vision_cache.py) with graceful
  degradation: while the table is absent the whole module is a silent miss. Created by
  `maintenance/vision-recognition-cache.sql`, run in production 2026-09-20.
