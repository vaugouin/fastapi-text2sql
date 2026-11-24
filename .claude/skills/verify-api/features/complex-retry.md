# Stronger-model retry and rescues

## Sub-features
- When the first pass fails or returns an empty page under suspicion (no entity extracted, person-role collapse, generic substitution, SQL failure), the question is rewritten by the stronger model and run again; `complex_model_used` true, `first_pass_*` fields describe the first attempt, `complex_retry_question` the rewrite.
- Rescues before the stronger model: no-entity rescue, co-constrained title rescue, co-constrained person rescue (`no_entity_rescue_outcome`, `co_constraint_rescue_outcome`).
- `sql_timeout` (60 s cap) is never retried.

## How to get to it
Questions that describe rather than name ("the film where a man wakes up every day on the same day"), or that name a work by a nickname.

## Driving it
- `verify_api.py ask "<descriptive question>" --trace`, then read `complex_model_used`, `first_pass_failure_code`, the rescue outcomes and the trace.

## Gotchas
- Costs more (two passes, a stronger model). One question at a time.
- A retried request writes two log files on the server; the response you hold is the outer one, which carries everything.
