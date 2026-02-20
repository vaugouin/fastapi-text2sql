import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd
from eval.text2sql_eval_functions import evaluate_dataframe_assertions

df = pd.DataFrame(
    {
        "A": [10, 20],
        "B": ["x", "y"],
        "C": [3.5, 4.5],
    }
)

tests = [
    "CELL(0, 0) == 10",      # should PASS
    "CELL(1, 0) == 20",      # should PASS
    "CELL(0, 1) == 'x'",     # should PASS
    "CELL(1, 2) >= 4.5",     # should PASS
    "CELL(0, 0) == 999",     # should FAIL
    "CELL(0, 99) == 1",      # should FAIL (col out of range)
    "CELL(99, 0) == 1",      # should FAIL (row out of range)
]

for a in tests:
    ok, details = evaluate_dataframe_assertions(df, a)
    print(a, "=>", ok, "|", details[0]["message"])
    