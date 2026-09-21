#!/bin/bash
#
# Build and run the Jev answer-entity bench (FASTAPI-TEXT2SQL-282) on the VPS.
#
# WHAT THIS MEASURES, IN ONE PARAGRAPH
# The answer-entity classifier decides, from the ORIGINAL question, what kind of thing the
# result rows should be, and it is AUTHORITATIVE over the text-to-SQL model's own
# result_entity. It has three outcomes and only one is dangerous: an abstention makes the
# caller keep the text-to-SQL answer type, which is the pre-existing behaviour and costs
# nothing, while a confidently wrong answer overrides a possibly-correct query. Jev has no
# native abstention, so this bench synthesises one from `confidence` and sweeps the
# threshold instead of picking one. Read the sweep, never a headline accuracy.
#
# CODE FROM THE CHECKOUT, KEY FROM THE EVALUATOR FOLDER
# ~/docker/text2sql-eval holds the Jev key in its .env, but it is a hand-made copy of the
# eval/ CONTENTS, not a git checkout, and AGENTS.md already records that its .py files
# drift silently from the repository. So this script takes the two bench files from a real
# checkout and only the env file from there. Nothing to copy by hand, nothing to drift.
# To run the flat copy anyway, set CODE_HOME=$EVAL_HOME; the mount below then makes its
# layout look like a checkout to the bench, see the next paragraph.
#
# THE FLAT COPY IS A TRAP, AND THE MOUNT IS WHAT DEFUSES IT
# The bench derives the repo root from its own location and reads the allowed vocabulary
# out of main.py there, deliberately, so an entity added to the application cannot go
# silently missing from the bench. Run from a flat folder, that lookup resolves to /main.py
# and finds nothing. Rather than relax the script, the container rebuilds the LAYOUT it
# expects: the code is mounted at /app/eval and main.py at /app/main.py, whatever the host
# arrangement. One read-only file, and it stays the single source of truth for the labels.
#
# INDEPENDENT OF BLUE AND GREEN
# The image shares nothing with the deployments: not their image, not their env file, not
# their network, no running API, no MariaDB and no ChromaDB. Only that one main.py is read
# from a checkout.
#
# Usage:
#   ./bench-jev.sh --dry-run          # no key, no network: layout, vocabulary, truth, payload
#   ./bench-jev.sh                    # 100 questions against the floor measured 2026-09-21
#   LIMIT=0 ./bench-jev.sh            # the whole verified set
#   LANG_CODE=fr ./bench-jev.sh
# Any extra argument is passed straight through to the Python bench.

set -u

EVAL_HOME=${EVAL_HOME:-$HOME/docker/text2sql-eval}
SHARED_DIR=${SHARED_DIR:-$HOME/docker/shared_data/text2sql-eval}
# Where the bench and main.py are read from. Green carries 1.1.19; point this at blue once
# blue is the newer colour.
API_HOME=${API_HOME:-$HOME/docker/fastapi-text2sql-green}
CODE_HOME=${CODE_HOME:-$API_HOME/eval}
ENV_FILE=${ENV_FILE:-$EVAL_HOME/.env}
IMAGE=${IMAGE:-t2s-bench-jev}

RUN=${RUN:-001.001.018}
LANG_CODE=${LANG_CODE:-en}
# The whole verified set by default, and NOT a sample. --limit triggers stratified
# sampling, which flattens the classes: `movie` falls from 55 % of the corpus to 16 % of a
# 100-question sample. That answers "how does it behave class by class", never "what will
# it do in production", and it moves the comparison bar with it (see COMPARE below). The
# full pass costs about 48 seconds, so there is little reason to sample at all.
LIMIT=${LIMIT:-0}
MODEL=${MODEL:-jev-latest}
# gpt-4o's confident-error rate on the FULL verified set, measured 2026-09-21: 2 of 688 on
# one side, 1 on the other. A percentage, not a count. On a stratified sample the same
# configuration scores 1 to 2 per 100, so this number does not apply there.
COMPARE=${COMPARE:-0.3}
COMPARE_DEFAULT=0.3
OUT=${OUT:-/shared/bench-jev-$LANG_CODE.json}

fail() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$CODE_HOME/bench-result-entity-jev.py" ] || fail \
    "no bench-result-entity-jev.py in $CODE_HOME.
     It landed in the repository after the last deployment, so: cd $API_HOME && git pull"
[ -f "$CODE_HOME/bench-result-entity.py" ] || fail \
    "no bench-result-entity.py in $CODE_HOME; the Jev bench reuses its ground-truth and
     vocabulary loaders rather than copying them."
[ -f "$CODE_HOME/Dockerfile.jev" ] || fail "no Dockerfile.jev in $CODE_HOME; git pull"
[ -f "$API_HOME/main.py" ] || fail \
    "no main.py at $API_HOME (set API_HOME to a checkout of the API)"
[ -d "$SHARED_DIR/evaluation_execution" ] || fail \
    "no ground truth at $SHARED_DIR/evaluation_execution.
     It is written by the evaluator's phase 32 and is NOT in git, so a checkout alone does
     not have it. Run a campaign first, or point SHARED_DIR at the folder that holds it."

DRY_RUN=0
for arg in "$@"; do [ "$arg" = "--dry-run" ] && DRY_RUN=1; done

# The pairing trap, paid for once on 2026-09-21. A sampled run compared against the
# full-set bar produces a verdict that is wrong in both directions: "does not reach
# parity" when it does, or the reverse. LIMIT and COMPARE must describe the same pass.
if [ "$LIMIT" != "0" ] && [ "$COMPARE" = "$COMPARE_DEFAULT" ]; then
    echo "WARNING: LIMIT=$LIMIT samples the set, but COMPARE=$COMPARE is gpt-4o's rate on"
    echo "         the FULL set. The two describe different passes, so the equal-risk line"
    echo "         below is measured against the wrong bar and will read too harshly."
    echo "         Either drop LIMIT to compare like with like, or pass the sampled bar,"
    echo "         which for a 100-question stratified sample is COMPARE=1.0."
    echo ""
fi

# The key is only needed for a real run. --dry-run returns before the SDK is imported, on
# purpose, so the layout and the truth can be checked on a machine that has no key at all.
ENV_ARGS=()
if [ "$DRY_RUN" -eq 0 ]; then
    [ -f "$ENV_FILE" ] || fail "no env file at $ENV_FILE (set ENV_FILE)"
    grep -q '^TYPESAFE_API_KEY=' "$ENV_FILE" || fail \
        "TYPESAFE_API_KEY is not in $ENV_FILE. Put it there, never on the command line:
         an argument is visible in the process list and in shell history."
    ENV_ARGS=(--env-file "$ENV_FILE")
    echo "NOTE: $ENV_FILE also carries the evaluator's other secrets, so this run holds"
    echo "      more than it needs. A file with TYPESAFE_API_KEY alone, passed with"
    echo "      ENV_FILE=..., would give the vendor container only what it uses."
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
echo "code   : $CODE_HOME -> /app/eval (read-only)"
echo "vocab  : $API_HOME/main.py -> /app/main.py (read-only)"
echo "truth  : $SHARED_DIR -> /shared, run $RUN, lang $LANG_CODE"
[ "$DRY_RUN" -eq 1 ] && echo "mode   : dry run, no key and no network"

docker build -f "$CODE_HOME/Dockerfile.jev" -t "$IMAGE" "$CODE_HOME" \
    || fail "image build failed"

ARGS=(--truth-dir /shared/evaluation_execution --run "$RUN" --lang "$LANG_CODE" \
      --limit "$LIMIT" --model "$MODEL")
if [ "$DRY_RUN" -eq 0 ]; then
    ARGS+=(--compare-confident-error "$COMPARE" --out "$OUT")
fi

# No --network=host: this only makes outbound calls, it serves nothing and binds no port.
docker run -it --rm \
    "${ENV_ARGS[@]+"${ENV_ARGS[@]}"}" \
    -v "$CODE_HOME":/app/eval:ro \
    -v "$API_HOME/main.py":/app/main.py:ro \
    -v "$SHARED_DIR":/shared \
    "$IMAGE" "${ARGS[@]}" "$@"
