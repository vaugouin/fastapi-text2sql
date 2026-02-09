import time
import requests
import pymysql.cursors
import json
import citizenphil as cp
from datetime import datetime, timedelta
import shutil
import os
from urllib.parse import urlparse
from dotenv import load_dotenv
import pandas as pd
import pytest
import re

from text2sql_eval_functions import (
    evaluate_dataframe_assertions,
    format_api_version,
    format_detailed_results_for_db,
    format_single_line_record,
    safe_json_loads,
)

# Load environment variables from .env file
load_dotenv()

datnow = datetime.now(cp.paris_tz)
# Compute the date and time for J-1 (yesterday)
# So we are sure to find the TMDb Id export files for this day
delta = timedelta(days=1)
datjminus1 = datnow - delta
#strdatjminus1 = datjminus1.strftime("%Y-%m-%d %H:%M:%S")
strdattodayminus1 = datjminus1.strftime("%Y-%m-%d")
strdattodayminus1us = datjminus1.strftime("%m_%d_%Y")

try:
    with cp.connectioncp:
        with cp.connectioncp.cursor() as cursor:
            cursor3 = cp.connectioncp.cursor()
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
            strtotalruntime = ""
            cp.f_setservervariable("strtext2sqlevaltotalruntime",strtotalruntime,strtotalruntimedesc,0)
            
            #arrprocessscope = {11: 'run evals'}
            #arrprocessscope = {12: 'process evals'}
            arrprocessscope = {11: 'run evals', 12: 'process evals'}
            strrunevalidold = cp.f_getservervariable("strtext2sqlevalrunevalid",0)
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
                strentityextractionmodeleval = "gpt-4o"
                strtext2sqlmodeleval = "gpt-4o"
                #strentityextractionmodeleval = "newmodel"
                #strtext2sqlmodeleval = "newmodel"
                strapiversioneval = "1.1.14"
                #strapiversioneval = "1.1.15"
                strapiversionevalformatted = format_api_version(strapiversioneval)
                lngrowsperpageeval = 100
                if intindex == 11:
                    # Running evaluations on the FastAPI text2SQL API 
                    strcurrentprocess = f"{intindex}: running evaluations on the FastAPI text2SQL API "
                    strsql = ""
                    strsql += "SELECT ID_T2S_EVALUATION AS id, QUESTION "
                    strsql += "FROM T_WC_T2S_EVALUATION "
                    strsql += "WHERE IS_EVAL = 1 "
                    strsql += "AND DELETED = 0 "
                    strsql += "AND ASSERTIONS <> '' "
                    strsql += "AND ASSERTIONS IS NOT NULL "
                    strsql += "AND ID_T2S_EVALUATION NOT IN ( "
                    strsql += "SELECT T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION "
                    strsql += "FROM T_WC_T2S_EVALUATION_EXECUTION "
                    strsql += "WHERE T_WC_T2S_EVALUATION_EXECUTION.DELETED = 0 "
                    strsql += "AND API_VERSION = '" + strapiversionevalformatted + "' AND ENTITY_EXTRACTION_MODEL = '" + strentityextractionmodeleval + "' AND TEXT2SQL_MODEL = '" + strtext2sqlmodeleval + "' "
                    strsql += ") "
                    #strrunevalidold = "486"
                    if strrunevalidold != "":
                        strsql += "AND ID_T2S_EVALUATION >= " + strrunevalidold + " "
                    strsql += "ORDER BY ID_T2S_EVALUATION ASC "
                    #strsql += "LIMIT 80 "
                    #strsql += "LIMIT 20000 "
                elif intindex == 12:
                    # Processing evaluations results to compute the scoring
                    strcurrentprocess = f"{intindex}: processing evaluations to compute the results "
                    strsql = ""
                    strsql += "SELECT T_WC_T2S_EVALUATION_EXECUTION.ID_ROW AS id, T_WC_T2S_EVALUATION_EXECUTION.JSON_RESULT, T_WC_T2S_EVALUATION.ASSERTIONS "
                    strsql += "FROM T_WC_T2S_EVALUATION_EXECUTION "
                    strsql += "INNER JOIN T_WC_T2S_EVALUATION ON T_WC_T2S_EVALUATION.ID_T2S_EVALUATION = T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION "
                    strsql += "WHERE T_WC_T2S_EVALUATION.DELETED = 0 "
                    strsql += "AND T_WC_T2S_EVALUATION_EXECUTION.DELETED = 0 "
                    strsql += "AND API_VERSION = '" + strapiversionevalformatted + "' AND ENTITY_EXTRACTION_MODEL = '" + strentityextractionmodeleval + "' AND TEXT2SQL_MODEL = '" + strtext2sqlmodeleval + "' "
                    #strsql += "AND T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION = 2140 "
                    #strsql += "AND T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 2139) "
                    strsql += "ORDER BY T_WC_T2S_EVALUATION_EXECUTION.ID_T2S_EVALUATION ASC "
                    #strsql += "LIMIT 5 "
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
                        if intindex == 11:
                            # Running evaluations on the FastAPI text2SQL API 
                            strquestion = row['QUESTION']
                            print(strquestion)
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

                            payload = {
                                "question": strquestion,
                                "question_hashed": None,
                                "page": 1,
                                "rows_per_page": lngrowsperpageeval,
                                "retrieve_from_cache": False,
                                "store_to_cache": True,
                                "llm_model_entity_extraction": strentityextractionmodeleval,
                                "llm_model_text2sql": strtext2sqlmodeleval,
                            }
                            print(url)
                            print(payload)
                            strdatnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
                            response = requests.post(url, headers=headers, json=payload, timeout=120)
                            response.raise_for_status()
                            response_json = response.json()
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
                            if intconfigerror:
                                # We stop now so we do not consume tokens and money because there is a configuration error
                                exit()
                            #Store to the database
                            arrevalexeccouples = {}
                            arrevalexeccouples["ID_T2S_EVALUATION"] = lngid
                            arrevalexeccouples["API_VERSION"] = strapiversionevalformatted
                            arrevalexeccouples["ENTITY_EXTRACTION_MODEL"] = strentityextractionmodeleval
                            arrevalexeccouples["TEXT2SQL_MODEL"] = strtext2sqlmodeleval
                            arrevalexeccouples["JSON_RESULT"] = response_text
                            arrevalexeccouples["TIM_EXECUTION"] = strdatnow
                            #print("\nArrmoviecouples:")
                            #print(arrevalexeccouples)
                            #time.sleep(5)
                            strsqltablename = "T_WC_T2S_EVALUATION_EXECUTION"
                            strsqlupdatecondition = f"ID_T2S_EVALUATION = {lngid} AND API_VERSION = '{strapiversionevalformatted}' AND ENTITY_EXTRACTION_MODEL = '{strentityextractionmodeleval}' AND TEXT2SQL_MODEL = '{strtext2sqlmodeleval}'"
                            cp.f_sqlupdatearray(strsqltablename,arrevalexeccouples,strsqlupdatecondition,1)
                        elif intindex == 12:
                            # Processing evaluations results to compute the scoring
                            strassertions = row['ASSERTIONS']
                            response_text = row['JSON_RESULT']
                            response_json = safe_json_loads(response_text)
                            print("question:", response_json['question'])
                            #print("sql_query:", response_json['sql_query'])
                            #print("assertions:", strassertions)
                            """
                            # enum response_json["result"] and display all values in a tabular way
                            for resultrow in response_json["result"]:
                                if isinstance(resultrow, dict):
                                    result_index = resultrow.get("index")
                                    result_data = resultrow.get("data")
                                else:
                                    result_index = None
                                    result_data = resultrow
                                print(f"index={result_index} | {format_single_line_record(result_data)}")
                            """
                            result_rows = response_json.get("result", [])
                            df_results = pd.DataFrame([
                                (r.get("data") if isinstance(r, dict) else r)
                                for r in result_rows
                            ])
                            if all(isinstance(r, dict) and "index" in r for r in result_rows):
                                df_results.index = [r["index"] for r in result_rows]
                            print(df_results)

                            evaluation_result, detailed_results = evaluate_dataframe_assertions(df_results, strassertions)
                            status = "PASS ✓" if evaluation_result else "FAIL ✗"
                            assertions_result_score = 1 if evaluation_result else 0
                            
                            # Format detailed results for database storage
                            detailed_results_string = format_detailed_results_for_db(detailed_results, evaluation_result)
                            
                            print(f"\n{'='*80}")
                            print(f"Evaluation Result: {status}")
                            print(f"{'='*80}")
                            print(f"\nAssertions: {strassertions}")
                            print(f"DataFrame shape: {df_results.shape[0]} rows, {df_results.shape[1]} columns")
                            
                            # Display detailed results for each assertion
                            print(f"\n{'='*80}")
                            print("Detailed Results:")
                            print(f"{'='*80}")
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
                            print(f"\n{'='*80}\n")
                            # === END NEW EVALUATION SYSTEM ===

                            dblcumulatedscore += assertions_result_score
                            dblevalcount += 1
                            #Store to the database
                            arrevalexeccouples = {}
                            arrevalexeccouples["ID_ROW"] = lngid
                            arrevalexeccouples["ASSERTIONS_RESULT_SCORE"] = assertions_result_score
                            arrevalexeccouples["ASSERTIONS_RESULT_DETAILED"] = detailed_results_string  # NEW: Store detailed results
                            def _safe_float(v):
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
                            print(f"{'*'*80}")

                        lngcount += 1
                        cp.f_setservervariable("strtext2sqlevalprocess"+str(intindex)+strdescvarname+"count",str(lngcount),"Count of rows processed for process "+str(intindex)+" : "+strdesc+"",0)
                        strnow = datetime.now(cp.paris_tz).strftime("%Y-%m-%d %H:%M:%S")
                        cp.f_setservervariable("strtext2sqlevaldatetime",strnow,"Date and time of the last crawled record using the TMDb API",0)
                print("------------------------------------------")
            strsql = ""
            if intindex == 12:
                dblglobalscore = dblcumulatedscore / dblevalcount
                print(f"FastAPI Text2SQL API version: {strapiversioneval}")
                print(f"Entity extraction model: {strentityextractionmodeleval}")
                print(f"Text2SQL model: {strtext2sqlmodeleval}")
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
    print("Process completed")
except pymysql.MySQLError as e:
    print(f"❌ MySQL Error: {e}")
    cp.connectioncp.rollback()
