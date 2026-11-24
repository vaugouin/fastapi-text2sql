# Result representations and intent

## Sub-features
- `result_kind` (`entity_rows`, `count`, `scalar`, ...), `representation` (`card-grid`, `ranked-bars`, `number-card`, `value-cards`, `timeline`, `sequence-strip`, `trend-columns`...), `representation_options` (chips), `summary_facts` (caption and spoken line), `result_columns` (with `ordered` and `focus` marks), `intent` (task such as `list`, `rank`, `compare`, `value`).
- Two consumers render them: voice-agent and t2s-front. The contract table is in `README.md`, *Result representations*.

## How to get to it
Any search; the shape of the question drives it ("how many" gives a count, "the 5 longest" a ranking).

## Driving it
- `verify_api.py ask "<question>"` prints `result_kind` and `representation`.
- Probes in `smoke.json`: a count (`number-card`), a ranking (`ranked-bars`), a list (`card-grid`).

## Gotchas
- A classifier change can flip a hundred evaluations: the census in `checks/census-result-shape.py` is the real check; this CLI only spot-checks.
