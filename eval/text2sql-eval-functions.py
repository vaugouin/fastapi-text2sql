import json
import re
from typing import Any

import pandas as pd


# Convert API version to XXX.YYY.ZZZ format for comparison
def format_api_version(version: str) -> str:
    """Convert version string to XXX.YYY.ZZZ format for comparison."""
    version_parts = version.split('.')
    return f"{int(version_parts[0]):03d}.{int(version_parts[1]):03d}.{int(version_parts[2]):03d}"


def safe_json_loads(value: Any):
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
            return json.loads(s[start : end + 1])
        raise


def format_single_line_record(record: Any) -> str:
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


def evaluate_dataframe_assertions(df_results: pd.DataFrame, strassertions: str) -> tuple[bool, list[dict]]:
    """
    Evaluate assertions against a pandas DataFrame with detailed error reporting.

    Supports:
    - COUNT(*) operations with comparisons
    - CELL(row, col) for position-based single cell assertions (0-indexed)
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
    results: list[dict] = []

    if not strassertions or not strassertions.strip():
        return True, [{"passed": True, "message": "No assertions to evaluate"}]

    if df_results is None or df_results.empty:
        # Check if assertions allow empty results
        if "COUNT(*)" in strassertions and "== 0" in strassertions:
            return True, [
                {
                    "passed": True,
                    "assertion": strassertions,
                    "message": "Empty DataFrame as expected",
                }
            ]
        return False, [
            {
                "passed": False,
                "assertion": strassertions,
                "message": "DataFrame is empty but assertions expect data",
                "actual": "0 rows",
                "expected": "Non-empty DataFrame",
            }
        ]

    try:
        assertions_str = strassertions.strip()

        # Split by AND/OR while preserving the operators
        parts = re.split(r"\s+(AND|OR)\s+", assertions_str, flags=re.IGNORECASE)

        # Process parts: odd indices are operators, even indices are assertions
        assertions_list: list[str] = []
        operators_list: list[str] = []

        for i, part in enumerate(parts):
            part_stripped = part.strip()
            if i % 2 == 0:  # Assertion
                # Remove outer parentheses if they wrap the entire assertion
                if part_stripped.startswith("(") and part_stripped.endswith(")"):
                    part_stripped = part_stripped[1:-1].strip()
                assertions_list.append(part_stripped)
            else:  # Operator (AND/OR)
                operators_list.append(part_stripped.upper())

        # Evaluate each assertion
        assertion_results: list[dict] = []
        for assertion in assertions_list:
            result = _evaluate_single_assertion(df_results, assertion)
            assertion_results.append(result)
            results.append(result)

        if not assertion_results:
            return True, [{"passed": True, "message": "No assertions to evaluate"}]

        # Calculate overall result
        bool_results = [r["passed"] for r in assertion_results]
        final_result = bool_results[0]
        for i, operator in enumerate(operators_list):
            if operator == "AND":
                final_result = final_result and bool_results[i + 1]
            elif operator == "OR":
                final_result = final_result or bool_results[i + 1]

        return final_result, results

    except Exception as e:
        return False, [
            {
                "passed": False,
                "assertion": strassertions,
                "message": f"Error evaluating assertions: {str(e)}",
                "error": str(e),
            }
        ]


def _evaluate_single_assertion(df: pd.DataFrame, assertion: str) -> dict:
    assertion = assertion.strip()

    # Handle COUNT(*) assertions
    if "COUNT(*)" in assertion.upper():
        return _evaluate_count_assertion(df, assertion)

    # Handle CELL(row, col) assertions
    if re.match(r"CELL\s*\(", assertion, re.IGNORECASE):
        return _evaluate_cell_assertion(df, assertion)

    # Handle IN / NOT IN assertions
    if " IN " in assertion.upper() or " NOT IN " in assertion.upper():
        return _evaluate_in_assertion(df, assertion)

    # Handle other column comparisons
    return _evaluate_comparison_assertion(df, assertion)


def _evaluate_count_assertion(df: pd.DataFrame, assertion: str) -> dict:
    actual_count = len(df)

    pattern = r"COUNT\(\*\)\s*(==|!=|<=|>=|<|>)\s*(\d+)"
    match = re.search(pattern, assertion, re.IGNORECASE)

    if not match:
        return {
            "passed": False,
            "assertion": assertion,
            "message": "Invalid COUNT(*) syntax",
            "error": "Could not parse COUNT(*) assertion",
        }

    operator = match.group(1)
    expected_value = int(match.group(2))

    passed = False
    if operator == "==":
        passed = actual_count == expected_value
    elif operator == "!=":
        passed = actual_count != expected_value
    elif operator == "<":
        passed = actual_count < expected_value
    elif operator == ">":
        passed = actual_count > expected_value
    elif operator == "<=":
        passed = actual_count <= expected_value
    elif operator == ">=":
        passed = actual_count >= expected_value

    if passed:
        return {
            "passed": True,
            "assertion": assertion,
            "message": "Row count check passed",
            "expected": f"COUNT(*) {operator} {expected_value}",
            "actual": f"COUNT(*) = {actual_count}",
        }

    return {
        "passed": False,
        "assertion": assertion,
        "message": f"Row count mismatch: Expected {operator} {expected_value}, but got {actual_count}",
        "expected": f"COUNT(*) {operator} {expected_value}",
        "actual": f"COUNT(*) = {actual_count}",
    }


def _evaluate_cell_assertion(df: pd.DataFrame, assertion: str) -> dict:
    """
    Evaluate a CELL(row, col) assertion against a DataFrame.

    Syntax: CELL(row, col) <operator> <value>
    Row and col are 0-indexed integers.

    Examples:
        CELL(0, 0) == 40
        CELL(0, 0) >= 10
        CELL(0, 0) == 'some text'

    Args:
        df: pandas DataFrame containing the query results
        assertion: String like "CELL(0, 0) == 40"

    Returns:
        dict with passed, assertion, message, expected, actual keys
    """
    pattern = r"CELL\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*(==|!=|<=|>=|<|>)\s*(.+)"
    match = re.match(pattern, assertion, re.IGNORECASE)

    if not match:
        return {
            "passed": False,
            "assertion": assertion,
            "message": "Invalid CELL() syntax. Expected: CELL(row, col) <operator> <value>",
            "error": "Could not parse CELL() assertion",
        }

    row_idx = int(match.group(1))
    col_idx = int(match.group(2))
    operator = match.group(3)
    value_str = match.group(4).strip()

    # Parse value
    value: Any = value_str
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]
    try:
        value = int(value)
    except ValueError:
        try:
            value = float(value)
        except ValueError:
            pass

    # Validate row index
    if row_idx >= len(df):
        return {
            "passed": False,
            "assertion": assertion,
            "message": f"Row index {row_idx} is out of range. DataFrame has {len(df)} row(s) (0-indexed)",
            "expected": f"Row index < {len(df)}",
            "actual": f"Row index {row_idx} requested",
        }

    # Validate column index
    if col_idx >= len(df.columns):
        return {
            "passed": False,
            "assertion": assertion,
            "message": f"Column index {col_idx} is out of range. DataFrame has {len(df.columns)} column(s) (0-indexed)",
            "expected": f"Column index < {len(df.columns)}",
            "actual": f"Column index {col_idx} requested. Available columns: {', '.join(df.columns.tolist())}",
        }

    actual_value = df.iloc[row_idx, col_idx]
    column_name = df.columns[col_idx]

    # Perform comparison
    passed = False
    if operator == "==":
        passed = actual_value == value
    elif operator == "!=":
        passed = actual_value != value
    elif operator == "<":
        passed = actual_value < value
    elif operator == ">":
        passed = actual_value > value
    elif operator == "<=":
        passed = actual_value <= value
    elif operator == ">=":
        passed = actual_value >= value

    if passed:
        return {
            "passed": True,
            "assertion": assertion,
            "message": f"Cell({row_idx}, {col_idx}) value check passed (column '{column_name}')",
            "expected": f"CELL({row_idx}, {col_idx}) {operator} {value}",
            "actual": f"Value = {actual_value}",
        }

    return {
        "passed": False,
        "assertion": assertion,
        "message": f"Cell({row_idx}, {col_idx}) value mismatch (column '{column_name}'): expected {operator} {value}, but got {actual_value}",
        "expected": f"CELL({row_idx}, {col_idx}) {operator} {value}",
        "actual": f"Value = {actual_value}",
    }


def _evaluate_in_assertion(df: pd.DataFrame, assertion: str) -> dict:
    is_not_in = "NOT IN" in assertion.upper()

    if is_not_in:
        pattern = r"(\w+)\s+NOT\s+IN\s*\(([^)]+)\)"
    else:
        pattern = r"(\w+)\s+IN\s*\(([^)]+)\)"

    match = re.search(pattern, assertion, re.IGNORECASE)

    if not match:
        return {
            "passed": False,
            "assertion": assertion,
            "message": "Invalid IN/NOT IN syntax",
            "error": "Could not parse IN/NOT IN assertion",
        }

    column_name = match.group(1).strip()
    values_str = match.group(2).strip()

    if column_name not in df.columns:
        return {
            "passed": False,
            "assertion": assertion,
            "message": f"Column '{column_name}' does not exist in DataFrame",
            "expected": f"Column '{column_name}' to exist",
            "actual": f"Available columns: {', '.join(df.columns.tolist())}",
        }

    values: list[Any] = []
    for val in values_str.split(","):
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        try:
            val = int(val)
        except ValueError:
            try:
                val = float(val)
            except ValueError:
                pass
        values.append(val)

    column_values = df[column_name].tolist()

    if is_not_in:
        violations = [val for val in column_values if val in values]
        passed = len(violations) == 0

        if passed:
            return {
                "passed": True,
                "assertion": assertion,
                "message": f"All {len(column_values)} values in '{column_name}' are not in the exclusion list",
                "expected": f"{column_name} NOT IN ({values_str})",
                "actual": "No violations found",
            }

        unique_violations = list(set(violations))
        violation_count = len(violations)
        return {
            "passed": False,
            "assertion": assertion,
            "message": f"Found {violation_count} value(s) in '{column_name}' that should NOT be in the list: {unique_violations}",
            "expected": f"{column_name} NOT IN ({values_str})",
            "actual": f"Found violations: {unique_violations} (occurred {violation_count} time(s))",
        }

    missing_values = [val for val in values if val not in column_values]
    passed = len(missing_values) == 0

    unique_df_values = len(set(column_values))

    if passed:
        return {
            "passed": True,
            "assertion": assertion,
            "message": f"All {len(values)} required values found in '{column_name}' (DataFrame has {unique_df_values} unique values)",
            "expected": f"All values from IN list present in {column_name}",
            "actual": f"All {len(values)} required values found in DataFrame",
        }

    return {
        "passed": False,
        "assertion": assertion,
        "message": f"Missing {len(missing_values)} required value(s) in '{column_name}': {missing_values}",
        "expected": f"{column_name} IN ({values_str}) - all values should be present",
        "actual": f"Missing values: {missing_values}. Found {unique_df_values} unique values in DataFrame",
    }


def _evaluate_comparison_assertion(df: pd.DataFrame, assertion: str) -> dict:
    pattern = r"(\w+)\s*(==|!=|<=|>=|<|>)\s*(.+)"
    match = re.match(pattern, assertion)

    if not match:
        return {
            "passed": False,
            "assertion": assertion,
            "message": "Invalid comparison syntax",
            "error": "Could not parse comparison assertion",
        }

    column_name = match.group(1).strip()
    operator = match.group(2)
    value_str = match.group(3).strip()

    if column_name not in df.columns:
        return {
            "passed": False,
            "assertion": assertion,
            "message": f"Column '{column_name}' does not exist in DataFrame",
            "expected": f"Column '{column_name}' to exist",
            "actual": f"Available columns: {', '.join(df.columns.tolist())}",
        }

    value: Any = value_str
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]
    try:
        value = int(value)
    except ValueError:
        try:
            value = float(value)
        except ValueError:
            pass

    column_values = df[column_name].tolist()

    violations: list[Any] = []
    if operator == "==":
        violations = [v for v in column_values if v != value]
        passed = len(violations) == 0
    elif operator == "!=":
        violations = [v for v in column_values if v == value]
        passed = len(violations) == 0
    elif operator == "<":
        violations = [v for v in column_values if v >= value]
        passed = len(violations) == 0
    elif operator == ">":
        violations = [v for v in column_values if v <= value]
        passed = len(violations) == 0
    elif operator == "<=":
        violations = [v for v in column_values if v > value]
        passed = len(violations) == 0
    elif operator == ">=":
        violations = [v for v in column_values if v < value]
        passed = len(violations) == 0
    else:
        return {
            "passed": False,
            "assertion": assertion,
            "message": f"Unknown operator '{operator}'",
            "error": "Unsupported comparison operator",
        }

    if passed:
        return {
            "passed": True,
            "assertion": assertion,
            "message": f"All {len(column_values)} values in '{column_name}' satisfy {column_name} {operator} {value}",
            "expected": f"{column_name} {operator} {value}",
            "actual": "All values match condition",
        }

    unique_violations = list(set(violations))
    violation_count = len(violations)
    sample_violations = unique_violations[:5]

    return {
        "passed": False,
        "assertion": assertion,
        "message": f"Found {violation_count} value(s) in '{column_name}' that violate {column_name} {operator} {value}. Sample violations: {sample_violations}",
        "expected": f"{column_name} {operator} {value}",
        "actual": f"Found {violation_count} violations: {sample_violations}{' (showing first 5)' if len(unique_violations) > 5 else ''}",
    }


def format_detailed_results_for_db(detailed_results: list[dict], overall_pass: bool) -> str:
    lines = []
    lines.append(f"OVERALL: {'PASS' if overall_pass else 'FAIL'}")
    #lines.append("="*80)

    for i, result in enumerate(detailed_results, 1):
        status = "PASS" if result["passed"] else "FAIL"
        lines.append(f"\nAssertion #{i}: [{status}]")
        lines.append(f"Statement: {result.get('assertion', 'N/A')}")
        lines.append(f"Message: {result['message']}")

        if not result["passed"]:
            if "expected" in result:
                lines.append(f"Expected: {result['expected']}")
            if "actual" in result:
                lines.append(f"Actual: {result['actual']}")
            if "error" in result:
                lines.append(f"Error: {result['error']}")

    return "\n".join(lines)
