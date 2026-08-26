"""Structural predicates over a generated SQL query.

Pure string analysis, no database and no LLM: these functions answer "what shape does
this query have?", never "is this query right?". They exist so the runtime guard in
main.py and the measurement script analyze-complex-retry-logs.py apply the EXACT same
predicate. A guard measured with a different rule than the one it runs is a number about
nothing.
"""
import re

# --- Person-role collapse (FASTAPI-TEXT2SQL-211) --------------------------------------
# A question that designates its answer by a ROLE while naming a DIFFERENT person as a
# property of the work ("the costume designer of Capote with Philip Seymour Hoffman") is
# about two distinct humans. The generator sometimes folds them into one, pinning the
# ID_PERSON of the person being LISTED to the ID_PERSON of the person being NAMED:
#
#   AND T_WC_T2S_PERSON_MOVIE.ID_PERSON IN (
#         SELECT ID_PERSON FROM T_WC_T2S_PERSON_MOVIE
#         WHERE ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE AND CREDIT_TYPE = 'cast'
#           AND ID_PERSON = (SELECT ID_PERSON FROM T_WC_T2S_PERSON
#                            WHERE PERSON_NAME = 'Philip Seymour Hoffman'))
#
# which reads "give me the costume designer, provided she is Philip Seymour Hoffman".
# Valid SQL, executes without error, empty by construction. Observed four times between
# 2026-08-25 and 2026-08-26 (logs 20260825-180503, -180636, -180913, 20260826-092145).
#
# The prompt-level fix is the "Two persons, two roles" rule in data/text_to_sql.md; this
# is the runtime belt behind it. It is a SUSPICION, not a proof: the same shape is
# legitimate when a question really is about one human in two roles ("who directed and
# starred in Unforgiven"), which is why a person pinned BY NAME inside the subquery is
# required. Firing wrongly costs one stronger-model call on a result that was ALREADY
# empty; missing it costs the user a silent "no results" on an answerable question. That
# asymmetry is the whole design.
_PERSON_CREDIT_TABLE_RE = re.compile(r"\bT_WC_T2S_PERSON_(?:MOVIE|SERIE)\b", re.IGNORECASE)
_PERSON_ID_SUBQUERY_RE = re.compile(r"\bID_PERSON\s*(?:=|\bIN\b)\s*\(", re.IGNORECASE)
_PINNED_PERSON_NAME_RE = re.compile(r"\bPERSON_NAME\b|\{\{Person_name\d*\}\}", re.IGNORECASE)


def _balanced_block(text, open_index):
    """Return what sits between the parenthesis at open_index and its matching close.

    Args:
        text: The SQL string to read.
        open_index: Index of the opening parenthesis.

    Returns:
        The inner text, or "" when the parenthesis is never closed.
    """
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:index]
    return ""


def detect_person_role_collapse(sql_query, result_entity):
    """Tell whether a person-listing query pins its answer to a person named in the question.

    Fires when a query whose answer entity is `person` constrains an `ID_PERSON` to a
    subquery that both reads a person-credit table and pins a person by name. That
    combination can only ever return the named person, so a question asking for somebody
    else by role comes back empty whatever the data holds. See the block comment above.

    Args:
        sql_query: The SQL actually executed, entity values already substituted. The
            anonymized form works too: `{{Person_nameN}}` counts as a pin.
        result_entity: The answer entity the pipeline settled on.

    Returns:
        True when the collapse shape is present, False otherwise.
    """
    if not sql_query or str(result_entity or "").strip().lower() != "person":
        return False
    for match in _PERSON_ID_SUBQUERY_RE.finditer(sql_query):
        block = _balanced_block(sql_query, match.end() - 1)
        if not block.lstrip().upper().startswith("SELECT"):
            continue
        if _PERSON_CREDIT_TABLE_RE.search(block) and _PINNED_PERSON_NAME_RE.search(block):
            return True
    return False
