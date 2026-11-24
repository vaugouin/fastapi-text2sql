# Bare identifiers (fast path)

## Sub-features
- A question that is only an identifier is answered by a direct lookup: no LLM call, no cache write, no cost. Measured on 2026-11-24: `tt0033467` (Citizen Kane), `nm0000033` (Alfred Hitchcock), Wikidata `Q25188` (Inception) each return one row.
- Also the target of the complex retry when it identifies a work by its credits (`complex_identity_check` decision `picked`): the retry queries the winner's IMDb id through this path.

## How to get to it
`POST /search/text2sql` with `{"question": "tt0033467"}`.

## Driving it
- `verify_api.py ask tt0033467` (one row, Citizen Kane, `llm_cost` null).
- Part of `doctor` and of `smoke --free`.

## Gotchas
- The best probe for a redeploy without a version bump: free, instant, and it exercises the response model, so a new response field shows up here.
