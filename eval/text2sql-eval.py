import argparse
import time
import requests
import pymysql.cursors
import json
import openai
import citizenphil as cp
from datetime import datetime, timedelta, date
from decimal import Decimal
import shutil
import os
import unicodedata
from urllib.parse import urlparse
from dotenv import load_dotenv
import pandas as pd
import pytest
import re
import html
import sys

import entity_extraction_eval_functions as ee_eval
import text2sql_eval_functions as t2s_eval

# Load environment variables from .env file
load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

EVAL_API_CALL_DELAY_SECONDS = float(os.getenv("TEXT2SQL_EVAL_API_CALL_DELAY_SECONDS", "2"))
EVAL_API_429_MAX_RETRIES = int(os.getenv("TEXT2SQL_EVAL_API_429_MAX_RETRIES", "6"))
EVAL_API_429_FALLBACK_DELAY_SECONDS = float(os.getenv("TEXT2SQL_EVAL_API_429_FALLBACK_DELAY_SECONDS", "30"))
EVAL_API_429_BUFFER_SECONDS = float(os.getenv("TEXT2SQL_EVAL_API_429_BUFFER_SECONDS", "3"))


def _extract_retry_after_seconds(response=None, response_json=None, error_text: str = ""):
    """Extract retry-after seconds from HTTP headers, structured JSON, or provider error text."""
    candidates = []

    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                candidates.append(float(retry_after))
            except (TypeError, ValueError):
                pass

    if isinstance(response_json, dict):
        for key in ["retry_after_seconds", "retry_after", "suggested_retry_after_seconds"]:
            value = response_json.get(key)
            if value is not None:
                try:
                    candidates.append(float(value))
                except (TypeError, ValueError):
                    pass

        retry_hint = response_json.get("retry_info")
        if isinstance(retry_hint, dict):
            value = retry_hint.get("retry_after_seconds")
            if value is not None:
                try:
                    candidates.append(float(value))
                except (TypeError, ValueError):
                    pass

    raw_text = error_text or ""
    patterns = [
        r"Please retry in\s+([0-9]+(?:\.[0-9]+)?)s",
        r"retryDelay['\"]?\s*[:=]\s*['\"]?([0-9]+(?:\.[0-9]+)?)s",
        r"retry after\s+([0-9]+(?:\.[0-9]+)?)s",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if match:
            try:
                candidates.append(float(match.group(1)))
            except (TypeError, ValueError):
                pass

    if not candidates:
        return None
    return max(candidates)


def _is_retryable_quota_error(response=None, response_json=None, error_text: str = "") -> bool:
    """Return True when the response/error indicates a retryable provider quota/rate-limit failure."""
    if response is not None and response.status_code == 429:
        return True

    if isinstance(response_json, dict):
        if response_json.get("is_retryable") is True and str(response_json.get("error_code") or "") == "429":
            return True
        if response_json.get("error_code") == "429":
            return True

    haystack = error_text or ""
    upper = haystack.upper()
    return (
        "RESOURCE_EXHAUSTED" in upper
        or "RATE_LIMIT" in upper
        or "QUOTA EXCEEDED" in upper
        or "ERROR CODE: 429" in upper
        or "429" in upper and "RETRY" in upper
    )


def translate_question_to_french(question: str) -> str:
    """Translate an evaluation question from English to French using OpenAI gpt-4o."""
    client = openai.OpenAI(api_key=openai.api_key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You translate evaluation questions from English to French. Return only the French translation, with no explanation or surrounding quotes."},
            {"role": "user", "content": question},
        ],
        temperature=0,
    )
    return response.choices[0].message.content.strip()


def translate_question_to_english(question: str) -> str:
    """Translate an evaluation question from French to English using OpenAI gpt-4o."""
    client = openai.OpenAI(api_key=openai.api_key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You translate evaluation questions from French to English. Return only the English translation, with no explanation or surrounding quotes."},
            {"role": "user", "content": question},
        ],
        temperature=0,
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# JSON export helpers (Phases 30 / 31 / 32) — write taxonomy / question bank /
# execution rows out to /shared/<subfolder>/*.json so an LLM can analyse the
# evaluator's output without needing direct DB access.
# ---------------------------------------------------------------------------
EXPORT_BASE_DIR = os.getenv("TEXT2SQL_EVAL_EXPORT_DIR", "/shared")

QUESTION_TRANSLATION_NOTE = (
    "Each evaluation carries an English (`question_en`) and a French (`question_fr`) form. "
    "One side is the original input typed by the user; the other is automatically translated by "
    "gpt-4o through Phase 5 (EN→FR) or Phase 6 (FR→EN) of the evaluator. Translations are generally "
    "high-quality but may differ in wording from a natively-typed equivalent — keep this in mind "
    "when comparing API outputs across languages."
)


def slug_for_filename(text, max_len=60):
    """ASCII-fold + lowercase + replace non-alphanumeric runs with '-' + truncate.

    'Best films of Martin Scorsese?' -> 'best-films-of-martin-scorsese'
    'gpt-4o' -> 'gpt-4o'  (already filesystem-safe)
    Returns 'untitled' when the input collapses to an empty slug.
    """
    if not text:
        return "untitled"
    nfkd = unicodedata.normalize("NFKD", str(text))
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_only = ascii_only.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def json_default(obj):
    """JSON serializer for date/datetime/Decimal coming out of pymysql rows."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj).__name__} not JSON serializable")


def ensure_export_dir(subfolder):
    """Create EXPORT_BASE_DIR/<subfolder> if missing; return the absolute path or None on error."""
    target = os.path.join(EXPORT_BASE_DIR, subfolder)
    try:
        os.makedirs(target, exist_ok=True)
        return target
    except OSError as e:
        print(f"⚠ Cannot create directory {target}: {e}")
        return None


def write_json_if_changed(output_dir, filename, payload):
    """Write JSON file when missing or when content differs from disk; return 'wrote' / 'skipped' / 'error'.

    'skipped' = file already exists with byte-identical serialized content (no write performed).
    'wrote'   = file was created or overwritten because content differed.
    """
    output_path = os.path.join(output_dir, filename)
    try:
        new_content = json.dumps(payload, ensure_ascii=False, indent=2, default=json_default)
    except (TypeError, ValueError) as e:
        print(f"⚠ Failed to serialize payload for {output_path}: {e}")
        return "error"
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
            if existing_content == new_content:
                return "skipped"
        except OSError as e:
            print(f"⚠ Failed to read {output_path} (will attempt rewrite): {e}")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return "wrote"
    except OSError as e:
        print(f"⚠ Failed to write {output_path}: {e}")
        return "error"

# ---------------------------------------------------------------------------
# CLI arguments (all optional; defaults match the previous hardcoded values)
# ---------------------------------------------------------------------------
_parser = argparse.ArgumentParser(description="Text2SQL evaluation runner")
_parser.add_argument("--entity-extraction-model", default="gpt-4o",
                     help="LLM model for entity extraction (default: gpt-4o)")
_parser.add_argument("--text2sql-model", default="gpt-4o",
                     help="LLM model for text-to-SQL (default: gpt-4o)")
_parser.add_argument("--complex-model", default="gpt-4o",
                     help="LLM model for complex question processing (default: gpt-4o)")
_parser.add_argument("--api-version", default="1.1.14",
                     help="API version to evaluate against (default: 1.1.14)")
_parser.add_argument("--language", default="*",
                     help="Language filter: 'en', 'fr', or '*' for all (default: *)")
_parser.add_argument("--store-to-cache", dest="store_to_cache", action="store_true",
                     help="Store evaluation API results in cache (default: true)")
_parser.add_argument("--no-store-to-cache", dest="store_to_cache", action="store_false",
                     help="Do not store evaluation API results in cache")
_parser.add_argument("--complex-model-used", dest="complex_model_used", action="store_true",
                     help="Set API input complex_model_used=true for the evaluation run")
_parser.add_argument("--no-complex-model-used", dest="complex_model_used", action="store_false",
                     help="Set API input complex_model_used=false for the evaluation run (default)")
_parser.set_defaults(store_to_cache=True)
_parser.set_defaults(complex_model_used=False)
_cli_args = _parser.parse_args()

datnow = datetime.now(cp.paris_tz)
# Compute the date and time for J-1 (yesterday)
# So we are sure to find the TMDb Id export files for this day
delta = timedelta(days=1)
datjminus1 = datnow - delta
#strdatjminus1 = datjminus1.strftime("%Y-%m-%d %H:%M:%S")
strdattodayminus1 = datjminus1.strftime("%Y-%m-%d")
strdattodayminus1us = datjminus1.strftime("%m_%d_%Y")

try:
    conn = cp.f_getconnection()
    with conn:
        with conn.cursor() as cursor:
            cursor3 = conn.cursor()
            # Start timing the script execution
            start_time = time.time()
            strnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
            cp.f_setservervariable("strtext2sqlevalstartdatetime",strnow,"Date and time of the last start of the Text2SQL evaluation",0)
            strprocessesexecutedprevious = cp.f_getservervariable("strtext2sqlevalprocessesexecuted",0)
            strprocessesexecuteddesc = "List of processes executed in the Text2SQL evaluation"
            cp.f_setservervariable("strtext2sqlevalprocessesexecutedprevious",strprocessesexecutedprevious,strprocessesexecuteddesc + " (previous execution)",0)
            strprocessesexecuted = ""
            cp.f_setservervariable("strtext2sqlevalprocessesexecuted",strprocessesexecuted,strprocessesexecuteddesc,0)
            strtotalruntimedesc = "Total runtime of the TMDb crawler"
            strtotalruntimeprevious = cp.f_getservervariable("strtext2sqlevaltotalruntime",0)
            cp.f_setservervariable("strtext2sqlevaltotalruntimeprevious",strtotalruntimeprevious,strtotalruntimedesc + " (previous execution)",0)
            strtotalruntime = "RUNNING"
            cp.f_setservervariable("strtext2sqlevaltotalruntime",strtotalruntime,strtotalruntimedesc,0)
            
            strentityextractionmodeleval = _cli_args.entity_extraction_model
            strtext2sqlmodeleval = _cli_args.text2sql_model
            strcomplexmodeleval = _cli_args.complex_model
            strapiversioneval = _cli_args.api_version
            strlanguage = _cli_args.language
            blnstoretocache = _cli_args.store_to_cache
            blncomplexmodelused = _cli_args.complex_model_used

            #arrprocessscope = {11: 'run evals'}
            #arrprocessscope = {20: 'process evals'}
            arrprocessscope = {4: 'translate categories to French', 5: 'translate EN to FR', 6: 'translate FR to EN', 10: 'cleanup deleted eval executions', 11: 'run evals', 20: 'process evals', 30: 'export categories to JSON', 31: 'export evaluations to JSON', 32: 'export executions to JSON'}
            #arrprocessscope = {4: 'translate categories to French', 5: 'translate EN to FR', 6: 'translate FR to EN', 10: 'cleanup deleted eval executions', 20: 'process evals', 30: 'export categories to JSON', 31: 'export evaluations to JSON', 32: 'export executions to JSON'}
            strrunevalidold = cp.f_getservervariable("strtext2sqlevalrunevalid",0)
            # Pre-initialize process-20 accumulators so the global-score summary
            # printed at the end of the script always has values to read, even
            # when process 20 is not in arrprocessscope.
            dblcumulatedscore = 0
            dblevalcount = 0
            dbl_entity_extraction_processing_time_sum = 0.0
            lng_entity_extraction_processing_time_count = 0
            dbl_text2sql_processing_time_sum = 0.0
            lng_text2sql_processing_time_count = 0
            dbl_embeddings_processing_time_sum = 0.0
            lng_embeddings_processing_time_count = 0
            dbl_query_execution_time_sum = 0.0
            lng_query_execution_time_count = 0
            dbl_total_processing_time_sum = 0.0
            lng_total_processing_time_count = 0
            for intindex, strdesc in arrprocessscope.items():
                # Get the current date and time
                datnow = datetime.now(cp.paris_tz)
                # Compute the date and time 14 days ago
                delta = timedelta(days=14)
                datjminus14 = datnow - delta
                strdatjminus14 = datjminus14.strftime("%Y-%m-%d %H:%M:%S")
                strprocessesexecuted += str(intindex) + ", "
                cp.f_setservervariable("strtext2sqlevalprocessesexecuted",strprocessesexecuted,strprocessesexecuteddesc,0)
                # Print the result (optional)
                #print("Current Date and Time:", current_datetime)
                #print("Date and Time 14 days ago:", past_datetime)
                # Now use the TMDb API to import data into the MySQL database
                # print(intindex, value)
                strcurrentprocess = ""
                strsql = ""
                strapiversionevalformatted = t2s_eval.format_api_version(strapiversioneval)
                lngrowsperpageeval = 100
                if intindex == 4:
                    strcurrentprocess = f"{intindex}: translating evaluation categories to French "
                    strsql = ""
                    strsql += "SELECT ID_T2S_EVALUATION_CATEGORY AS id, DESCRIPTION "
                    strsql += "FROM T_WC_T2S_EVALUATION_CATEGORY "
                    strsql += "WHERE DELETED = 0 "
                    strsql += "AND DESCRIPTION IS NOT NULL "
                    strsql += "AND DESCRIPTION <> '' "
                    strsql += "AND (DESCRIPTION_FR IS NULL OR DESCRIPTION_FR = '') "
                    strsql += "ORDER BY ID_T2S_EVALUATION_CATEGORY ASC "
                elif intindex == 5:
                    strcurrentprocess = f"{intindex}: translating evaluation questions from English to French "
                    strsql = ""
                    strsql += "SELECT ID_T2S_EVALUATION AS id, QUESTION "
                    strsql += "FROM T_WC_T2S_EVALUATION "
                    strsql += "WHERE DELETED = 0 "
                    strsql += "AND QUESTION IS NOT NULL "
                    strsql += "AND QUESTION <> '' "
                    strsql += "AND (QUESTION_FR IS NULL OR QUESTION_FR = '') "
                    strsql += "ORDER BY ID_T2S_EVALUATION ASC "
                    #strsql += "LIMIT 10 "
                elif intindex == 6:
                    strcurrentprocess = f"{intindex}: translating evaluation questions from French to English "
                    strsql = ""
                    strsql += "SELECT ID_T2S_EVALUATION AS id, QUESTION_FR "
                    strsql += "FROM T_WC_T2S_EVALUATION "
                    strsql += "WHERE DELETED = 0 "
                    strsql += "AND QUESTION_FR IS NOT NULL "
                    strsql += "AND QUESTION_FR <> '' "
                    strsql += "AND (QUESTION IS NULL OR QUESTION = '') "
                    strsql += "ORDER BY ID_T2S_EVALUATION ASC "
                    strsql += "LIMIT 10 "
                elif intindex == 10:
                    strcurrentprocess = f"{intindex}: deleting deleted records from T_WC_T2S_EVALUATION_EXECUTION "
                    print(strcurrentprocess)
                    cp.f_setservervariable("strtext2sqlevalcurrentprocess",strcurrentprocess,"Current process in the Text2SQL evaluation",0)
                    strsql = "DELETE FROM T_WC_T2S_EVALUATION_EXECUTION WHERE DELETED = 1"
                    print(strsql)
                    cursor.execute(strsql)
                    cp.connectioncp.commit()
                    continue
                elif intindex == 11:
                    # Running evaluations on the FastAPI text2SQL API
                    strlangdesc = {"en": "English", "fr": "French", "*": "all-language"}
                    strcurrentprocess = f"{intindex}: running {strlangdesc.get(strlanguage, strlanguage)} evaluations on the FastAPI text2SQL API "
                    strsql = ""
                    strsql += "SELECT ID_T2S_EVALUATION AS id, QUESTION, QUESTION_FR "
                    strsql += "FROM T_WC_T2S_EVALUATION "
                    strsql += "WHERE IS_EVAL = 1 "
                    strsql += "AND DELETED = 0 "
                    strsql += "AND ( "
                    strsql += "(ASSERTIONS_QUERY_RESULT <> '' AND ASSERTIONS_QUERY_RESULT IS NOT NULL) "
                    strsql += "OR (ASSERTIONS_ENTITY_EXTRACTION <> '' AND ASSERTIONS_ENTITY_EXTRACTION IS NOT NULL) "
                    strsql += "OR (ASSERTIONS_SQL_QUERY <> '' AND ASSERTIONS_SQL_QUERY IS NOT NULL) "
                    strsql += ") "
                    strnotinbase = (
                        "SELECT T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION "
                        "FROM T_WC_T2S_EVALUATION_EXECUTION "
                        "WHERE T_WC_T2S_EVALUATION_EXECUTION.DELETED = 0 "
                        f"AND API_VERSION = '{strapiversionevalformatted}' "
                        f"AND ENTITY_EXTRACTION_MODEL = '{strentityextractionmodeleval}' "
                        f"AND TEXT2SQL_MODEL = '{strtext2sqlmodeleval}' "
                        f"AND COMPLEX_MODEL = '{strcomplexmodeleval}' "
                    )
                    if strlanguage == "en":
                        strsql += "AND QUESTION IS NOT NULL AND QUESTION <> '' "
                        strsql += "AND ID_T2S_EVALUATION NOT IN ( "
                        strsql += strnotinbase + "AND LANG = 'en' "
                        strsql += ") "
                    elif strlanguage == "fr":
                        strsql += "AND QUESTION_FR IS NOT NULL AND QUESTION_FR <> '' "
                        strsql += "AND ID_T2S_EVALUATION NOT IN ( "
                        strsql += strnotinbase + "AND LANG = 'fr' "
                        strsql += ") "
                    else:  # "*"
                        strsql += "AND ((QUESTION IS NOT NULL AND QUESTION <> '') OR (QUESTION_FR IS NOT NULL AND QUESTION_FR <> '')) "
                        strsql += "AND ( "
                        strsql += "(QUESTION IS NOT NULL AND QUESTION <> '' AND ID_T2S_EVALUATION NOT IN ( "
                        strsql += strnotinbase + "AND LANG = 'en' "
                        strsql += ")) "
                        strsql += "OR "
                        strsql += "(QUESTION_FR IS NOT NULL AND QUESTION_FR <> '' AND ID_T2S_EVALUATION NOT IN ( "
                        strsql += strnotinbase + "AND LANG = 'fr' "
                        strsql += ")) "
                        strsql += ") "
                    #strrunevalidold = "486"
                    if strrunevalidold != "":
                        strsql += "AND ID_T2S_EVALUATION >= " + strrunevalidold + " "
                    strsql += "ORDER BY ID_T2S_EVALUATION ASC "
                    #strsql += "LIMIT 10 "
                elif intindex == 20:
                    # Processing evaluations results to compute the scoring
                    strcurrentprocess = f"{intindex}: processing evaluations to compute the results "
                    strsql = ""
                    strsql += "SELECT T_WC_T2S_EVALUATION_EXECUTION.ID_ROW AS id, T_WC_T2S_EVALUATION_EXECUTION.JSON_RESULT, T_WC_T2S_EVALUATION.ASSERTIONS_QUERY_RESULT, T_WC_T2S_EVALUATION.ASSERTIONS_ENTITY_EXTRACTION, T_WC_T2S_EVALUATION.ASSERTIONS_SQL_QUERY "
                    strsql += "FROM T_WC_T2S_EVALUATION_EXECUTION "
                    strsql += "INNER JOIN T_WC_T2S_EVALUATION ON T_WC_T2S_EVALUATION.ID_T2S_EVALUATION = T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION "
                    strsql += "WHERE T_WC_T2S_EVALUATION.DELETED = 0 "
                    strsql += "AND T_WC_T2S_EVALUATION_EXECUTION.DELETED = 0 "
                    strsql += "AND API_VERSION = '" + strapiversionevalformatted + "' AND ENTITY_EXTRACTION_MODEL = '" + strentityextractionmodeleval + "' AND TEXT2SQL_MODEL = '" + strtext2sqlmodeleval + "' AND COMPLEX_MODEL = '" + strcomplexmodeleval + "' "
                    if strlanguage != "*":
                        strsql += "AND T_WC_T2S_EVALUATION_EXECUTION.LANG = '" + strlanguage + "' "
                    #strsql += "AND T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION IN (1) "
                    #strsql += "AND T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 20, 13, 14, 2139) "
                    strsql += "ORDER BY T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION ASC "
                    #strsql += "LIMIT 5 "
                elif intindex == 30:
                    # Export evaluation categories to /shared/evaluation_category/*.json (full taxonomy, CLI-agnostic)
                    strcurrentprocess = f"{intindex}: exporting evaluation categories to {EXPORT_BASE_DIR}/evaluation_category "
                    strsql = ""
                    strsql += "SELECT ID_T2S_EVALUATION_CATEGORY AS id, DESCRIPTION, DESCRIPTION_FR, "
                    strsql += "LONG_DESC, MOT_CLE, MOT_CLE_AUTO, ID_PARENT, LANG, DISPLAY_ORDER, "
                    strsql += "DAT_CREAT, TIM_UPDATED "
                    strsql += "FROM T_WC_T2S_EVALUATION_CATEGORY "
                    strsql += "WHERE DELETED = 0 "
                    strsql += "ORDER BY ID_T2S_EVALUATION_CATEGORY ASC "
                    lng_export_wrote = 0
                    lng_export_skipped = 0
                    lng_export_errors = 0
                elif intindex == 31:
                    # Export evaluation question bank to /shared/evaluation/*.json (full bank, CLI-agnostic)
                    strcurrentprocess = f"{intindex}: exporting evaluations to {EXPORT_BASE_DIR}/evaluation "
                    strsql = ""
                    strsql += "SELECT ID_T2S_EVALUATION AS id, ID_T2S_EVALUATION_CATEGORY, "
                    strsql += "QUESTION, QUESTION_FR, "
                    strsql += "ASSERTIONS_ENTITY_EXTRACTION, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, "
                    strsql += "LONG_DESC, MOT_CLE, MOT_CLE_AUTO, IS_EVAL, IS_SAMPLE, "
                    strsql += "DISPLAY_ORDER, DAT_CREAT, TIM_UPDATED "
                    strsql += "FROM T_WC_T2S_EVALUATION "
                    strsql += "WHERE DELETED = 0 "
                    strsql += "ORDER BY ID_T2S_EVALUATION ASC "
                    lng_export_wrote = 0
                    lng_export_skipped = 0
                    lng_export_errors = 0
                elif intindex == 32:
                    # Export evaluation executions to
                    # /shared/evaluation_execution/<api_version>_<lang>_<eemodel>_<t2smodel>_<complexmodel>/*.json
                    # (filtered by CLI tuple — same scope as Phase 20). One subfolder per run signature
                    # so successive evaluations across versions/models/languages stay separated.
                    strcurrentprocess = f"{intindex}: exporting evaluation executions to {EXPORT_BASE_DIR}/evaluation_execution/<run-subfolder> "
                    strsql = ""
                    strsql += "SELECT EE.ID_ROW AS id, EE.ID_T2S_EVALUATION, EE.LANG, EE.API_VERSION, "
                    strsql += "EE.ENTITY_EXTRACTION_MODEL, EE.TEXT2SQL_MODEL, EE.COMPLEX_MODEL, "
                    strsql += "EE.JSON_RESULT, EE.TIM_EXECUTION, EE.DAT_CREAT, EE.TIM_UPDATED, "
                    strsql += "EE.ENTITY_EXTRACTION_PROCESSING_TIME, EE.TEXT2SQL_PROCESSING_TIME, "
                    strsql += "EE.EMBEDDINGS_PROCESSING_TIME, EE.QUERY_EXECUTION_TIME, EE.TOTAL_PROCESSING_TIME, "
                    strsql += "EE.ASSERTIONS_ENTITY_EXTRACTION_SCORE, EE.ASSERTIONS_SQL_QUERY_SCORE, "
                    strsql += "EE.ASSERTIONS_RESULT_SCORE, EE.ASSERTIONS_TOTAL_SCORE, "
                    strsql += "EE.ASSERTIONS_RESULT_DETAILED "
                    strsql += "FROM T_WC_T2S_EVALUATION_EXECUTION EE "
                    strsql += "WHERE EE.DELETED = 0 "
                    strsql += f"AND EE.API_VERSION = '{strapiversionevalformatted}' "
                    strsql += f"AND EE.ENTITY_EXTRACTION_MODEL = '{strentityextractionmodeleval}' "
                    strsql += f"AND EE.TEXT2SQL_MODEL = '{strtext2sqlmodeleval}' "
                    strsql += f"AND EE.COMPLEX_MODEL = '{strcomplexmodeleval}' "
                    if strlanguage != "*":
                        strsql += f"AND EE.LANG = '{strlanguage}' "
                    strsql += "ORDER BY EE.ID_ROW ASC "
                    lng_export_wrote = 0
                    lng_export_skipped = 0
                    lng_export_errors = 0
                if strsql != "":
                    print(strcurrentprocess)
                    cp.f_setservervariable("strtext2sqlevalcurrentprocess",strcurrentprocess,"Current process in the Text2SQL evaluation",0)
                    print(strsql)
                    lngcount = 0
                    strdescvarname = strdesc.replace(" ","")
                    print("strdescvarname", strdescvarname)
                    cursor.execute(strsql)
                    lngrowcount = cursor.rowcount
                    print(f"{lngrowcount} lines")
                    results = cursor.fetchall()
                    intconfigerror = False
                    #exit()
                    for row in results:
                        # print("------------------------------------------")
                        lngid = row['id']
                        print(f"{strdesc} id: {lngid}")
                        if intindex == 4:
                            strdescription = row['DESCRIPTION']
                            print(strdescription)
                            strdescriptionfr = translate_question_to_french(strdescription)
                            print(strdescriptionfr)
                            arrtranslationcouples = {}
                            arrtranslationcouples["DESCRIPTION_FR"] = strdescriptionfr
                            strsqltablename = "T_WC_T2S_EVALUATION_CATEGORY"
                            strsqlupdatecondition = f"ID_T2S_EVALUATION_CATEGORY = {lngid}"
                            cp.f_sqlupdatearray(strsqltablename,arrtranslationcouples,strsqlupdatecondition,1)
                        elif intindex == 5:
                            strquestion = row['QUESTION']
                            print(strquestion)
                            strquestionfr = translate_question_to_french(strquestion)
                            print(strquestionfr)
                            arrtranslationcouples = {}
                            arrtranslationcouples["QUESTION_FR"] = strquestionfr
                            strsqltablename = "T_WC_T2S_EVALUATION"
                            strsqlupdatecondition = f"ID_T2S_EVALUATION = {lngid}"
                            cp.f_sqlupdatearray(strsqltablename,arrtranslationcouples,strsqlupdatecondition,1)
                        elif intindex == 6:
                            strquestionfr = row['QUESTION_FR']
                            print(strquestionfr)
                            strquestion = translate_question_to_english(strquestionfr)
                            print(strquestion)
                            arrtranslationcouples = {}
                            arrtranslationcouples["QUESTION"] = strquestion
                            strsqltablename = "T_WC_T2S_EVALUATION"
                            strsqlupdatecondition = f"ID_T2S_EVALUATION = {lngid}"
                            cp.f_sqlupdatearray(strsqltablename,arrtranslationcouples,strsqlupdatecondition,1)
                        elif intindex == 11:
                            # Running evaluations on the FastAPI text2SQL API
                            strquestion_en = (row.get('QUESTION') or "").strip()
                            strquestion_fr = (row.get('QUESTION_FR') or "").strip()

                            # Build list of (question_text, lang_code) pairs to evaluate
                            arrlangpairs = []
                            if strlanguage in ("en", "*") and strquestion_en:
                                arrlangpairs.append((strquestion_en, "en"))
                            if strlanguage in ("fr", "*") and strquestion_fr:
                                arrlangpairs.append((strquestion_fr, "fr"))

                            if not arrlangpairs:
                                continue

                            # For "*" mode, skip languages already evaluated for this row
                            if strlanguage == "*":
                                cursor3.execute(
                                    "SELECT LANG FROM T_WC_T2S_EVALUATION_EXECUTION "
                                    "WHERE DELETED = 0 AND ID_T2S_EVALUATION = %s "
                                    "AND API_VERSION = %s AND ENTITY_EXTRACTION_MODEL = %s "
                                    "AND TEXT2SQL_MODEL = %s AND COMPLEX_MODEL = %s",
                                    (lngid, strapiversionevalformatted, strentityextractionmodeleval, strtext2sqlmodeleval, strcomplexmodeleval)
                                )
                                arralreadydone = {r['LANG'] for r in cursor3.fetchall()}
                                arrlangpairs = [(q, l) for q, l in arrlangpairs if l not in arralreadydone]
                                if not arrlangpairs:
                                    continue

                            # Connection setup
                            base_url_env = os.getenv("TEXT2SQL_API_URL", "http://localhost")
                            parsed_base_url = urlparse(base_url_env)
                            base_scheme = parsed_base_url.scheme or "http"
                            base_host = parsed_base_url.hostname or "localhost"
                            version_parts = strapiversioneval.split('.')
                            patch_version = int(version_parts[2])
                            api_port_blue = int(os.getenv("API_PORT_BLUE", 8000))
                            api_port_green = int(os.getenv("API_PORT_GREEN", 8001))
                            api_port = api_port_blue if patch_version % 2 == 0 else api_port_green

                            base_url = f"{base_scheme}://{base_host}:{api_port}"
                            url = f"{base_url}/search/text2sql"
                            api_key = os.getenv("TEXT2SQL_API_KEY")
                            headers = {"Content-Type": "application/json"}
                            if api_key:
                                headers["X-API-Key"] = api_key

                            # One API call per (question, lang) pair because ui_language affects the answer field
                            for strquestion, strevallang in arrlangpairs:
                                print(f"  [{strevallang}] {strquestion}")
                                payload = {
                                    "question": strquestion,
                                    "question_hashed": "",
                                    "page": 1,
                                    "rows_per_page": lngrowsperpageeval,
                                    "retrieve_from_cache": False,
                                    "store_to_cache": blnstoretocache,
                                    "llm_model_entity_extraction": strentityextractionmodeleval,
                                    "llm_model_text2sql": strtext2sqlmodeleval,
                                    "llm_model_complex": strcomplexmodeleval,
                                    "complex_model_used": blncomplexmodelused,
                                    "complex_question_processing": True,
                                    "complex_question_already_resolved": False,
                                    "ui_language": strevallang,
                                }
                                print(url)
                                print(payload)
                                strdatnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
                                if EVAL_API_CALL_DELAY_SECONDS > 0:
                                    print(f"Sleeping {EVAL_API_CALL_DELAY_SECONDS:.1f}s before API call")
                                    time.sleep(EVAL_API_CALL_DELAY_SECONDS)

                                retry_count = 0
                                response = None
                                response_json = None
                                while True:
                                    try:
                                        response = requests.post(url, headers=headers, json=payload, timeout=120)
                                    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
                                        print(f"⚠ Request failed for eval id {lngid} [{strevallang}]: {type(e).__name__}: {e}")
                                        break

                                    response_json = None
                                    try:
                                        response_json = response.json()
                                    except ValueError:
                                        response_json = None

                                    error_text = ""
                                    if isinstance(response_json, dict):
                                        error_text = str(response_json.get("error") or "")
                                    if response is not None and response.status_code >= 400 and not error_text:
                                        error_text = response.text or ""

                                    is_retryable = _is_retryable_quota_error(response=response, response_json=response_json, error_text=error_text)
                                    if is_retryable:
                                        retry_count += 1
                                        retry_after = _extract_retry_after_seconds(response=response, response_json=response_json, error_text=error_text)
                                        wait_seconds = (retry_after if retry_after is not None else EVAL_API_429_FALLBACK_DELAY_SECONDS) + EVAL_API_429_BUFFER_SECONDS
                                        structured_error_code = None
                                        structured_is_retryable = None
                                        structured_provider = None
                                        if isinstance(response_json, dict):
                                            structured_error_code = response_json.get("error_code")
                                            structured_is_retryable = response_json.get("is_retryable")
                                            structured_provider = response_json.get("provider")
                                        print(f"⚠ Retryable 429/quota error for eval id {lngid} [{strevallang}] (attempt {retry_count}/{EVAL_API_429_MAX_RETRIES})")
                                        print(
                                            f"⚠ Retry metadata: status={response.status_code if response is not None else 'n/a'} "
                                            f"error_code={structured_error_code} is_retryable={structured_is_retryable} "
                                            f"provider={structured_provider} retry_after_seconds={retry_after}"
                                        )
                                        if error_text:
                                            print(f"⚠ Retry error text: {error_text}")
                                        print(f"⚠ Waiting {wait_seconds:.1f}s before retry")
                                        if retry_count >= EVAL_API_429_MAX_RETRIES:
                                            print(f"❌ Retry budget exhausted for eval id {lngid} [{strevallang}]. Stopping evaluation run.")
                                            sys.exit(1)
                                        time.sleep(wait_seconds)
                                        continue

                                    try:
                                        response.raise_for_status()
                                    except requests.exceptions.HTTPError as e:
                                        print(f"⚠ Request failed for eval id {lngid} [{strevallang}]: {type(e).__name__}: {e}")
                                        break

                                    if response_json is None:
                                        print(f"⚠ Response JSON parsing failed for eval id {lngid} [{strevallang}]")
                                        break

                                    break

                                if response is None or response_json is None or (response is not None and response.status_code >= 400):
                                    continue
                                response_text = json.dumps(response_json, ensure_ascii=False)
                                print("FastAPI text2sql response received")
                                print(response_json)
                                # check if the api_version field is equal to strapiversioneval
                                if response_json['api_version'] != strapiversioneval:
                                    print("API version mismatch; queried: ", response_json['api_version'], " expected: ", strapiversioneval)
                                    intconfigerror = True
                                if response_json['llm_model_entity_extraction'] != strentityextractionmodeleval:
                                    print("API llm_model_entity_extraction mismatch; queried: ", response_json['llm_model_entity_extraction'], " expected: ", strentityextractionmodeleval)
                                    intconfigerror = True
                                if response_json['llm_model_text2sql'] != strtext2sqlmodeleval:
                                    print("API llm_model_text2sql mismatch; queried: ", response_json['llm_model_text2sql'], " expected: ", strtext2sqlmodeleval)
                                    intconfigerror = True
                                response_llm_model_complex = response_json.get('llm_model_complex')
                                if response_llm_model_complex is not None and response_llm_model_complex != strcomplexmodeleval:
                                    print("API llm_model_complex mismatch; queried: ", response_llm_model_complex, " expected: ", strcomplexmodeleval)
                                    intconfigerror = True
                                if intconfigerror:
                                    # We stop now so we do not consume tokens and money because there is a configuration error
                                    exit()
                                # Store one execution row for this (question, lang) pair
                                arrevalexeccouples = {}
                                arrevalexeccouples["ID_T2S_EVALUATION"] = lngid
                                arrevalexeccouples["API_VERSION"] = strapiversionevalformatted
                                arrevalexeccouples["ENTITY_EXTRACTION_MODEL"] = strentityextractionmodeleval
                                arrevalexeccouples["TEXT2SQL_MODEL"] = strtext2sqlmodeleval
                                arrevalexeccouples["COMPLEX_MODEL"] = strcomplexmodeleval
                                arrevalexeccouples["JSON_RESULT"] = response_text
                                arrevalexeccouples["TIM_EXECUTION"] = strdatnow
                                arrevalexeccouples["LANG"] = strevallang
                                strsqltablename = "T_WC_T2S_EVALUATION_EXECUTION"
                                strsqlupdatecondition = f"ID_T2S_EVALUATION = {lngid} AND API_VERSION = '{strapiversionevalformatted}' AND ENTITY_EXTRACTION_MODEL = '{strentityextractionmodeleval}' AND TEXT2SQL_MODEL = '{strtext2sqlmodeleval}' AND COMPLEX_MODEL = '{strcomplexmodeleval}' AND LANG = '{strevallang}'"
                                cp.f_sqlupdatearray(strsqltablename,arrevalexeccouples,strsqlupdatecondition,1)
                        elif intindex == 20:
                            # Processing evaluations results to compute the scoring
                            strassertions_entity_extraction = row.get('ASSERTIONS_ENTITY_EXTRACTION')
                            strassertions_sql_query = row.get('ASSERTIONS_SQL_QUERY')
                            strassertions_query_result = row.get('ASSERTIONS_QUERY_RESULT')
                            #print("ASSERTIONS_ENTITY_EXTRACTION:", strassertions_entity_extraction)

                            response_text = row['JSON_RESULT']
                            response_json = t2s_eval.safe_json_loads(response_text)
                            print("question:", response_json['question'])
                            #print("sql_query:", response_json['sql_query'])
                            """
                            # enum response_json["result"] and display all values in a tabular way
                            for resultrow in response_json["result"]:
                                if isinstance(resultrow, dict):
                                    result_index = resultrow.get("index")
                                    result_data = resultrow.get("data")
                                else:
                                    result_index = None
                                    result_data = resultrow
                                print(f"index={result_index} | {t2s_eval.format_single_line_record(result_data)}")
                            """
                            result_rows = response_json.get("result", [])
                            df_results = pd.DataFrame([
                                (r.get("data") if isinstance(r, dict) else r)
                                for r in result_rows
                            ])
                            if all(isinstance(r, dict) and "index" in r for r in result_rows):
                                df_results.index = [r["index"] for r in result_rows]
                            print(df_results)

                            detailed_results = []
                            detailed_results_string = ""
                            status = "SKIPPED"
                            assertions_result_score = None

                            if strassertions_query_result is not None and str(strassertions_query_result).strip() != "":
                                strassertions_query_result = html.unescape(str(strassertions_query_result).strip())
                                evaluation_result, detailed_results = t2s_eval.evaluate_dataframe_assertions(df_results, strassertions_query_result)
                                status = "PASS ✓" if evaluation_result else "FAIL ✗"
                                assertions_result_score = 1 if evaluation_result else 0
                                # Format detailed results for database storage
                                detailed_results_string = t2s_eval.format_detailed_results_for_db(detailed_results, evaluation_result)
                            else:
                                detailed_results_string = "OVERALL: SKIPPED\nReason: ASSERTIONS_QUERY_RESULT is empty"

                            # === SQL query regex evaluation (ASSERTIONS_SQL_QUERY) ===
                            assertions_sql_query_score = None
                            assertions_sql_query_details_lines = []
                            sql_query_value = (response_json or {}).get("sql_query")
                            sql_query_value = (sql_query_value or "").strip() if isinstance(sql_query_value, str) else ""

                            if strassertions_sql_query is not None and str(strassertions_sql_query).strip() != "":
                                strassertions_sql_query = html.unescape(str(strassertions_sql_query).strip())
                                pattern = str(strassertions_sql_query).strip()
                                if sql_query_value == "":
                                    assertions_sql_query_score = 0
                                    assertions_sql_query_details_lines.append("ASSERTIONS_SQL_QUERY: FAIL")
                                    assertions_sql_query_details_lines.append(f"Regex: {pattern}")
                                    assertions_sql_query_details_lines.append("Reason: sql_query is missing or empty in JSON_RESULT")
                                else:
                                    try:
                                        matched = re.search(pattern, sql_query_value) is not None
                                        assertions_sql_query_score = 1 if matched else 0
                                        assertions_sql_query_details_lines.append(
                                            f"ASSERTIONS_SQL_QUERY: {'PASS' if matched else 'FAIL'}"
                                        )
                                        assertions_sql_query_details_lines.append(f"Regex: {pattern}")
                                        assertions_sql_query_details_lines.append(f"SQL query: {sql_query_value}")
                                    except re.error as e:
                                        assertions_sql_query_score = 0
                                        assertions_sql_query_details_lines.append("ASSERTIONS_SQL_QUERY: FAIL")
                                        assertions_sql_query_details_lines.append(f"Regex: {pattern}")
                                        assertions_sql_query_details_lines.append(f"Regex error: {str(e)}")

                            if assertions_sql_query_score is not None:
                                detailed_results_string = (
                                    detailed_results_string
                                    + "\n\n"
                                    + "\n".join(assertions_sql_query_details_lines)
                                )

                            # === Entity extraction evaluation (ASSERTIONS_ENTITY_EXTRACTION) ===
                            assertions_entity_extraction_score = None
                            assertions_entity_extraction_details_lines = []
                            entity_extraction_value = (response_json or {}).get("entity_extraction")

                            if strassertions_entity_extraction is not None and str(strassertions_entity_extraction).strip() != "":
                                strassertions_entity_extraction = html.unescape(str(strassertions_entity_extraction).strip())
                                if isinstance(entity_extraction_value, dict) and len(entity_extraction_value) > 0:
                                    try:
                                        ee_ok = ee_eval.ee_eval_two_layer(entity_extraction_value, strassertions_entity_extraction)
                                        assertions_entity_extraction_score = 1 if ee_ok else 0
                                        assertions_entity_extraction_details_lines.append(
                                            f"ASSERTIONS_ENTITY_EXTRACTION: {'PASS' if ee_ok else 'FAIL'}"
                                        )
                                    except Exception as e:
                                        assertions_entity_extraction_score = 0
                                        assertions_entity_extraction_details_lines.append("ASSERTIONS_ENTITY_EXTRACTION: FAIL")
                                        assertions_entity_extraction_details_lines.append(f"Error: {str(e)}")
                                else:
                                    # Assertion provided but entity_extraction missing from JSON_RESULT: do not evaluate
                                    assertions_entity_extraction_score = None
                                    assertions_entity_extraction_details_lines.append("ASSERTIONS_ENTITY_EXTRACTION: SKIPPED")
                                    assertions_entity_extraction_details_lines.append("Reason: entity_extraction dict is missing or empty in JSON_RESULT")

                            if len(assertions_entity_extraction_details_lines) > 0:
                                detailed_results_string = (
                                    detailed_results_string
                                    + "\n\n"
                                    + "\n".join(assertions_entity_extraction_details_lines)
                                )
                            
                            print(f"\n{'='*40}")
                            print(f"Evaluation Result: {status}")
                            print(f"{'='*40}")
                            print(f"\nAssertions on result set: {strassertions_query_result}")
                            print(f"DataFrame shape: {df_results.shape[0]} rows, {df_results.shape[1]} columns")
                            
                            # Display detailed results for each assertion
                            print(f"\n{'='*40}")
                            print("Detailed Results:")
                            print(f"{'='*40}")
                            for i, result in enumerate(detailed_results, 1):
                                status_symbol = "✓" if result["passed"] else "✗"
                                status_text = "PASS" if result["passed"] else "FAIL"
                                print(f"\nAssertion #{i}: {status_symbol} {status_text}")
                                print(f"  Statement: {result.get('assertion', 'N/A')}")
                                print(f"  Message: {result['message']}")
                                if not result["passed"]:
                                    if 'expected' in result:
                                        print(f"  Expected: {result['expected']}")
                                    if 'actual' in result:
                                        print(f"  Actual: {result['actual']}")
                                    if 'error' in result:
                                        print(f"  Error: {result['error']}")
                            print(f"\n{'='*40}\n")
                            # === END NEW EVALUATION SYSTEM ===

                            if assertions_result_score is not None:
                                dblcumulatedscore += assertions_result_score
                                dblevalcount += 1
                            #Store to the database
                            arrevalexeccouples = {}
                            arrevalexeccouples["ID_ROW"] = lngid
                            arrevalexeccouples["ASSERTIONS_SQL_QUERY_SCORE"] = assertions_sql_query_score
                            arrevalexeccouples["ASSERTIONS_ENTITY_EXTRACTION_SCORE"] = assertions_entity_extraction_score
                            arrevalexeccouples["ASSERTIONS_RESULT_SCORE"] = assertions_result_score
                            # Compute total score across available (non-null) assertion scores
                            scores_for_total = []
                            if assertions_result_score is not None:
                                scores_for_total.append(assertions_result_score)
                            if assertions_sql_query_score is not None:
                                scores_for_total.append(assertions_sql_query_score)
                            if assertions_entity_extraction_score is not None:
                                scores_for_total.append(assertions_entity_extraction_score)
                            if len(scores_for_total) > 0:
                                assertions_total_score = 1 if all(s == 1 for s in scores_for_total) else 0
                                arrevalexeccouples["ASSERTIONS_TOTAL_SCORE"] = assertions_total_score
                            arrevalexeccouples["ASSERTIONS_RESULT_DETAILED"] = detailed_results_string  # NEW: Store detailed results
                            def _safe_float(v):
                                """Convert optional timing values to floats while preserving ``None``."""
                                try:
                                    if v is None:
                                        return None
                                    return float(v)
                                except (TypeError, ValueError):
                                    return None

                            arrevalexeccouples["ENTITY_EXTRACTION_PROCESSING_TIME"] = _safe_float(
                                (response_json or {}).get("entity_extraction_processing_time")
                            )
                            arrevalexeccouples["TEXT2SQL_PROCESSING_TIME"] = _safe_float(
                                (response_json or {}).get("text2sql_processing_time")
                            )
                            arrevalexeccouples["EMBEDDINGS_PROCESSING_TIME"] = _safe_float(
                                (response_json or {}).get("embeddings_processing_time")
                            )
                            arrevalexeccouples["QUERY_EXECUTION_TIME"] = _safe_float(
                                (response_json or {}).get("query_execution_time")
                            )
                            arrevalexeccouples["TOTAL_PROCESSING_TIME"] = _safe_float(
                                (response_json or {}).get("total_processing_time")
                            )

                            if arrevalexeccouples["ENTITY_EXTRACTION_PROCESSING_TIME"] is not None:
                                dbl_entity_extraction_processing_time_sum += arrevalexeccouples["ENTITY_EXTRACTION_PROCESSING_TIME"]
                                lng_entity_extraction_processing_time_count += 1
                            if arrevalexeccouples["TEXT2SQL_PROCESSING_TIME"] is not None:
                                dbl_text2sql_processing_time_sum += arrevalexeccouples["TEXT2SQL_PROCESSING_TIME"]
                                lng_text2sql_processing_time_count += 1
                            if arrevalexeccouples["EMBEDDINGS_PROCESSING_TIME"] is not None:
                                dbl_embeddings_processing_time_sum += arrevalexeccouples["EMBEDDINGS_PROCESSING_TIME"]
                                lng_embeddings_processing_time_count += 1
                            if arrevalexeccouples["QUERY_EXECUTION_TIME"] is not None:
                                dbl_query_execution_time_sum += arrevalexeccouples["QUERY_EXECUTION_TIME"]
                                lng_query_execution_time_count += 1
                            if arrevalexeccouples["TOTAL_PROCESSING_TIME"] is not None:
                                dbl_total_processing_time_sum += arrevalexeccouples["TOTAL_PROCESSING_TIME"]
                                lng_total_processing_time_count += 1
                            #print("\nArrmoviecouples:")
                            #print(arrevalexeccouples)
                            #time.sleep(5)
                            strsqltablename = "T_WC_T2S_EVALUATION_EXECUTION"
                            strsqlupdatecondition = f"ID_ROW = {lngid} "
                            cp.f_sqlupdatearray(strsqltablename,arrevalexeccouples,strsqlupdatecondition,1)
                            print("*" * 40)
                        elif intindex == 30:
                            # Export evaluation category to JSON: evalcatid_englishDescription.json
                            strdescription = html.unescape((row.get('DESCRIPTION') or "").strip())
                            strdescription_fr = html.unescape((row.get('DESCRIPTION_FR') or "").strip())
                            slug = slug_for_filename(strdescription)
                            filename = f"{lngid}_{slug}.json"
                            output_dir = ensure_export_dir("evaluation_category")
                            if output_dir is None:
                                lng_export_errors += 1
                            else:
                                payload = {
                                    "evaluation_category_id": lngid,
                                    "description": strdescription or None,
                                    "description_fr": strdescription_fr or None,
                                    "lang": row.get('LANG'),
                                    "id_parent": row.get('ID_PARENT'),
                                    "comment": (row.get('LONG_DESC') or "").strip() or None,
                                    "keywords": (row.get('MOT_CLE') or "").strip() or None,
                                    "keywords_auto": (row.get('MOT_CLE_AUTO') or "").strip() or None,
                                    "display_order": row.get('DISPLAY_ORDER'),
                                    "dat_creat": row.get('DAT_CREAT'),
                                    "tim_updated": row.get('TIM_UPDATED'),
                                }
                                outcome = write_json_if_changed(output_dir, filename, payload)
                                if outcome == "wrote":
                                    lng_export_wrote += 1
                                elif outcome == "skipped":
                                    lng_export_skipped += 1
                                else:
                                    lng_export_errors += 1
                        elif intindex == 31:
                            # Export evaluation to JSON: evalid_evalcatid_englishDescription.json
                            strquestion_en = html.unescape((row.get('QUESTION') or "").strip())
                            strquestion_fr = html.unescape((row.get('QUESTION_FR') or "").strip())
                            evalcatid = row.get('ID_T2S_EVALUATION_CATEGORY')
                            slug_source = strquestion_en or strquestion_fr
                            slug = slug_for_filename(slug_source)
                            evalcatid_part = str(evalcatid) if evalcatid is not None else "0"
                            filename = f"{lngid}_{evalcatid_part}_{slug}.json"
                            output_dir = ensure_export_dir("evaluation")
                            if output_dir is None:
                                lng_export_errors += 1
                            else:
                                payload = {
                                    "evaluation_id": lngid,
                                    "evaluation_category_id": evalcatid,
                                    "question_en": strquestion_en or None,
                                    "question_fr": strquestion_fr or None,
                                    "translation_note": QUESTION_TRANSLATION_NOTE,
                                    "assertions": {
                                        "entity_extraction": (row.get('ASSERTIONS_ENTITY_EXTRACTION') or "").strip() or None,
                                        "sql_query": (row.get('ASSERTIONS_SQL_QUERY') or "").strip() or None,
                                        "query_result": (row.get('ASSERTIONS_QUERY_RESULT') or "").strip() or None,
                                    },
                                    "comment": (row.get('LONG_DESC') or "").strip() or None,
                                    "keywords": (row.get('MOT_CLE') or "").strip() or None,
                                    "keywords_auto": (row.get('MOT_CLE_AUTO') or "").strip() or None,
                                    "is_eval": row.get('IS_EVAL'),
                                    "is_sample": row.get('IS_SAMPLE'),
                                    "display_order": row.get('DISPLAY_ORDER'),
                                    "dat_creat": row.get('DAT_CREAT'),
                                    "tim_updated": row.get('TIM_UPDATED'),
                                }
                                outcome = write_json_if_changed(output_dir, filename, payload)
                                if outcome == "wrote":
                                    lng_export_wrote += 1
                                elif outcome == "skipped":
                                    lng_export_skipped += 1
                                else:
                                    lng_export_errors += 1
                        elif intindex == 32:
                            # Export execution row to JSON:
                            # YYYYMMDD_evalid_maj.min.rel_lang_eemodel_t2smodel_complexmodel.json
                            eval_id = row.get('ID_T2S_EVALUATION')
                            api_version_formatted = row.get('API_VERSION') or strapiversionevalformatted
                            row_lang = row.get('LANG') or ""
                            ee_model = row.get('ENTITY_EXTRACTION_MODEL') or ""
                            t2s_model = row.get('TEXT2SQL_MODEL') or ""
                            complex_model = row.get('COMPLEX_MODEL') or ""
                            tim_execution = row.get('TIM_EXECUTION')
                            if isinstance(tim_execution, (datetime, date)):
                                date_str = tim_execution.strftime("%Y%m%d")
                            else:
                                dat_creat = row.get('DAT_CREAT')
                                if isinstance(dat_creat, (datetime, date)):
                                    date_str = dat_creat.strftime("%Y%m%d")
                                else:
                                    date_str = datetime.now(cp.paris_tz).strftime("%Y%m%d")

                            ee_slug = slug_for_filename(ee_model, max_len=40)
                            t2s_slug = slug_for_filename(t2s_model, max_len=40)
                            complex_slug = slug_for_filename(complex_model, max_len=40)

                            run_subfolder = (
                                f"{api_version_formatted}_{row_lang}_"
                                f"{ee_slug}_{t2s_slug}_{complex_slug}"
                            )
                            filename = (
                                f"{date_str}_{eval_id}_{api_version_formatted}_{row_lang}_"
                                f"{ee_slug}_{t2s_slug}_{complex_slug}.json"
                            )
                            output_dir = ensure_export_dir(
                                os.path.join("evaluation_execution", run_subfolder)
                            )
                            if output_dir is None:
                                lng_export_errors += 1
                            else:
                                json_result_text = row.get('JSON_RESULT') or ""
                                api_output = None
                                if json_result_text:
                                    try:
                                        api_output = t2s_eval.safe_json_loads(json_result_text)
                                    except Exception as e:
                                        print(f"⚠ Cannot parse JSON_RESULT for execution row {lngid}: {e}")
                                        api_output = {"_parse_error": str(e), "_raw_truncated": json_result_text[:500]}

                                # Backfill complex_model_used for evaluations run before the API
                                # exposed this flag (e.g. 1.1.15). Detect from messages: every
                                # complex-retry path emits a message containing "stronger model".
                                if isinstance(api_output, dict) and api_output.get("complex_model_used") is None:
                                    derived_used = False
                                    for msg in (api_output.get("messages") or []):
                                        msg_text = (msg or {}).get("text") if isinstance(msg, dict) else None
                                        if isinstance(msg_text, str) and "stronger model" in msg_text.lower():
                                            derived_used = True
                                            break
                                    api_output["complex_model_used"] = derived_used
                                payload = {
                                    "evaluation_id": eval_id,
                                    "execution_row_id": lngid,
                                    "language": row_lang,
                                    "api_input": {
                                        "api_version": api_version_formatted,
                                        "entity_extraction_model": ee_model,
                                        "text2sql_model": t2s_model,
                                        "complex_model": complex_model,
                                        "ui_language": row_lang,
                                    },
                                    "api_output": api_output,
                                    "scoring": {
                                        "assertions_entity_extraction_score": row.get('ASSERTIONS_ENTITY_EXTRACTION_SCORE'),
                                        "assertions_sql_query_score": row.get('ASSERTIONS_SQL_QUERY_SCORE'),
                                        "assertions_result_score": row.get('ASSERTIONS_RESULT_SCORE'),
                                        "assertions_total_score": row.get('ASSERTIONS_TOTAL_SCORE'),
                                        "assertions_result_detailed": row.get('ASSERTIONS_RESULT_DETAILED'),
                                    },
                                    "timings": {
                                        "entity_extraction_processing_time": row.get('ENTITY_EXTRACTION_PROCESSING_TIME'),
                                        "text2sql_processing_time": row.get('TEXT2SQL_PROCESSING_TIME'),
                                        "embeddings_processing_time": row.get('EMBEDDINGS_PROCESSING_TIME'),
                                        "query_execution_time": row.get('QUERY_EXECUTION_TIME'),
                                        "total_processing_time": row.get('TOTAL_PROCESSING_TIME'),
                                    },
                                    "tim_execution": tim_execution,
                                    "tim_updated": row.get('TIM_UPDATED'),
                                }
                                outcome = write_json_if_changed(output_dir, filename, payload)
                                if outcome == "wrote":
                                    lng_export_wrote += 1
                                elif outcome == "skipped":
                                    lng_export_skipped += 1
                                else:
                                    lng_export_errors += 1

                        lngcount += 1
                        cp.f_setservervariable("strtext2sqlevalprocess"+str(intindex)+strdescvarname+"count",str(lngcount),"Count of rows processed for process "+str(intindex)+" : "+strdesc+"",0)
                        strnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
                        cp.f_setservervariable("strtext2sqlevaldatetime",strnow,"Date and time of the last crawled record using the TMDb API",0)
                if intindex in (30, 31, 32):
                    print(
                        f"Export summary (process {intindex}): "
                        f"wrote={lng_export_wrote}, skipped={lng_export_skipped}, errors={lng_export_errors}"
                    )
                print("------------------------------------------")
            print("------------------------------------------")
            strcurrentprocess = ""
            cp.f_setservervariable("strtext2sqlevalcurrentprocess",strcurrentprocess,"Current process in the Text2SQL evaluation",0)
            strnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
            cp.f_setservervariable("strtext2sqlevalenddatetime",strnow,"Date and time of the Text2SQL evaluation ending",0)
            # Calculate total runtime and convert to readable format
            end_time = time.time()
            strtotalruntime = int(end_time - start_time)  # Total runtime in seconds
            cp.f_setservervariable("strtext2sqlevaltotalruntimeseconds",str(strtotalruntime),strtotalruntimedesc,0)
            readable_duration = cp.convert_seconds_to_duration(strtotalruntime)
            cp.f_setservervariable("strtext2sqlevaltotalruntime",readable_duration,strtotalruntimedesc,0)
            print(f"Total runtime: {strtotalruntime} seconds ({readable_duration})")

            # Global-score summary — printed last so it stays at the bottom of the
            # script output regardless of which processes ran in arrprocessscope.
            # Gated on dblevalcount > 0: skipped silently when process 20 was not
            # in scope or had no scored rows.
            if dblevalcount > 0:
                dblglobalscore = dblcumulatedscore / dblevalcount
                print("==========================================")
                print("Global score summary")
                print("==========================================")
                print(f"FastAPI Text2SQL API version: {strapiversioneval}")
                print(f"Entity extraction model: {strentityextractionmodeleval}")
                print(f"Text2SQL model: {strtext2sqlmodeleval}")
                print(f"Complex model: {strcomplexmodeleval}")
                print(f"Language: {strlanguage}")
                print(f"Store to cache: {blnstoretocache}")
                print(f"Complex model used input: {blncomplexmodelused}")
                print(f"Global score: {dblcumulatedscore}/{dblevalcount} = {dblglobalscore:.2%}")
                if lng_entity_extraction_processing_time_count > 0:
                    str_entity_extraction_processing_time_sum_duration = cp.convert_seconds_to_duration(
                        int(dbl_entity_extraction_processing_time_sum)
                    )
                    print(
                        f"Sum entity_extraction_processing_time: "
                        f"{dbl_entity_extraction_processing_time_sum:.3f}s "
                        f"({str_entity_extraction_processing_time_sum_duration}) "
                        f"(n={lng_entity_extraction_processing_time_count})"
                    )
                if lng_entity_extraction_processing_time_count > 0:
                    print(
                        f"Avg entity_extraction_processing_time: "
                        f"{dbl_entity_extraction_processing_time_sum / lng_entity_extraction_processing_time_count:.3f}s "
                        f"(n={lng_entity_extraction_processing_time_count})"
                    )
                if lng_text2sql_processing_time_count > 0:
                    str_text2sql_processing_time_sum_duration = cp.convert_seconds_to_duration(
                        int(dbl_text2sql_processing_time_sum)
                    )
                    print(
                        f"Sum text2sql_processing_time: "
                        f"{dbl_text2sql_processing_time_sum:.3f}s "
                        f"({str_text2sql_processing_time_sum_duration}) "
                        f"(n={lng_text2sql_processing_time_count})"
                    )
                if lng_text2sql_processing_time_count > 0:
                    print(
                        f"Avg text2sql_processing_time: "
                        f"{dbl_text2sql_processing_time_sum / lng_text2sql_processing_time_count:.3f}s "
                        f"(n={lng_text2sql_processing_time_count})"
                    )
                if lng_embeddings_processing_time_count > 0:
                    str_embeddings_processing_time_sum_duration = cp.convert_seconds_to_duration(
                        int(dbl_embeddings_processing_time_sum)
                    )
                    print(
                        f"Sum embeddings_processing_time: "
                        f"{dbl_embeddings_processing_time_sum:.3f}s "
                        f"({str_embeddings_processing_time_sum_duration}) "
                        f"(n={lng_embeddings_processing_time_count})"
                    )
                if lng_embeddings_processing_time_count > 0:
                    print(
                        f"Avg embeddings_processing_time: "
                        f"{dbl_embeddings_processing_time_sum / lng_embeddings_processing_time_count:.3f}s "
                        f"(n={lng_embeddings_processing_time_count})"
                    )
                if lng_query_execution_time_count > 0:
                    str_query_execution_time_sum_duration = cp.convert_seconds_to_duration(
                        int(dbl_query_execution_time_sum)
                    )
                    print(
                        f"Sum query_execution_time: "
                        f"{dbl_query_execution_time_sum:.3f}s "
                        f"({str_query_execution_time_sum_duration}) "
                        f"(n={lng_query_execution_time_count})"
                    )
                if lng_query_execution_time_count > 0:
                    print(
                        f"Avg query_execution_time: "
                        f"{dbl_query_execution_time_sum / lng_query_execution_time_count:.3f}s "
                        f"(n={lng_query_execution_time_count})"
                    )
                if lng_total_processing_time_count > 0:
                    str_total_processing_time_sum_duration = cp.convert_seconds_to_duration(
                        int(dbl_total_processing_time_sum)
                    )
                    print(
                        f"Sum total_processing_time: "
                        f"{dbl_total_processing_time_sum:.3f}s "
                        f"({str_total_processing_time_sum_duration}) "
                        f"(n={lng_total_processing_time_count})"
                    )
                if lng_total_processing_time_count > 0:
                    print(
                        f"Avg total_processing_time: "
                        f"{dbl_total_processing_time_sum / lng_total_processing_time_count:.3f}s "
                        f"(n={lng_total_processing_time_count})"
                    )
    print("Process completed")
except pymysql.MySQLError as e:
    print(f"❌ MySQL Error: {e}")
    conn = getattr(cp, "connectioncp", None)
    if conn is not None and getattr(conn, "open", False):
        conn.rollback()
