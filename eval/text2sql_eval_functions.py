import json
import re
import html
from typing import Any

import pandas as pd


# Convert API version to XXX.YYY.ZZZ format for comparison
def format_api_version(version: str) -> str:
    """Convert version string to XXX.YYY.ZZZ format for comparison."""
    version_parts = version.split('.')
    return f"{int(version_parts[0]):03d}.{int(version_parts[1]):03d}.{int(version_parts[2]):03d}"


def safe_json_loads(value: Any):
    """Safely parse JSON-like values, including strings with surrounding noise."""
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
    """Render a JSON-like record into a compact single-line display string."""
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

    # Assertions can be stored HTML-escaped in DB exports (e.g. &gt; instead of >)
    #strassertions = html.unescape(strassertions)

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
        # Unified-schema bridge: prompts emit `ID_MOVIE/ID_SERIE/ID_PERSON AS ID_CONTENT`
        # plus a CONTENT_TYPE discriminator. Synthesize the per-entity columns so
        # legacy assertions like `ID_MOVIE IN (...)` still resolve. Non-matching rows
        # become NaN, which the IN/NOT IN evaluator treats as not-in-list.
        if {"ID_CONTENT", "CONTENT_TYPE"} <= set(df_results.columns):
            ct = df_results["CONTENT_TYPE"].astype(str).str.lower()
            if "ID_MOVIE" not in df_results.columns:
                df_results["ID_MOVIE"] = df_results["ID_CONTENT"].where(ct == "movie")
            if "ID_SERIE" not in df_results.columns:
                df_results["ID_SERIE"] = df_results["ID_CONTENT"].where(ct == "serie")
            if "ID_PERSON" not in df_results.columns:
                df_results["ID_PERSON"] = df_results["ID_CONTENT"].where(ct == "person")

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
    """Dispatch a single assertion string to the appropriate evaluator."""
    assertion = assertion.strip()

    # Handle COUNT(column) assertions (unique non-null values)
    if re.search(r"\bCOUNT\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s*\)", assertion, re.IGNORECASE) and "COUNT(*)" not in assertion.upper():
        return _evaluate_count_unique_assertion(df, assertion)

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
    """Evaluate a ``COUNT(*)`` assertion against the DataFrame row count."""
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


def _evaluate_count_unique_assertion(df: pd.DataFrame, assertion: str) -> dict:
    """Evaluate a ``COUNT(column)`` assertion against unique non-null values."""
    pattern = r"COUNT\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*(==|!=|<=|>=|<|>)\s*(\d+)"
    match = re.search(pattern, assertion, re.IGNORECASE)

    if not match:
        return {
            "passed": False,
            "assertion": assertion,
            "message": "Invalid COUNT(column) syntax",
            "error": "Could not parse COUNT(column) assertion",
        }

    column_name = match.group(1)
    operator = match.group(2)
    expected_value = int(match.group(3))

    if column_name not in df.columns:
        return {
            "passed": False,
            "assertion": assertion,
            "message": f"Unknown column '{column_name}' for COUNT({column_name})",
            "error": f"DataFrame has columns: {', '.join([str(c) for c in df.columns])}",
        }

    actual_unique_count = int(df[column_name].dropna().nunique())

    passed = False
    if operator == "==":
        passed = actual_unique_count == expected_value
    elif operator == "!=":
        passed = actual_unique_count != expected_value
    elif operator == "<":
        passed = actual_unique_count < expected_value
    elif operator == ">":
        passed = actual_unique_count > expected_value
    elif operator == "<=":
        passed = actual_unique_count <= expected_value
    elif operator == ">=":
        passed = actual_unique_count >= expected_value

    expected_str = f"COUNT({column_name}) {operator} {expected_value}"
    actual_str = f"COUNT({column_name}) = {actual_unique_count} (unique non-null)"

    if passed:
        return {
            "passed": True,
            "assertion": assertion,
            "message": f"Unique count check passed for column '{column_name}'",
            "expected": expected_str,
            "actual": actual_str,
        }

    return {
        "passed": False,
        "assertion": assertion,
        "message": f"Unique count mismatch for column '{column_name}': Expected {operator} {expected_value}, but got {actual_unique_count}",
        "expected": expected_str,
        "actual": actual_str,
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
    """Evaluate ``IN`` and ``NOT IN`` assertions against a DataFrame column."""
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

    remaining_values: list[Any] = []
    missing_pool = missing_values.copy()
    for value in values:
        if value in missing_pool:
            missing_pool.remove(value)
            continue
        remaining_values.append(value)

    return {
        "passed": False,
        "assertion": assertion,
        "message": f"Missing {len(missing_values)} required value(s) in '{column_name}': {missing_values}",
        "expected": f"{column_name} IN ({values_str}) - all values should be present",
        "actual": f"Missing values: {missing_values}. Found {unique_df_values} unique values in DataFrame",
        "success_if_statement": f"{column_name} IN ({', '.join([str(v) for v in remaining_values])})",
    }


def _evaluate_comparison_assertion(df: pd.DataFrame, assertion: str) -> dict:
    """Evaluate a column-wise comparison assertion against every row value."""
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
    sample_violations_str = ", ".join([str(v) for v in sample_violations])

    return {
        "passed": False,
        "assertion": assertion,
        "message": f"Found {violation_count} value(s) in '{column_name}' that violate {column_name} {operator} {value}. Sample violations: {sample_violations_str}",
        "expected": f"{column_name} {operator} {value}",
        "actual": f"Found {violation_count} violations: {sample_violations_str}{' (showing first 5)' if len(unique_violations) > 5 else ''}",
    }


def format_detailed_results_for_db(detailed_results: list[dict], overall_pass: bool) -> str:
    """Format assertion results into a readable summary string for database storage."""
    lines = []
    lines.append(f"OVERALL: {'PASS' if overall_pass else 'FAIL'}")
    #lines.append("="*80)

    for i, result in enumerate(detailed_results, 1):
        status = "PASS" if result["passed"] else "FAIL"
        lines.append(f"\nAssertion #{i}: {status}")
        lines.append(f"Statement: {result.get('assertion', 'N/A')}")
        lines.append(f"Message: {result['message']}")

        if not result["passed"]:
            if "expected" in result:
                lines.append(f"Expected: {result['expected']}")
            if "actual" in result:
                lines.append(f"Actual: {result['actual']}")
            if "error" in result:
                lines.append(f"Error: {result['error']}")
            success_if_statement = result.get("success_if_statement")
            if success_if_statement is not None:
                lines.append(f"Success if statement: {success_if_statement}")

    formatted = "\n".join(lines)
    formatted = formatted.replace("[", "(").replace("]", ")")
    return formatted


# ---------------------------------------------------------------------------
# Translation guards for phases 4-6 (EVALUATIONS-019)
#
# On 2026-09-25 fifteen evaluations were found whose French column held a refusal of
# the translation model ("Je suis desole, je ne peux pas vous aider avec ca.") instead
# of a question: phase 5 had been asked to translate French text, typed into the
# English column, into French. And a 2025 film, "Sorry, Baby", came back translated as
# a phrase. The helpers below keep both from being stored again. They are pure, so the
# rules can be checked offline against the exported bank.
# ---------------------------------------------------------------------------

_REFUSAL_PATTERNS = (
    r"\bje suis d[ée]sol[ée]",
    r"\bje ne (peux|suis) pas\b",
    r"\bje ne peux\b",
    r"\bd[ée]sol[ée], mais\b",
    r"\bquestions d'[ée]valuation en anglais sont n[ée]cessaires\b",
    r"\bveuillez fournir\b",
    r"\bi'?m sorry\b",
    r"\bi am sorry\b",
    r"\bi (can(no|')t|am unable to|cannot)\b",
    r"\bas an ai\b",
    r"\bplease provide\b",
)


def looks_like_refusal(text: str) -> bool:
    """True when a translation output reads as a refusal or a request for input."""
    t = html.unescape(text or "").strip().lower().replace("’", "'")
    if not t:
        return True
    return any(re.search(p, t) for p in _REFUSAL_PATTERNS)


# Words that only one of the two languages uses. "film", "films", "photos", "action"
# and the like are shared and deliberately absent: a question like "Film roofman" or
# "Movie noroit" must come out as undecided, never as the wrong language.
_FR_MARKERS = {
    "le", "la", "les", "des", "du", "une", "et", "est", "avec", "pour", "dans", "sur",
    "qui", "que", "quel", "quels", "quelle", "quelles", "sont", "ont", "été", "par",
    "au", "aux", "moi", "donne", "montre", "liste", "listez", "tous", "toutes", "série",
    "séries", "acteurs", "réalisés", "réalisateur", "réalisateurs", "sortis", "nés",
    "affiches", "années", "langue", "où", "combien", "à", "d", "l", "qu", "c",
}
_EN_MARKERS = {
    "the", "of", "and", "with", "what", "which", "who", "whose", "show", "list", "all",
    "movie", "movies", "series", "by", "from", "in", "on", "are", "is", "was", "were",
    "released", "directed", "starring", "born", "actors", "actor", "pictures", "posters",
    "give", "me", "how", "many", "where", "when", "did", "does", "about", "that", "their",
}


def guess_language(text: str):
    """Return 'fr', 'en', or None when the text does not say clearly enough.

    A crude marker count, tuned to fail towards None: it is only used to refuse a
    translation that is obviously in the wrong language, never to accept one.
    """
    t = html.unescape(text or "").lower().replace("’", "'")
    words = re.findall(r"[a-zàâäçéèêëîïôöùûüœ]+", t)
    if not words:
        return None
    fr = sum(1 for w in words if w in _FR_MARKERS)
    en = sum(1 for w in words if w in _EN_MARKERS)
    if re.search(r"[àâçéèêëîïôùûœ]", t):
        fr += 1
    if fr >= 2 and fr >= en + 2:
        return "fr"
    if en >= 2 and en >= fr + 2:
        return "en"
    return None


def question_ngrams(question: str, max_words: int = 10) -> list:
    """Every run of 1 to max_words consecutive words of the question, trimmed of the
    punctuation that sits around a title ("Pulp Fiction?" -> "Pulp Fiction"), longest
    first. Punctuation inside a title stays ("The Good, the Bad and the Ugly")."""
    words = html.unescape(question or "").replace("\r", " ").replace("\n", " ").split()
    grams = []
    for n in range(min(max_words, len(words)), 0, -1):
        for i in range(0, len(words) - n + 1):
            g = " ".join(words[i:i + n]).strip(" \t?!.;:«»\"'()[]")
            if g and g not in grams:
                grams.append(g)
    return grams


_GENERIC_TITLES = {
    "movie", "movies", "film", "films", "serie", "series", "série", "séries", "the", "a",
    "list", "show", "all", "who", "what", "which", "actors", "people", "photos", "pictures",
}


def is_title_candidate(gram: str) -> bool:
    """A word sequence long enough to be looked up as a title. Single short or generic
    words ("It", "Up", "Her", "Movie") would match titles everywhere and are skipped."""
    g = gram.strip()
    if g.lower() in _GENERIC_TITLES or g.isdigit():
        return False
    return len(g.split()) >= 2 or len(g) >= 5


def assertion_ids(assertion: str) -> dict:
    """The ID_MOVIE / ID_SERIE lists named in an ASSERTIONS_QUERY_RESULT string."""
    out = {"movie": set(), "serie": set()}
    a = html.unescape(assertion or "")
    for col, key in (("ID_MOVIE", "movie"), ("ID_SERIE", "serie")):
        for m in re.finditer(col + r"\s+IN\s*\(([\d,\s]+)\)", a):
            out[key].update(int(x) for x in m.group(1).split(",") if x.strip())
    return out


def build_title_glossary(question: str, rows: list, preferred_ids: dict) -> dict:
    """Decide which titles of the question the database can translate.

    rows: dicts with keys kind ('movie' or 'serie'), id, src (title in the source
    language) and dst (title in the target language), as fetched for the question's
    word sequences. A title is kept only on an EXACT match (case-insensitive) with a
    sequence of the question, so a deliberate typo ("tron ares") is never corrected
    into a real title. Homonyms are settled by the assertion ids; when they disagree
    on the target title and no assertion settles it, the title is left out, and the
    model is told to copy it verbatim. Longest titles win, and a title inside a
    longer matched title is dropped.

    Returns {source title as written in the question: target title}.
    """
    grams = {g.lower(): g for g in question_ngrams(question)}
    by_title = {}
    for r in rows:
        src = (r.get("src") or "").strip()
        dst = (r.get("dst") or "").strip()
        if not src or not dst or src.lower() not in grams or not is_title_candidate(src):
            continue
        by_title.setdefault(src.lower(), []).append(r)
    glossary = {}
    for key in sorted(by_title, key=len, reverse=True):
        if any(key in longer.lower() for longer in glossary):
            continue
        cands = by_title[key]
        preferred = [c for c in cands if c["id"] in preferred_ids.get(c["kind"], set())]
        pool = preferred or cands
        targets = {(c.get("dst") or "").strip() for c in pool}
        if len(targets) == 1:
            glossary[grams[key]] = targets.pop()
    return glossary


def translation_system_prompt(src_lang: str, dst_lang: str, glossary: dict) -> str:
    """The system prompt of phases 5 and 6: titles and names are never translated by
    the model; the only translated titles are the ones the database supplies."""
    names = {"en": "English", "fr": "French"}
    lines = [
        f"You translate evaluation questions about movies and TV series from {names[src_lang]} to {names[dst_lang]}.",
        "Return only the translation, with no explanation or surrounding quotes.",
        "Never translate the title of a movie, series, collection or any other work, nor a person's name: copy it exactly as written, spelling mistakes and missing accents included.",
        "Keep the question's own imperfections (typos, lowercase names, missing punctuation): translate the sentence, do not correct it.",
        "If the text is already in the target language, return it unchanged. Never answer the question and never refuse: always return a translation.",
    ]
    if glossary:
        lines.append("The following titles appear in the question and have an official title in the target language. Use exactly these, and translate no other title:")
        for src, dst in glossary.items():
            lines.append(f"- {src} => {dst}")
    return "\n".join(lines)
