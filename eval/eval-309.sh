#!/bin/bash
#
# FASTAPI-TEXT2SQL-309: evaluate the typographic rescue of the resolver gate, stage by stage.
#
# WHAT IT MEASURES
# The embeddings search returns ten candidates and the gate refuses those that do not look enough
# like the value sought. The rescue scores the same ten again on normalised strings, same
# threshold, when the gate refused them all. eval-309.py runs one corpus (values the gate refused
# in the exports, catalogue values, the same values retyped with a space after an apostrophe,
# without accents, dashes as spaces, without punctuation, values of other types, invented names)
# through the real resolver, under one stage:
#
#   none          the gate before -309, no second pass
#   apostrophes   the first fix
#   full          apostrophes, accents, dashes, punctuation
#   configured    each type with the list data/entity_resolution.json gives it, which is what the
#                 API runs after its restart: the stage that decides the deployment
#
# and `compare` lists every value whose outcome changed between the latest run of two stages,
# with the count of NEW WRONG ACCEPTANCES, which must be 0 for a stage to be switched on.
#
# DOCKER ONLY, PRODUCTION UNTOUCHED
# It runs in a throwaway container built from the API image (fastapi-text2sql-<colour>-app, which
# restart.sh builds), with the API checkout mounted read-only at /app and the share at /shared.
# The stage is set in memory inside that container: neither data/entity_resolution.json nor the
# running API is changed. So the three stages can be measured one after the other on the same
# pulled checkout, BEFORE deciding to restart the API, which is what puts a stage in production.
#
# THE CHECKOUT MUST CARRY -309
# `none` is measured on the -309 code with the second pass removed, which is the old gate to the
# letter (eval/check-rescue-309.py, case 5). So: cd $API_HOME && git pull first. Pulling does not
# change the running API; only its restart.sh does.
#
# Usage, from ~/docker/text2sql-eval (where eval/* is copied):
#   ./eval-309.sh none
#   ./eval-309.sh apostrophes
#   ./eval-309.sh full
#   ./eval-309.sh configured              # the per-type configuration, before restarting the API
#   ./eval-309.sh compare                 # none -> apostrophes, apostrophes -> full, none -> full, none -> configured
#   TYPES=Movie_title,Serie_title PER_TYPE=60 ./eval-309.sh full
#   NORMALIZERS=accents ./eval-309.sh custom   # one normaliser alone, to isolate its effect
#
# Results: $SHARED_DIR/eval-309/<stage>-<timestamp>.json and .txt (the printed table).

set -u

STAGE=${1:-}
API_HOME=${API_HOME:-$HOME/docker/fastapi-text2sql-green}
SHARED_DIR=${SHARED_DIR:-$HOME/docker/shared_data/text2sql-eval}
COLOR=${COLOR:-$(basename "$API_HOME" | sed 's/^fastapi-text2sql-//')}
IMAGE=${IMAGE:-fastapi-text2sql-$COLOR-app}
ENV_FILE=${ENV_FILE:-$API_HOME/.env}
TYPES=${TYPES:-}
PER_TYPE=${PER_TYPE:-40}
NORMALIZERS=${NORMALIZERS:-}
OUT_DIR="$SHARED_DIR/eval-309"

fail() { echo "ERROR: $*" >&2; exit 1; }

case "$STAGE" in
    none|apostrophes|full|configured|custom|compare) ;;
    *) fail "usage: $0 none|apostrophes|full|configured|custom|compare" ;;
esac

[ -f "$API_HOME/eval/eval-309.py" ] || fail \
    "no eval/eval-309.py in $API_HOME: cd $API_HOME && git pull (the running API is not affected)"
[ -f "$ENV_FILE" ] || fail "no env file at $ENV_FILE (set ENV_FILE)"
docker image inspect "$IMAGE" >/dev/null 2>&1 || fail \
    "no image $IMAGE: it is built by $API_HOME/restart.sh, or set IMAGE"
mkdir -p "$OUT_DIR" || fail "cannot create $OUT_DIR"

run_in_container() {
    # --network host: MariaDB and ChromaDB are reached exactly as the API reaches them.
    # Read-only checkout, no bytecode written into it.
    docker run --rm --network host \
        --env-file "$ENV_FILE" \
        -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONUNBUFFERED=1 \
        -e TEXT2SQL_EVAL_EXPORT_DIR=/shared \
        -v "$API_HOME":/app:ro \
        -v "$SHARED_DIR":/shared \
        -w /app --entrypoint python \
        --name "eval-309-$$" \
        "$IMAGE" eval/eval-309.py "$@"
}

latest() { ls -t "$OUT_DIR"/"$1"-*.json 2>/dev/null | head -1; }

if [ "$STAGE" = "compare" ]; then
    NONE=$(latest none); APOS=$(latest apostrophes); FULL=$(latest full); CONF=$(latest configured)
    STAMP=$(date +%Y%m%d-%H%M%S)
    {
        echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') === FASTAPI-TEXT2SQL-309 comparison"
        for pair in "$NONE $APOS" "$APOS $FULL" "$NONE $FULL" "$NONE $CONF"; do
            set -- $pair
            [ $# -eq 2 ] || { echo "(skipped: a stage has not been run yet)"; continue; }
            echo ""; echo "--- $(basename "$1") -> $(basename "$2")"
            run_in_container --compare "/shared/eval-309/$(basename "$1")" "/shared/eval-309/$(basename "$2")"
        done
    } 2>&1 | tee "$OUT_DIR/compare-$STAMP.txt"
    exit "${PIPESTATUS[0]}"
fi

ARGS=(--per-type "$PER_TYPE")
[ -n "$TYPES" ] && ARGS+=(--types "$TYPES")
if [ "$STAGE" = "custom" ]; then
    [ -n "$NORMALIZERS" ] || fail "custom needs NORMALIZERS=apostrophes,accents,... "
    ARGS+=(--normalizers "$NORMALIZERS")
    LABEL=$(echo "$NORMALIZERS" | tr ',' '+')
else
    ARGS+=(--stage "$STAGE")
    LABEL=$STAGE
fi
STAMP=$(date +%Y%m%d-%H%M%S)
ARGS+=(--out "/shared/eval-309/$LABEL-$STAMP.json")

echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') === eval-309 stage $LABEL"
echo "code  : $API_HOME (read-only), commit $(git -C "$API_HOME" log -1 --format='%h %s' 2>/dev/null)"
echo "image : $IMAGE"
echo "out   : $OUT_DIR/$LABEL-$STAMP.json"
run_in_container "${ARGS[@]}" 2>&1 | tee "$OUT_DIR/$LABEL-$STAMP.txt"
exit "${PIPESTATUS[0]}"
