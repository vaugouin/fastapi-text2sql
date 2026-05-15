import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd
from eval.text2sql_eval_functions import evaluate_dataframe_assertions


def run(label, df, assertion, expected):
    ok, details = evaluate_dataframe_assertions(df, assertion)
    status = "PASS" if ok == expected else "FAIL"
    print(f"[{status}] {label}: {assertion!r} => got={ok}, expected={expected} | {details[0]['message']}")
    return ok == expected


print("=== Unified-schema bridge tests ===")
all_ok = True

# 1. Movies-only unified schema: ID_MOVIE IN should resolve via ID_CONTENT.
df_movies = pd.DataFrame({
    "ID_CONTENT": [5925, 76203, 5924],
    "CONTENT_TYPE": ["movie", "movie", "movie"],
    "CONTENT_TITLE": ["A", "B", "C"],
})
all_ok &= run("ID_MOVIE IN matches", df_movies, "ID_MOVIE IN (5925, 76203, 5924)", True)
all_ok &= run("ID_MOVIE IN missing", df_movies, "ID_MOVIE IN (1, 2, 3)", False)

# 2. Mixed movies + series: ID_MOVIE assertion must only see movie rows; series IDs become NaN.
df_mixed = pd.DataFrame({
    "ID_CONTENT": [5925, 999, 76203],
    "CONTENT_TYPE": ["movie", "serie", "movie"],
})
all_ok &= run("ID_MOVIE ignores series rows", df_mixed, "ID_MOVIE IN (5925, 76203)", True)
all_ok &= run("ID_SERIE only matches series", df_mixed, "ID_SERIE IN (999)", True)
all_ok &= run("ID_SERIE skips movies", df_mixed, "ID_SERIE IN (5925)", False)

# 3. ID_PERSON branch.
df_persons = pd.DataFrame({
    "ID_CONTENT": [42, 43],
    "CONTENT_TYPE": ["person", "person"],
})
all_ok &= run("ID_PERSON IN matches", df_persons, "ID_PERSON IN (42, 43)", True)

# 4. Case-insensitive CONTENT_TYPE.
df_caps = pd.DataFrame({
    "ID_CONTENT": [5925],
    "CONTENT_TYPE": ["Movie"],
})
all_ok &= run("CONTENT_TYPE 'Movie' is treated as movie", df_caps, "ID_MOVIE IN (5925)", True)

# 5. No-op: DataFrame already has ID_MOVIE — virtual logic must not overwrite.
df_native = pd.DataFrame({
    "ID_MOVIE": [111, 222],
    "ID_CONTENT": [999, 888],
    "CONTENT_TYPE": ["movie", "movie"],
})
all_ok &= run("Existing ID_MOVIE preserved", df_native, "ID_MOVIE IN (111, 222)", True)
all_ok &= run("Existing ID_MOVIE not overwritten by ID_CONTENT", df_native, "ID_MOVIE IN (999, 888)", False)

# 6. No CONTENT_TYPE — virtual logic does not fire (back to strict resolution).
df_no_ct = pd.DataFrame({
    "ID_CONTENT": [5925],
})
all_ok &= run("Missing CONTENT_TYPE leaves ID_MOVIE unresolved", df_no_ct, "ID_MOVIE IN (5925)", False)

# 7. NOT IN against virtual column.
all_ok &= run("ID_MOVIE NOT IN excludes correctly", df_mixed, "ID_MOVIE NOT IN (1, 2, 3)", True)
all_ok &= run("ID_MOVIE NOT IN catches violation", df_mixed, "ID_MOVIE NOT IN (5925)", False)

print()
print("OVERALL:", "PASS" if all_ok else "FAIL")
sys.exit(0 if all_ok else 1)
