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
# THE FIVE MODELS EACH OPEN A NAMESPACE (FASTAPI-TEXT2SQL-234, 2026-09-25)
# RESULT_ENTITY_MODEL and ANSWER_SINGLE_VALUE_MODEL have their own columns in
# T_WC_T2S_EVALUATION_EXECUTION. The skip rule and the run folder are keyed on all five: a run
# that moves only one of them is measured in full and lands in its own folder, suffixed
# _re-<model> and/or _asv-<model>. Rows written before the columns existed carry NULL and count
# as the default gpt-4o, so the baseline folders keep their three-model names. The migration
# eval/migrate-evaluation-execution-late-models.sql must have run before this evaluator.
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
#   EVAL_LANGUAGE=fr ./text2sql-eval.sh
#   API_VERSION=1.1.19 EVAL_LANGUAGE='*' ./text2sql-eval.sh
#   TEXT2SQL_MODEL=gpt-5.6-terra API_VERSION=1.1.19 ./text2sql-eval.sh   # AFTER the baseline
#
# THE LANGUAGE VARIABLE IS EVAL_LANGUAGE, NOT LANGUAGE
# LANGUAGE is the gettext locale list ("en_US:en") on any machine whose locale sets it, and
# ${LANGUAGE:-*} would then silently hand "en_US:en" to the evaluator, which is neither "en",
# "fr" nor "*". The old name is still honoured, but only when it holds one of those values.
#
# NOTHING IS LAUNCHED WITHOUT A TYPED "yes"
# A full two-language run is hours of wall-clock and around $150 on gpt-4o. So the script first
# builds the image, runs a read-only pre-flight inside it (what is left to run, what the target
# API answers, whether the eval copy drifted, which scheduled tasks are still armed), prints it all,
# and waits for the word "yes". Anything else aborts. With no terminal attached (cron, nohup)
# it aborts too, unless EVAL_CONFIRM=yes is set.
# EXCEPTION, a rescore-only run (Philippe, 2026-09-25): when the pre-flight counts zero API calls
# left AND zero bank rows to translate, the run spends no LLM token at all. It only purges the
# soft-deleted executions, rescores (phase 20) and re-exports (phases 30-32), which is exactly
# what follows an assertion correction. Then it launches without asking.
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
# See the header: LANGUAGE is only trusted when it holds one of our three values.
if [ -n "${EVAL_LANGUAGE:-}" ]; then
    :
elif [ "${LANGUAGE:-}" = "en" ] || [ "${LANGUAGE:-}" = "fr" ] || [ "${LANGUAGE:-}" = "*" ]; then
    EVAL_LANGUAGE=$LANGUAGE
else
    EVAL_LANGUAGE='*'
fi
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
# The git clone the eval copy is compared against. ~/docker/text2sql-eval is NOT a checkout
# and its eval/*.py drift from the repo silently (AGENTS.md, "Clients of this API").
REPO_EVAL_DIR=${REPO_EVAL_DIR:-$HOME/docker/fastapi-text2sql-blue/eval}
# Scheduled workloads to switch OFF for the duration of a run. Stopping a container is not
# enough: cron relaunches it at its next tick, in the middle of a multi-hour campaign. The house
# convention is that each repository under ~/docker carries an off.sh that renames the script
# cron calls (tmdb-movie-preprocess.sh -> tmdb-movie-preprocess-off.sh) and an on.sh that puts
# it back. The crontab never changes; its ticks simply find nothing to run. So the pre-flight
# reads every ~/docker/*/off.sh, tells from its `mv` lines which tasks are still armed, and
# recommends off.sh for each of them, including the ones not running right now (wikidata-crawler,
# sqlite, ...), since an idle armed task can start at any minute.
# Why it matters: the crawlers and preprocessors share the MariaDB and the CPU with the API and
# inflate every latency the campaign records, and embedding-update rewrites the ChromaDB
# collections the API resolves entities against, so it changes the ANSWERS, not only the timing.
DOCKER_ROOT=${DOCKER_ROOT:-$HOME/docker}
# Folders never to switch off: letsencrypt renews the TLS certificate, harmless to the run and
# costly to forget.
SCHEDULED_KEEP=${SCHEDULED_KEEP:-^(letsencrypt)$}
# Measured, gpt-4o on all five tasks, v1.1.17-1.1.18 (AGENTS.md, "The six LLM tasks").
COST_PER_1000_GPT4O=50.69
SECONDS_PER_CALL=8   # 6.04 s mean end to end + TEXT2SQL_EVAL_API_CALL_DELAY_SECONDS (2 s)

case "$EVAL_LANGUAGE" in
    en|fr|'*') ;;
    *) echo "ERROR: EVAL_LANGUAGE must be en, fr or '*' (got '$EVAL_LANGUAGE')."; exit 1 ;;
esac
case "$STORE_TO_CACHE" in
    --store-to-cache|--no-store-to-cache) ;;
    *) echo "ERROR: STORE_TO_CACHE must be --store-to-cache or --no-store-to-cache."; exit 1 ;;
esac
case "$COMPLEX_QUESTION_PROCESSING" in
    --complex-question-processing|--no-complex-question-processing|--complex-model-used|--no-complex-model-used) ;;
    *) echo "ERROR: COMPLEX_QUESTION_PROCESSING must be --complex-question-processing or --no-complex-question-processing."; exit 1 ;;
esac

if [ "$(docker ps -q -f name=text2sql-eval)" ]; then
    echo "text2sql-eval Docker container is already running."
    echo "Follow it with: docker logs -f text2sql-eval"
    exit 0
fi

cd "$EVAL_HOME" || { echo "ERROR: $EVAL_HOME not found."; exit 1; }
# Building costs nothing and the pre-flight needs the image, so it happens before the question.
echo "Building the evaluator image..."
docker build -q -t text2sql-eval-python-app . >/dev/null || { echo "ERROR: docker build failed."; exit 1; }

PATCH=${API_VERSION##*.}
if [ $((PATCH % 2)) -eq 0 ]; then COLOUR=Blue; PARITY=even; else COLOUR=Green; PARITY=odd; fi

# ---------------------------------------------------------------------------------------------
# Pre-flight, read-only, run inside the image so it sees the same .env, DB and API as the run.
# The Python is inline on purpose: a separate file would have to be copied into EVAL_HOME, and
# that copy is exactly what drifts.
# ---------------------------------------------------------------------------------------------
read -r -d '' PREFLIGHT_PY <<'PYEOF'
import os
from urllib.parse import urlparse

ver = os.environ["PF_API_VERSION"]
lang = os.environ["PF_LANGUAGE"]
major, minor, patch = (int(x) for x in ver.split("."))
fver = f"{major:03d}.{minor:03d}.{patch:03d}"

# 1. The API the run will hit, derived exactly as text2sql-eval.py derives it.
try:
    import requests
    u = urlparse(os.getenv("TEXT2SQL_API_URL", "http://localhost"))
    port = int(os.getenv("API_PORT_BLUE", 8000)) if patch % 2 == 0 else int(os.getenv("API_PORT_GREEN", 8001))
    base = f"{u.scheme or 'http'}://{u.hostname or 'localhost'}:{port}"
    print(f"PF_API_URL={base}")
    r = requests.get(base + "/", headers={"X-API-Key": os.getenv("TEXT2SQL_API_KEY", "")}, timeout=15)
    j = r.json() if r.ok else {}
    print(f"PF_API_STATUS={r.status_code}")
    print(f"PF_API_VERSION_SEEN={j.get('api_version', 'absent')}")
    print(f"PF_BKTREES={j.get('bktrees_ready', 'absent')}")
except Exception as e:
    print(f"PF_API_STATUS=unreachable ({type(e).__name__}: {e})")

# 2. What is left to run, with the same eligibility and skip rule as phase 11.
try:
    import citizenphil as cp
    cur = cp.f_getconnection().cursor()
    elig = ("FROM T_WC_T2S_EVALUATION e WHERE e.IS_EVAL = 1 AND e.DELETED = 0 AND ("
            "(e.ASSERTIONS_QUERY_RESULT <> '' AND e.ASSERTIONS_QUERY_RESULT IS NOT NULL) OR "
            "(e.ASSERTIONS_ENTITY_EXTRACTION <> '' AND e.ASSERTIONS_ENTITY_EXTRACTION IS NOT NULL) OR "
            "(e.ASSERTIONS_SQL_QUERY <> '' AND e.ASSERTIONS_SQL_QUERY IS NOT NULL)) ")
    def late(col, val):
        # Same rule as late_models_clause() in text2sql-eval.py (-234): the default model also
        # matches the NULL of the rows written before the column existed.
        v = val.replace("'", "''")
        return f"(x.{col} = '{v}' OR x.{col} IS NULL)" if val == "gpt-4o" else f"x.{col} = '{v}'"
    done = ("SELECT x.ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION_EXECUTION x WHERE x.DELETED = 0 "
            "AND x.API_VERSION = %s AND x.ENTITY_EXTRACTION_MODEL = %s AND x.TEXT2SQL_MODEL = %s "
            "AND x.COMPLEX_MODEL = %s AND x.LANG = %s "
            f"AND {late('RESULT_ENTITY_MODEL', os.environ['PF_RE'])} "
            f"AND {late('ANSWER_SINGLE_VALUE_MODEL', os.environ['PF_ASV'])}")
    models = (fver, os.environ["PF_EE"], os.environ["PF_T2S"], os.environ["PF_CX"])
    resume = (cp.f_getservervariable("strtext2sqlevalrunevalid", 0) or "").strip()
    total_remaining = 0
    for l, col in (("en", "QUESTION"), ("fr", "QUESTION_FR")):
        if lang not in (l, "*"):
            continue
        base_q = elig + f"AND e.{col} IS NOT NULL AND e.{col} <> '' "
        cur.execute("SELECT COUNT(*) AS n " + base_q)
        eligible = cur.fetchone()["n"]
        q = "SELECT COUNT(*) AS n " + base_q + f"AND e.ID_T2S_EVALUATION NOT IN ({done}) "
        params = models + (l,)
        if resume:
            q += "AND e.ID_T2S_EVALUATION >= %s "
            params += (int(resume),)
        cur.execute(q, params)
        remaining = cur.fetchone()["n"]
        total_remaining += remaining
        print(f"PF_LANG_{l}={eligible} eligible, {eligible - remaining} already done, {remaining} to run")
    print(f"PF_REMAINING={total_remaining}")
    print(f"PF_RESUME={resume or 'none'}")
    cur.execute("SELECT COUNT(*) AS n FROM T_WC_T2S_EVALUATION_EXECUTION WHERE DELETED = 1")
    print(f"PF_PURGE={cur.fetchone()['n']}")
    cur.execute("SELECT COUNT(*) AS n FROM T_WC_T2S_EVALUATION WHERE DELETED = 0 AND "
                "((QUESTION <> '' AND (QUESTION_FR IS NULL OR QUESTION_FR = '')) OR "
                "(QUESTION_FR <> '' AND (QUESTION IS NULL OR QUESTION = '')))")
    print(f"PF_TRANSLATE={cur.fetchone()['n']}")
except Exception as e:
    print(f"PF_DB=unreachable ({type(e).__name__}: {e})")
PYEOF

PREFLIGHT=$(printf '%s\n' "$PREFLIGHT_PY" | docker run -i --rm --network="host" \
    --env-file "$EVAL_HOME/.env" \
    -e PF_API_VERSION="$API_VERSION" -e PF_LANGUAGE="$EVAL_LANGUAGE" \
    -e PF_EE="$ENTITY_EXTRACTION_MODEL" -e PF_T2S="$TEXT2SQL_MODEL" -e PF_CX="$COMPLEX_MODEL" \
    -e PF_RE="$RESULT_ENTITY_MODEL" -e PF_ASV="$ANSWER_SINGLE_VALUE_MODEL" \
    --entrypoint python text2sql-eval-python-app - 2>&1)

pf() { printf '%s\n' "$PREFLIGHT" | sed -n "s/^$1=//p" | head -1; }

PF_REMAINING=$(pf PF_REMAINING)
PF_API_VERSION_SEEN=$(pf PF_API_VERSION_SEEN)
PF_BKTREES=$(pf PF_BKTREES)

echo
echo "================ text2sql evaluation campaign: pre-flight ================"
echo "Date        : $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "API version : $API_VERSION -> $COLOUR (patch $PATCH is $PARITY)"
echo "Target      : $(pf PF_API_URL)  HTTP $(pf PF_API_STATUS)"
echo "              answers api_version=${PF_API_VERSION_SEEN:-?}, bktrees_ready=${PF_BKTREES:-?}"
if [ "$EVAL_LANGUAGE" = '*' ]; then
    echo "Language(s) : * = English AND French, one API call per question and per language"
else
    echo "Language(s) : $EVAL_LANGUAGE only"
fi
echo "              to run one language: EVAL_LANGUAGE=en ./text2sql-eval.sh  (or EVAL_LANGUAGE=fr)"
echo
echo "LLM per task (the API has a 6th task, vision, that the evaluator never triggers):"
echo "  1 entity_extraction    $ENTITY_EXTRACTION_MODEL"
echo "  2 text2sql             $TEXT2SQL_MODEL"
echo "  3 result_entity        $RESULT_ENTITY_MODEL"
echo "  4 complex_question     $COMPLEX_MODEL"
echo "  5 answer_single_value  $ANSWER_SINGLE_VALUE_MODEL"
echo "  + gpt-4o, called by the evaluator itself to translate untranslated bank rows (phases 4-6)"
echo
echo "Options:"
echo "  Escalation  : $COMPLEX_QUESTION_PROCESSING (stronger-model retry, fired on 2.6 % of 001.001.018)"
echo "  Cache write : $STORE_TO_CACHE (reads are always off: retrieve_from_cache=false)"
echo "  Pacing      : TEXT2SQL_EVAL_API_CALL_DELAY_SECONDS and 429 retries, from $EVAL_HOME/.env"
echo "  Resume from : ID_T2S_EVALUATION >= $(pf PF_RESUME) (server variable strtext2sqlevalrunevalid)"
echo "  Phases      : 4-6 translate, 10 purge, 11 run, 20 score, 30-32 export to $SHARED_DIR"
echo
echo "Work:"
printf '%s\n' "$PREFLIGHT" | sed -n 's/^PF_LANG_\(..\)=/  \1 : /p'
echo "  Bank rows to translate first (phases 4-6): $(pf PF_TRANSLATE)"
echo "  Soft-deleted executions phase 10 will HARD-delete: $(pf PF_PURGE)"
if [ -n "$(pf PF_DB)" ]; then
    echo "  DATABASE NOT REACHED: $(pf PF_DB)"
fi
if [ -n "$PF_REMAINING" ]; then
    HOURS=$(awk -v n="$PF_REMAINING" -v s="$SECONDS_PER_CALL" 'BEGIN{printf "%.1f", n*s/3600}')
    echo "  Estimated wall-clock: ~${HOURS} h for $PF_REMAINING API calls"
    ALL_GPT4O=1
    for m in "$ENTITY_EXTRACTION_MODEL" "$TEXT2SQL_MODEL" "$COMPLEX_MODEL" "$RESULT_ENTITY_MODEL" "$ANSWER_SINGLE_VALUE_MODEL"; do
        [ "$m" = "gpt-4o" ] || ALL_GPT4O=0
    done
    if [ "$ALL_GPT4O" -eq 1 ]; then
        COST=$(awk -v n="$PF_REMAINING" -v c="$COST_PER_1000_GPT4O" 'BEGIN{printf "%.0f", n*c/1000}')
        echo "  Estimated LLM cost  : ~\$${COST} (measured \$${COST_PER_1000_GPT4O} per 1000 requests on gpt-4o)"
    else
        echo "  Estimated LLM cost  : UNKNOWN, a non-gpt-4o model is selected and no measured figure exists"
    fi
fi

# --- Checks ----------------------------------------------------------------------------------
WARNINGS=0
warn() { echo "  ! $*"; WARNINGS=$((WARNINGS + 1)); }
more() { echo "    $*"; }   # continuation line of the warning above, not a new one
echo
echo "Checks:"

if [ -n "$PF_API_VERSION_SEEN" ] && [ "$PF_API_VERSION_SEEN" != "$API_VERSION" ]; then
    warn "the $COLOUR API answers $PF_API_VERSION_SEEN, not $API_VERSION: the evaluator aborts on the first call."
fi
if [ "$PF_BKTREES" = "False" ]; then
    warn "bktrees_ready is false: the API is still warming up and early latencies will be inflated. Wait."
fi
if [ "$PF_REMAINING" = "0" ]; then
    echo "  - nothing left to run for this version, models and language: phase 11 will be an empty pass."
    more "this is a rescore-only run if nothing is left to translate either; for a fresh measurement,"
    more "bump API_VERSION, or retire the rows (maintenance/)."
fi
if [ "$RESULT_ENTITY_MODEL" != "gpt-4o" ] || [ "$ANSWER_SINGLE_VALUE_MODEL" != "gpt-4o" ]; then
    echo "  - result_entity=$RESULT_ENTITY_MODEL, answer_single_value=$ANSWER_SINGLE_VALUE_MODEL: this run gets its own folder (-234)."
fi
if [ "$STORE_TO_CACHE" = "--store-to-cache" ]; then
    echo "  - results will be written to the PRODUCTION cache (T_WC_T2S_CACHE, version $API_VERSION)."
fi

# Drift between this non-git copy and the git clone.
if [ -d "$REPO_EVAL_DIR" ]; then
    DRIFT=""
    for f in "$REPO_EVAL_DIR"/*.py; do
        b=$(basename "$f")
        if [ -f "$EVAL_HOME/$b" ] && ! cmp -s "$f" "$EVAL_HOME/$b"; then
            DRIFT="$DRIFT $b"
        fi
    done
    if [ -n "$DRIFT" ]; then
        warn "$EVAL_HOME differs from $REPO_EVAL_DIR on:$DRIFT"
        more "the run would use the OLD copy: git pull the clone, then copy eval/*.py into $EVAL_HOME."
    else
        echo "  - eval/*.py identical to $REPO_EVAL_DIR ($(git -C "$REPO_EVAL_DIR" log -1 --format='%h %cs' 2>/dev/null))."
    fi
else
    warn "no git clone at $REPO_EVAL_DIR to compare the eval copy against (set REPO_EVAL_DIR)."
fi

# Scheduled workloads, see DOCKER_ROOT above. A task is ARMED when a source of an `mv` line of
# its off.sh still exists, OFF when every target exists instead.
ARMED=""; DISARMED=""; UNKNOWN=""; CONTAINER_NAMES=""
for off in "$DOCKER_ROOT"/*/off.sh; do
    [ -f "$off" ] || continue
    dir=$(dirname "$off"); repo=$(basename "$dir")
    printf '%s\n' "$repo" | grep -Eq "$SCHEDULED_KEEP" && continue
    state=off; seen=0
    while read -r src dst; do
        seen=1
        CONTAINER_NAMES="$CONTAINER_NAMES|${src%.sh}"
        if [ -f "$dir/$src" ]; then state=armed
        elif [ ! -f "$dir/$dst" ] && [ "$state" = off ]; then state=unknown
        fi
    done < <(tr -d '\r' < "$off" | awk '$1 == "mv" { print $2, $3 }')
    [ "$seen" -eq 1 ] || state=unknown
    CONTAINER_NAMES="$CONTAINER_NAMES|$repo"
    case "$state" in
        armed)   ARMED="$ARMED $repo" ;;
        off)     DISARMED="$DISARMED $repo" ;;
        *)       UNKNOWN="$UNKNOWN $repo" ;;
    esac
done
if [ -n "$ARMED" ]; then
    warn "scheduled tasks still ARMED, cron can start them at any minute of the run:"
    more " $ARMED"
    more "switch them off first (renames the script cron calls, the crontab is untouched):"
    more "  for d in$ARMED; do (cd $DOCKER_ROOT/\$d && ./off.sh); done"
    more "and back on once the campaign is over:"
    more "  for d in$ARMED; do (cd $DOCKER_ROOT/\$d && ./on.sh); done"
else
    echo "  - every scheduled task under $DOCKER_ROOT is switched off."
fi
[ -n "$DISARMED" ] && echo "  - already off:$DISARMED"
[ -n "$UNKNOWN" ] && warn "state unclear (neither the script nor its -off twin found):$UNKNOWN"

# off.sh only prevents the NEXT launch: a container already running goes on until it ends.
COMPETING_PATTERN=${COMPETING_PATTERN:-^(${CONTAINER_NAMES#|})}
COMPETING=""
[ -n "$CONTAINER_NAMES" ] && COMPETING=$(docker ps --format '{{.Names}}' | grep -E "$COMPETING_PATTERN" || true)
if [ -n "$COMPETING" ]; then
    warn "running now, off.sh will not stop them (embedding-update changes the answers, not only the timings):"
    printf '%s\n' "$COMPETING" | sed 's/^/        /'
    more "wait for them to finish, or:  docker stop $(printf '%s' "$COMPETING" | tr '\n' ' ')"
else
    echo "  - none of those tasks has a container running."
fi

FREE=$(df -Pm "$SHARED_DIR" 2>/dev/null | awk 'NR==2{print $4}')
if [ -n "$FREE" ] && [ "$FREE" -lt 1024 ]; then
    warn "only ${FREE} MB free under $SHARED_DIR for the JSON exports."
fi
[ "$WARNINGS" -eq 0 ] && echo "  - no warning."
echo "=========================================================================="
echo

# --- Confirmation ----------------------------------------------------------------------------
# A rescore-only run spends nothing: no API call left (phase 11 empty) and nothing to translate
# (phases 4-6 empty, the only other LLM calls). It launches without asking. An unreachable
# database leaves both counters empty, so it never qualifies.
PF_TRANSLATE=$(pf PF_TRANSLATE)
if [ "$PF_REMAINING" = "0" ] && [ "$PF_TRANSLATE" = "0" ]; then
    echo "Rescore-only run: 0 API calls left and 0 rows to translate, no LLM token will be spent."
    echo "Launching without asking (phase 20 rescores, phases 30-32 re-export)."
elif [ "${EVAL_CONFIRM:-}" = "yes" ]; then
    echo "EVAL_CONFIRM=yes is set: launching without asking."
elif [ -t 0 ]; then
    read -r -p "Type 'yes' to launch this campaign ($WARNINGS warning(s) above), anything else aborts: " ANSWER
    if [ "$ANSWER" != "yes" ]; then
        echo "Aborted. Nothing was launched, nothing was spent."
        exit 1
    fi
else
    echo "No terminal to confirm on and EVAL_CONFIRM is not 'yes': aborted, nothing launched."
    exit 1
fi

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
    --language "$EVAL_LANGUAGE" \
    "$STORE_TO_CACHE" \
    "$COMPLEX_QUESTION_PROCESSING"

docker logs -f text2sql-eval
