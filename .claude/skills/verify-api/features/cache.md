# Cache tiers and the feedback bypass

## Sub-features
- Tiers: exact question, anonymized question, anonymized-question embedding, keyed by the formatted version (`XXX.YYY.ZZZ`) and `UI_LANGUAGE`. Response flags: `cached_exact_question`, `cached_anonymized_question`, `cached_anonymized_question_embedding` (the CLI reports `cache_hit`).
- An empty result is never cached.
- A negative feedback (`new` or `analysed`) on a question turns every cache read and write off for it (`cache_bypassed_by_feedback`).
- The provider prompt cache (OpenAI) is a different thing: it lowers the cost of a fresh pipeline run, visible in the `Prompt cache (...)` lines of the trace.

## How to get to it
`retrieve_from_cache: true` reads; `store_to_cache: true` writes. Fronts use both.

## Driving it
- `verify_api.py ask "<question>" --cache`: reads the cache (writes stay off). Compare with the same question without `--cache` to see whether a stale cached answer hides a fix.

## Gotchas
- After a prompt or config change shipped without a version bump, cache rows of the current version may still answer the old way: verify with cache read off.
- The CLI never writes to the cache. To test a write path, ask Philippe; it changes what users see.
