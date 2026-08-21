#!/bin/bash
#
# Run the evaluation bank against the deployed API.
#
# A VERSION THAT ALREADY HAS EXECUTIONS RUNS ALMOST NOTHING
# text2sql-eval.py skips any evaluation that already has a live execution row for the same
# API_VERSION, the same three models and the same LANG (the `strnotinbase` subquery, around
# line 372). Two ways out. Either bump strapiversion, which opens a clean namespace and keeps
# the previous version's runs as a comparison point, or retire the old rows with
# maintenance/eval-executions-retirer-1-1-17.sql. The bump is simpler and is what the repo
# convention asks for anyway once a data/ prompt has changed. Without either, this script
# reports a suspiciously fast, suspiciously empty pass.
#
# BLUE OR GREEN IS DECIDED BY THE VERSION
# An even patch targets BLUE, an odd one GREEN, in main.py for the MCP and in
# text2sql-eval.py:563 for this run. 1.1.18 is even, so deploy on BLUE before launching.
#
# LANGUAGE
# "*" runs English and French in the same pass, one row per evaluation and per language.
# "en" or "fr" restricts it. The bank holds ~1444 evaluations, so "*" is roughly 2900 API
# calls at about 28k prompt tokens each: budget the wall-clock and the spend accordingly.
#
# CACHE
# The evaluator always sends retrieve_from_cache=false (hardcoded, text2sql-eval.py:580), so
# a run always measures the prompt and never the cache. STORE_TO_CACHE below only decides
# whether the results are written back. Storing warms the production cache with fresh
# answers; not storing keeps the cache free of evaluation-driven entries.
#
# Everything can be overridden from the environment without editing this file:
#   LANGUAGE=fr ./text2sql-eval.sh
#   API_VERSION=1.1.18 LANGUAGE='*' ./text2sql-eval.sh

set -u

API_VERSION=${API_VERSION:-1.1.18}
LANGUAGE=${LANGUAGE:-*}
ENTITY_EXTRACTION_MODEL=${ENTITY_EXTRACTION_MODEL:-gpt-4o}
TEXT2SQL_MODEL=${TEXT2SQL_MODEL:-gpt-4o}
COMPLEX_MODEL=${COMPLEX_MODEL:-gpt-4o}
STORE_TO_CACHE=${STORE_TO_CACHE:---store-to-cache}
COMPLEX_MODEL_USED=${COMPLEX_MODEL_USED:---no-complex-model-used}

EVAL_HOME=${EVAL_HOME:-$HOME/docker/text2sql-eval}
SHARED_DIR=${SHARED_DIR:-$HOME/docker/shared_data/text2sql-eval}

if [ "$(docker ps -q -f name=text2sql-eval)" ]; then
    echo "text2sql-eval Docker container is already running."
    echo "Follow it with: docker logs -f text2sql-eval"
    exit 0
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
echo "API version : $API_VERSION"
echo "Language    : $LANGUAGE"
echo "Models      : $ENTITY_EXTRACTION_MODEL / $TEXT2SQL_MODEL / $COMPLEX_MODEL"
echo "Cache       : $STORE_TO_CACHE"
echo

if [ "$LANGUAGE" = "*" ]; then
    echo "Full two-language pass. Does $API_VERSION already carry executions?"
    echo "  If so, bump the version or retire them: any evaluation with a live"
    echo "  execution row for this version, models and language is skipped."
    echo
fi

cd "$EVAL_HOME" || { echo "ERROR: $EVAL_HOME not found."; exit 1; }
docker build -t text2sql-eval-python-app .

# Secrets are injected at runtime via --env-file from a host-managed env file kept outside
# the app source tree (never baked into the image).
docker run -d --rm --network="host" \
    --env-file "$EVAL_HOME/.env" \
    --name text2sql-eval \
    -v "$SHARED_DIR:/shared" \
    text2sql-eval-python-app \
    --entity-extraction-model "$ENTITY_EXTRACTION_MODEL" \
    --text2sql-model "$TEXT2SQL_MODEL" \
    --complex-model "$COMPLEX_MODEL" \
    --api-version "$API_VERSION" \
    --language "$LANGUAGE" \
    "$STORE_TO_CACHE" \
    "$COMPLEX_MODEL_USED"

docker logs -f text2sql-eval
