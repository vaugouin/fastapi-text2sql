# AGENTS.md - checks/

Offline checks and benches of the API's internals. Human-facing description and the per-script table: @README.md. Repository rules: `../AGENTS.md`.

- Every script here imports this repository's modules or reads its files; that is the criterion for living here rather than in the evaluator repository `text2sql-eval` (an HTTP client of the API). A new script that only calls the API over HTTP, or only touches the evaluation bank, belongs in `text2sql-eval`.
- Run from the repository root: `uv run checks/<script>.py`. The scripts put the repository root on `sys.path` with `dirname(dirname(__file__))`, so they must stay one level deep.
- Evaluator code is reached through the sibling folder `../text2sql-eval` (same layout under `%USERPROFILE%/Code` and `~/docker`); execution exports through `../shared_data/text2sql-eval` or `$TEXT2SQL_EVAL_EXPORT_DIR`.
- `data/bench/` is gitignored on purpose: it carries the evaluation questions verbatim.
- On the VPS, the Docker launchers (`eval-309.sh`, `bench-jev.sh`) mount the API checkout (`~/docker/fastapi-text2sql-<colour>`): `git pull` it first; pulling does not restart the API.
- One-off scripts whose ticket is closed move to `checks/archive/`.
