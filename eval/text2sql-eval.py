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

# Convert API version to XXX.YYY.ZZZ format for comparison
def format_api_version(version: str) -> str:
    """Convert version string to XXX.YYY.ZZZ format for comparison."""
    version_parts = version.split('.')
    return f"{int(version_parts[0]):03d}.{int(version_parts[1]):03d}.{int(version_parts[2]):03d}"

def safe_json_loads(value: str):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    s = value.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find('{')
        end = s.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start:end + 1])
        raise

def format_single_line_record(record):
    if isinstance(record, str):
        s = record.strip()
        while s.endswith('}}'):
            try:
                record = json.loads(s)
                break
            except Exception:
                s = s[:-1]
        if isinstance(record, str):
            record = safe_json_loads(record)
    if isinstance(record, dict):
        return " | ".join([f"{k}={v}" for k, v in record.items()])
    return str(record)

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

                            # === NEW EVALUATION SYSTEM ===
                            # Line 249: Completely new evaluation system using df_results and strassertions
                            
                            def evaluate_dataframe_assertions(df_results: pd.DataFrame, strassertions: str) -> tuple[bool, list[dict]]:
                                """
                                Evaluate assertions against a pandas DataFrame with detailed error reporting.
                                
                                Supports:
                                - COUNT(*) operations with comparisons
                                - Column IN (values) / NOT IN (values)
                                - AND / OR logical operators
                                - Comparison operators: ==, !=, <, >, <=, >=
                                
                                Args:
                                    df_results: pandas DataFrame containing the query results
                                    strassertions: String containing SQL-like assertions
                                
                                Returns:
                                    tuple: (overall_pass: bool, results: list[dict])
                                        - overall_pass: True if all assertions pass, False otherwise
                                        - results: List of dicts with detailed results for each assertion
                                """
                                results = []
                                
                                if not strassertions or not strassertions.strip():
                                    return True, [{"passed": True, "message": "No assertions to evaluate"}]
                                
                                if df_results is None or df_results.empty:
                                    # Check if assertions allow empty results
                                    if "COUNT(*)" in strassertions and "== 0" in strassertions:
                                        return True, [{"passed": True, "assertion": strassertions, "message": "Empty DataFrame as expected"}]
                                    return False, [{
                                        "passed": False,
                                        "assertion": strassertions,
                                        "message": "DataFrame is empty but assertions expect data",
                                        "actual": "0 rows",
                                        "expected": "Non-empty DataFrame"
                                    }]
                                
                                try:
                                    # Split by AND/OR but keep track of the operators
                                    assertions_str = strassertions.strip()
                                    
                                    # Split by AND/OR while preserving the operators
                                    parts = re.split(r'\s+(AND|OR)\s+', assertions_str, flags=re.IGNORECASE)
                                    
                                    # Process parts: odd indices are operators, even indices are assertions
                                    assertions_list = []
                                    operators_list = []
                                    
                                    for i, part in enumerate(parts):
                                        part_stripped = part.strip()
                                        if i % 2 == 0:  # Assertion
                                            # Remove outer parentheses if they wrap the entire assertion
                                            if part_stripped.startswith('(') and part_stripped.endswith(')'):
                                                part_stripped = part_stripped[1:-1].strip()
                                            assertions_list.append(part_stripped)
                                        else:  # Operator (AND/OR)
                                            operators_list.append(part_stripped.upper())
                                    
                                    # Evaluate each assertion
                                    assertion_results = []
                                    for assertion in assertions_list:
                                        result = _evaluate_single_assertion(df_results, assertion)
                                        assertion_results.append(result)
                                        results.append(result)
                                    
                                    # Apply logical operators
                                    if not assertion_results:
                                        return True, [{"passed": True, "message": "No assertions to evaluate"}]
                                    
                                    # Calculate overall result
                                    bool_results = [r["passed"] for r in assertion_results]
                                    final_result = bool_results[0]
                                    for i, operator in enumerate(operators_list):
                                        if operator == 'AND':
                                            final_result = final_result and bool_results[i + 1]
                                        elif operator == 'OR':
                                            final_result = final_result or bool_results[i + 1]
                                    
                                    return final_result, results
                                
                                except Exception as e:
                                    return False, [{
                                        "passed": False,
                                        "assertion": strassertions,
                                        "message": f"Error evaluating assertions: {str(e)}",
                                        "error": str(e)
                                    }]
                            
                            def _evaluate_single_assertion(df: pd.DataFrame, assertion: str) -> dict:
                                """
                                Evaluate a single assertion against the DataFrame with detailed results.
                                
                                Args:
                                    df: pandas DataFrame
                                    assertion: Single assertion string
                                
                                Returns:
                                    dict: Result with 'passed', 'assertion', 'message', 'expected', 'actual' keys
                                """
                                assertion = assertion.strip()
                                
                                # Handle COUNT(*) assertions
                                if 'COUNT(*)' in assertion.upper():
                                    return _evaluate_count_assertion(df, assertion)
                                
                                # Handle IN / NOT IN assertions
                                if ' IN ' in assertion.upper() or ' NOT IN ' in assertion.upper():
                                    return _evaluate_in_assertion(df, assertion)
                                
                                # Handle other column comparisons
                                return _evaluate_comparison_assertion(df, assertion)
                            
                            def _evaluate_count_assertion(df: pd.DataFrame, assertion: str) -> dict:
                                """Evaluate COUNT(*) assertions with detailed results."""
                                actual_count = len(df)
                                
                                # Extract the comparison pattern
                                pattern = r'COUNT\(\*\)\s*(==|!=|<=|>=|<|>)\s*(\d+)'
                                match = re.search(pattern, assertion, re.IGNORECASE)
                                
                                if not match:
                                    return {
                                        "passed": False,
                                        "assertion": assertion,
                                        "message": "Invalid COUNT(*) syntax",
                                        "error": "Could not parse COUNT(*) assertion"
                                    }
                                
                                operator = match.group(1)
                                expected_value = int(match.group(2))
                                
                                # Evaluate the comparison
                                passed = False
                                if operator == '==':
                                    passed = actual_count == expected_value
                                elif operator == '!=':
                                    passed = actual_count != expected_value
                                elif operator == '<':
                                    passed = actual_count < expected_value
                                elif operator == '>':
                                    passed = actual_count > expected_value
                                elif operator == '<=':
                                    passed = actual_count <= expected_value
                                elif operator == '>=':
                                    passed = actual_count >= expected_value
                                
                                if passed:
                                    return {
                                        "passed": True,
                                        "assertion": assertion,
                                        "message": f"Row count check passed",
                                        "expected": f"COUNT(*) {operator} {expected_value}",
                                        "actual": f"COUNT(*) = {actual_count}"
                                    }
                                else:
                                    return {
                                        "passed": False,
                                        "assertion": assertion,
                                        "message": f"Row count mismatch: Expected {operator} {expected_value}, but got {actual_count}",
                                        "expected": f"COUNT(*) {operator} {expected_value}",
                                        "actual": f"COUNT(*) = {actual_count}"
                                    }
                            
                            def _evaluate_in_assertion(df: pd.DataFrame, assertion: str) -> dict:
                                """Evaluate IN / NOT IN assertions with detailed results."""
                                is_not_in = 'NOT IN' in assertion.upper()
                                
                                if is_not_in:
                                    pattern = r'(\w+)\s+NOT\s+IN\s*\(([^)]+)\)'
                                else:
                                    pattern = r'(\w+)\s+IN\s*\(([^)]+)\)'
                                
                                match = re.search(pattern, assertion, re.IGNORECASE)
                                
                                if not match:
                                    return {
                                        "passed": False,
                                        "assertion": assertion,
                                        "message": "Invalid IN/NOT IN syntax",
                                        "error": "Could not parse IN/NOT IN assertion"
                                    }
                                
                                column_name = match.group(1).strip()
                                values_str = match.group(2).strip()
                                
                                # Check if column exists
                                if column_name not in df.columns:
                                    return {
                                        "passed": False,
                                        "assertion": assertion,
                                        "message": f"Column '{column_name}' does not exist in DataFrame",
                                        "expected": f"Column '{column_name}' to exist",
                                        "actual": f"Available columns: {', '.join(df.columns.tolist())}"
                                    }
                                
                                # Parse the values list
                                values = []
                                for val in values_str.split(','):
                                    val = val.strip()
                                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                                        val = val[1:-1]
                                    try:
                                        val = int(val)
                                    except ValueError:
                                        try:
                                            val = float(val)
                                        except ValueError:
                                            pass
                                    values.append(val)
                                
                                # Get the column values
                                column_values = df[column_name].tolist()
                                
                                # Evaluate IN / NOT IN
                                if is_not_in:
                                    # Find values that ARE in the exclusion list (violations)
                                    violations = [val for val in column_values if val in values]
                                    passed = len(violations) == 0
                                    
                                    if passed:
                                        return {
                                            "passed": True,
                                            "assertion": assertion,
                                            "message": f"All {len(column_values)} values in '{column_name}' are not in the exclusion list",
                                            "expected": f"{column_name} NOT IN ({values_str})",
                                            "actual": f"No violations found"
                                        }
                                    else:
                                        unique_violations = list(set(violations))
                                        violation_count = len(violations)
                                        return {
                                            "passed": False,
                                            "assertion": assertion,
                                            "message": f"Found {violation_count} value(s) in '{column_name}' that should NOT be in the list: {unique_violations}",
                                            "expected": f"{column_name} NOT IN ({values_str})",
                                            "actual": f"Found violations: {unique_violations} (occurred {violation_count} time(s))"
                                        }
                                else:
                                    # IN assertion: Check that ALL required values are present in the DataFrame
                                    # Extra values in DataFrame are OK
                                    missing_values = [val for val in values if val not in column_values]
                                    passed = len(missing_values) == 0
                                    
                                    unique_df_values = len(set(column_values))
                                    
                                    if passed:
                                        return {
                                            "passed": True,
                                            "assertion": assertion,
                                            "message": f"All {len(values)} required values found in '{column_name}' (DataFrame has {unique_df_values} unique values)",
                                            "expected": f"All values from IN list present in {column_name}",
                                            "actual": f"All {len(values)} required values found in DataFrame"
                                        }
                                    else:
                                        return {
                                            "passed": False,
                                            "assertion": assertion,
                                            "message": f"Missing {len(missing_values)} required value(s) in '{column_name}': {missing_values}",
                                            "expected": f"{column_name} IN ({values_str}) - all values should be present",
                                            "actual": f"Missing values: {missing_values}. Found {unique_df_values} unique values in DataFrame"
                                        }
                            
                            def _evaluate_comparison_assertion(df: pd.DataFrame, assertion: str) -> dict:
                                """Evaluate simple comparison assertions with detailed results."""
                                pattern = r'(\w+)\s*(==|!=|<=|>=|<|>)\s*(.+)'
                                match = re.match(pattern, assertion)
                                
                                if not match:
                                    return {
                                        "passed": False,
                                        "assertion": assertion,
                                        "message": "Invalid comparison syntax",
                                        "error": "Could not parse comparison assertion"
                                    }
                                
                                column_name = match.group(1).strip()
                                operator = match.group(2)
                                value_str = match.group(3).strip()
                                
                                # Check if column exists
                                if column_name not in df.columns:
                                    return {
                                        "passed": False,
                                        "assertion": assertion,
                                        "message": f"Column '{column_name}' does not exist in DataFrame",
                                        "expected": f"Column '{column_name}' to exist",
                                        "actual": f"Available columns: {', '.join(df.columns.tolist())}"
                                    }
                                
                                # Parse the value
                                value = value_str
                                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                                    value = value[1:-1]
                                try:
                                    value = int(value)
                                except ValueError:
                                    try:
                                        value = float(value)
                                    except ValueError:
                                        pass
                                
                                # Get column values
                                column_values = df[column_name].tolist()
                                
                                # Find violations
                                violations = []
                                if operator == '==':
                                    violations = [v for v in column_values if v != value]
                                    passed = len(violations) == 0
                                elif operator == '!=':
                                    violations = [v for v in column_values if v == value]
                                    passed = len(violations) == 0
                                elif operator == '<':
                                    violations = [v for v in column_values if v >= value]
                                    passed = len(violations) == 0
                                elif operator == '>':
                                    violations = [v for v in column_values if v <= value]
                                    passed = len(violations) == 0
                                elif operator == '<=':
                                    violations = [v for v in column_values if v > value]
                                    passed = len(violations) == 0
                                elif operator == '>=':
                                    violations = [v for v in column_values if v < value]
                                    passed = len(violations) == 0
                                else:
                                    return {
                                        "passed": False,
                                        "assertion": assertion,
                                        "message": f"Unknown operator '{operator}'",
                                        "error": "Unsupported comparison operator"
                                    }
                                
                                if passed:
                                    return {
                                        "passed": True,
                                        "assertion": assertion,
                                        "message": f"All {len(column_values)} values in '{column_name}' satisfy {column_name} {operator} {value}",
                                        "expected": f"{column_name} {operator} {value}",
                                        "actual": f"All values match condition"
                                    }
                                else:
                                    unique_violations = list(set(violations))
                                    violation_count = len(violations)
                                    sample_violations = unique_violations[:5]  # Show first 5 unique violations
                                    
                                    return {
                                        "passed": False,
                                        "assertion": assertion,
                                        "message": f"Found {violation_count} value(s) in '{column_name}' that violate {column_name} {operator} {value}. Sample violations: {sample_violations}",
                                        "expected": f"{column_name} {operator} {value}",
                                        "actual": f"Found {violation_count} violations: {sample_violations}{' (showing first 5)' if len(unique_violations) > 5 else ''}"
                                    }
                            
                            def format_detailed_results_for_db(detailed_results: list[dict], overall_pass: bool) -> str:
                                """
                                Format detailed assertion results into a string for database storage.
                                
                                Args:
                                    detailed_results: List of assertion result dictionaries
                                    overall_pass: Overall evaluation result
                                
                                Returns:
                                    Formatted string suitable for database storage
                                """
                                lines = []
                                lines.append(f"OVERALL: {'PASS' if overall_pass else 'FAIL'}")
                                #lines.append("="*80)
                                
                                for i, result in enumerate(detailed_results, 1):
                                    status = "PASS" if result["passed"] else "FAIL"
                                    lines.append(f"\nAssertion #{i}: [{status}]")
                                    lines.append(f"Statement: {result.get('assertion', 'N/A')}")
                                    lines.append(f"Message: {result['message']}")
                                    
                                    if not result["passed"]:
                                        if 'expected' in result:
                                            lines.append(f"Expected: {result['expected']}")
                                        if 'actual' in result:
                                            lines.append(f"Actual: {result['actual']}")
                                        if 'error' in result:
                                            lines.append(f"Error: {result['error']}")
                                
                                return "\n".join(lines)
                            
                            # Use the new evaluator
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
