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
# THE TWO NEW KNOBS DO NOT OPEN A NAMESPACE, AND THAT IS A TRAP
# The API takes five model selectors since FASTAPI-TEXT2SQL-232, and this script now passes
# all five. But T_WC_T2S_EVALUATION_EXECUTION still has columns for only three of them
# (FASTAPI-TEXT2SQL-234), so the skip rule above and the run folder name are both keyed on
# ENTITY_EXTRACTION_MODEL / TEXT2SQL_MODEL / COMPLEX_MODEL alone. Two consequences, and both
# of them look like success:
#   * A run that changes ONLY RESULT_ENTITY_MODEL or ANSWER_SINGLE_VALUE_MODEL is skipped
#     entirely, because rows already exist for that version, triple and language. Empty pass,
#     no error, nothing measured.
#   * Force it through by retiring those rows and it writes into the SAME folder as the
#     baseline, indistinguishable from it afterwards.
# So to move one of those two, bump API_VERSION to open a clean namespace, or do not use this
# script at all: eval/bench-result-entity.py measures the answer-entity classifier offline,
# with no execution row and no cache write, which is exactly what it was written for.
#
# BLUE OR GREEN IS DECIDED BY THE VERSION
# An even patch targets BLUE, an odd one GREEN, in main.py for the MCP and in
# text2sql-eval.py:563 for this run. 1.1.19 is ODD, so this run targets GREEN, which is where
# the 1.1.19 build already serves (verified 2026-09-14: Blue answers 1.1.18, Green 1.1.19).
#
# LANGUAGE
# "*" runs English and French in the same pass, one row per evaluation and per language.
# "en" or "fr" restricts it. The bank holds ~1444 evaluations, so "*" is roughly 2900 API
# calls at about 28k prompt tokens each: budget the wall-clock and the spend accordingly.
#
# THE STRONGER-MODEL ESCALATION IS ON, AND IT ALWAYS WAS
# COMPLEX_QUESTION_PROCESSING allows the API to retry once with the stronger model when the
# primary pipeline fails. It fired on 46 of 1784 executions (2.6 %) in campaign 001.001.018.
# Keep it on for any campaign meant to reflect production, and for the descriptive questions
# that cannot be answered any other way (a film recalled by its plot, with no title and no
# entity to extract). Turn it off only to measure the primary pipeline alone.
#
# CACHE
# The evaluator always sends retrieve_from_cache=false (hardcoded, text2sql-eval.py:580), so
# a run always measures the prompt and never the cache. STORE_TO_CACHE below only decides
# whether the results are written back. Storing warms the production cache with fresh
# answers; not storing keeps the cache free of evaluation-driven entries.
#
# Everything can be overridden from the environment without editing this file:
#   LANGUAGE=fr ./text2sql-eval.sh
#   API_VERSION=1.1.19 LANGUAGE='*' ./text2sql-eval.sh
#   TEXT2SQL_MODEL=gpt-5.6-terra API_VERSION=1.1.19 ./text2sql-eval.sh   # AFTER the baseline
#
# THE DEFAULTS ARE THE BASELINE RUN, AND THAT IS DELIBERATE
# Five times gpt-4o on 1.1.19, launched with no variable at all: `./text2sql-eval.sh`.
# It is owed for two reasons at once. The prompts moved a lot since the 001.001.018
# reference (data/text_to_sql.md +10.5 % over 6 commits, data/entity_extraction.md +18.9 %
# over 2, the last on 2026-09-14), so the 78.5 % / 82.0 % pass rates describe a pipeline
# that no longer exists, and the work of -230, -237, -238, -239, -249 and -255 has never
# been scored end to end. Until this run exists, a model comparison has nothing to be read
# against: moving a model now would move the prompt and the model at once, and a bad result
# could not be attributed to either. gpt-4o is the right side of the comparison precisely
# because it carries the long history on all five tasks.

set -u

API_VERSION=${API_VERSION:-1.1.19}
LANGUAGE=${LANGUAGE:-*}
ENTITY_EXTRACTION_MODEL=${ENTITY_EXTRACTION_MODEL:-gpt-4o}
TEXT2SQL_MODEL=${TEXT2SQL_MODEL:-gpt-4o}
COMPLEX_MODEL=${COMPLEX_MODEL:-gpt-4o}
# FASTAPI-TEXT2SQL-232: the answer-entity classifier and the single-value answerer. Read the
# header before changing either on a version that already carries executions.
RESULT_ENTITY_MODEL=${RESULT_ENTITY_MODEL:-gpt-4o}
ANSWER_SINGLE_VALUE_MODEL=${ANSWER_SINGLE_VALUE_MODEL:-gpt-4o}
STORE_TO_CACHE=${STORE_TO_CACHE:---store-to-cache}
# FASTAPI-TEXT2SQL-256. True, because that is what the run has always done: the evaluator
# hard-coded complex_question_processing=True while the old flag sent a field the API does
# not declare, so the default said "no" and the run said "yes". The flag now drives the real
# switch. The former variable name still works if it is set.
COMPLEX_QUESTION_PROCESSING=${COMPLEX_QUESTION_PROCESSING:-${COMPLEX_MODEL_USED:---complex-question-processing}}

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
echo "              result_entity=$RESULT_ENTITY_MODEL answer_single_value=$ANSWER_SINGLE_VALUE_MODEL"
echo "Cache       : $STORE_TO_CACHE"
echo "Escalation  : $COMPLEX_QUESTION_PROCESSING (stronger-model retry, fired on 2.6 % of 001.001.018)"
echo

if [ "$RESULT_ENTITY_MODEL" != "gpt-4o" ] || [ "$ANSWER_SINGLE_VALUE_MODEL" != "gpt-4o" ]; then
    echo "WARNING: you moved a model the execution table has no column for (-234)."
    echo "  The skip rule and the run folder are keyed on the first three models only, so this"
    echo "  run is either skipped as already done, or written into the baseline's own folder."
    echo "  Bump API_VERSION to open a clean namespace, or use eval/bench-result-entity.py."
    echo
fi

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
    --result-entity-model "$RESULT_ENTITY_MODEL" \
    --answer-single-value-model "$ANSWER_SINGLE_VALUE_MODEL" \
    --api-version "$API_VERSION" \
    --language "$LANGUAGE" \
    "$STORE_TO_CACHE" \
    "$COMPLEX_QUESTION_PROCESSING"

docker logs -f text2sql-eval
