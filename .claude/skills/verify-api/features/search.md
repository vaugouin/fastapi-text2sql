# Question to SQL, the core pipeline

## Sub-features
- `POST /search/text2sql` with `{"question", "ui_language", "retrieve_from_cache", "store_to_cache", "page", "rows_per_page"}`; the OpenAI key travels per request in `X-OpenAI-Key` (no key on the server: without it, a cache miss answers 401 `openai_key_required`).
- Stages, in the `messages` trace: entity extraction (question anonymized into placeholders such as `{{Person_name1}}`), result-entity classification and entity resolution forked in parallel with SQL generation, resolution (regex, closed vocabulary, RapidFuzz or embeddings, raw fallback), SQL guard and read-only execution with pagination, intent, representation.
- Response fields read first: `error`, `error_code`, `result` (a list of `{"index", "data"}`), `sql_query`, `justification`, `answer`, `result_kind`, `representation`, `result_entity`, `llm_cost`, `total_processing_time`, `llm_usage`, `messages`.

## How to get to it
Any front (t2s-front `/en/`, `/fr/`, voice-agent, MCP) ends here. A user report names a question: replay that exact wording, in the same language.

## Driving it
- `verify_api.py ask "<question>" [--lang fr] [--trace]`: cache read and write off by default, so the whole pipeline runs; `--trace` prints every step, including the resolved entities (`{{Person_name1}} -> Alfred Hitchcock (rapidfuzz, ...)`) and the prompt-cache lines.
- `--extra '{"rows_per_page": 10}'` merges any request field.
- Evidence: the full response JSON under `.verify-api/`.

## Gotchas
- Cost: about 0.013 USD per question on a warm provider prompt cache, about 0.13 USD for the first question after a restart (the prompt cache is written). Do not loop over dozens of paid questions without saying so.
- Write off is deliberate: a verification must never seed `T_WC_T2S_CACHE` with an answer nobody checked.
- A plausible answer is not a correct one: read the first rows and the SQL, not only `error`. Example found on 2026-11-24: "the 5 longest films directed by Christopher Nolan" ranks an anthology of shorts first.
- To check the rows against the truth, prefer the entity endpoints or a `text2sql-eval` assertion over your own memory of the films.
