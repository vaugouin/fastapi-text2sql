# Pagination, homonyms, dropped clauses

## Sub-features
- `page` and `rows_per_page` (default 50); `question_hashed` replays a processed question for the next page without re-running the LLM stages. Model-written `LIMIT` and `OFFSET` are stripped; a smaller model-defined limit is kept (`llm_defined_limit`).
- `name_ambiguity`: present when an exact name match returns several homonyms (Steve McQueen, Le Bonheur); candidates ordered oldest first, with discriminators. Page 1 only. The API states the fact; the client decides to ask "which one?".
- `dropped_clause`: names the part of the question the SQL does not implement (a filter with no placeholder).

## How to get to it
"Movies called Le Bonheur", "Steve McQueen films"; any long list for pagination.

## Driving it
- `verify_api.py ask "Movies called Le Bonheur"` then read `name_ambiguity` in the evidence JSON.
- `verify_api.py ask "<question>" --extra '{"page": 2}'` for a second page.

## Gotchas
- A non-empty `dropped_clause` means the answer is wider than the question: a correct-looking list can still be wrong.
