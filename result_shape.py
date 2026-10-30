"""Structural classification of a /search/text2sql result into a rendering hint.

Pure analysis, no database and no LLM: these functions answer "what shape does this
result have, and how should a client draw it?", never "is this answer right?". The hint
is emitted on every live result (FASTAPI-TEXT2SQL-349) so a client dispatches on it
instead of guessing from column names, which is what made a one-row aggregate such as
`{"TOTAL_RUNTIME": 1178}` land on the entity page as an empty "Result" card
(VOICE-AGENT-243) and a runtime print as US dollars (the front's `formatScalarValue`
treats any `TOTAL_*` column as dollars).

Shape decides, intent disambiguates (design note voice-agent-243-result-representations.md,
approved 2026-10-29):

- the representation is chosen from the structure of the result alone (row count, the
  role and type of each column), which is deterministic and testable;
- only when the shape leaves two renderings tied does the generated SQL break the tie
  (an aggregate without GROUP BY is the scalar family; an ORDER BY on a metric with a
  LIMIT is a ranking). The phrasing of the question is NOT read here; when even the SQL
  leaves it tied, the default stands and a miss is cosmetic (a grid instead of bars),
  never the empty card.

No model call is involved, so the hint adds none of the six LLM tasks and no latency,
and an assertion over it ("this sum returns result_kind scalar, unit minutes") is true
or false rather than often-true, which is how an API defect is closed here.
"""
import re
from datetime import date, datetime
from decimal import Decimal
from numbers import Number

# result_kind stays faithful to the /samples vocabulary
# (entity_rows | scalar | count | bound | unknown). The real dispatch for a client lives
# in `representation`; a shape with no clean kind (a grouped aggregate of label + metric)
# is `unknown` here and still carries a usable representation.
RESULT_KINDS = ("entity_rows", "scalar", "count", "bound", "unknown")

# Representation hints a client switches on. Additive: a new one is a new value plus a new
# renderer, with no change to the dispatch. The entity-row ones match the front's existing
# two renderers (entity page, card grid); the others are VOICE-AGENT-243 and -244.
REPRESENTATIONS = (
    "entity-page",   # one entity row
    "card-grid",     # N entity rows, no extra metric
    "number-card",   # one row, one metric or count, no entity
    "stat-strip",    # one row, 2 to 5 metrics, no entity
    "ranked-bars",   # N rows of a label (or entity) plus one ordered metric
    "table",         # the honest fallback, never an empty card
)

# The entity id columns the pipeline can project, mirroring _RESULT_ENTITY_SOURCES in
# main.py plus the movie+series UNION key. A caller passes its own authoritative set; this
# is the fallback so the module stays testable on its own.
_DEFAULT_ID_COLUMNS = frozenset({
    "ID_MOVIE", "ID_SERIE", "ID_PERSON", "ID_T2S_COLLECTION", "ID_T2S_LIST", "ID_TOPIC",
    "ID_MOVEMENT", "ID_TECHNICAL", "ID_GROUP", "ID_DEATH", "ID_AWARD", "ID_NOMINATION",
    "ID_COMPANY", "ID_NETWORK", "ID_LOCATION", "ID_SOURCE_WORK", "ID_GENRE", "ID_ROW",
    "ID_CONTENT",
})

# Column-name patterns that carry a unit. Checked in order; first match wins. The point is
# to put the unit on the API side, where the summed column is known, so a runtime never
# reaches a client as dollars. A computed column whose alias says nothing (PROFIT from
# SUM(REVENUE) - SUM(BUDGET)) stays unit-less rather than guessed (open question, note §6).
#
# `ratio` is tested before `usd` on purpose: a column expressing a ratio ("how many times
# the budget", TIMES_BUDGET) contains a money word but must never read as money.
_UNIT_PATTERNS = (
    ("ratio", re.compile(r"RATIO|PERCENT|_RATE\b|\bTIMES_|_PER_", re.IGNORECASE)),
    ("usd", re.compile(r"BUDGET|REVENUE|GROSS|BOX_?OFFICE|_USD\b|EARNING", re.IGNORECASE)),
    ("minutes", re.compile(r"RUNTIME|DURATION|_MINUTES?\b", re.IGNORECASE)),
    ("years", re.compile(r"_YEAR\b|\bYEARS?\b|\bAGE\b", re.IGNORECASE)),
    ("count", re.compile(r"^COUNT|_COUNT\b|^NB_|NUMBER_OF|^N_|^TOTAL$", re.IGNORECASE)),
)

_LABEL_RE = re.compile(r"_(?:TITLE|NAME)$|^(?:TITLE|NAME)$|_LABEL$", re.IGNORECASE)
_DATE_NAME_RE = re.compile(r"^DAT_|_DATE$|^DATE_|_YEAR$", re.IGNORECASE)
_AGGREGATE_RE = re.compile(r"\b(?:SUM|COUNT|AVG|MIN|MAX|TOTAL)\s*\(", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_COUNT_RE = re.compile(r"\bCOUNT\s*\(", re.IGNORECASE)
_ORDER_BY_CLAUSE_RE = re.compile(
    r"\bORDER\s+BY\b(.*?)(?:\bLIMIT\b|\bOFFSET\b|\)|;|$)", re.IGNORECASE | re.DOTALL)

# Metrics the pipeline projects by default on entity rows (FASTAPI-TEXT2SQL-350). A list of
# actors carries POPULARITY, an image wall VOTE_AVERAGE, and both are ordered on them, so
# "one metric plus ORDER BY" fired ranked-bars on 103 plain lists of the 2026-10-29 campaign.
# They are sort keys, not the measure the question asked for: never a ranking on their own.
_DEFAULT_ENTITY_METRICS = frozenset({"POPULARITY", "VOTE_AVERAGE", "VOTE_COUNT", "IMDB_VOTES"})


def _is_numeric(value):
    """Tell whether a cell holds a number (int, float or a DB Decimal), not a bool."""
    return isinstance(value, (int, float, Decimal, Number)) and not isinstance(value, bool)


def _unit_for(name):
    """Return the unit a column name implies, or None when nothing is certain."""
    for unit, pattern in _UNIT_PATTERNS:
        if pattern.search(name):
            return unit
    return None


def _column_role(name, sample_value, id_columns):
    """Classify one column into entity_id | label | date | metric | other.

    The name settles id, label and date; the Python type of a sample cell settles metric
    (a numeric cell that is none of the above). A year reads as a date, not a metric, so a
    client never charts BIRTH_YEAR as a bar.
    """
    upper = str(name).upper()
    if upper in id_columns:
        return "entity_id"
    if _LABEL_RE.search(name):
        return "label"
    if isinstance(sample_value, (date, datetime)) or _DATE_NAME_RE.search(name):
        return "date"
    if _is_numeric(sample_value):
        return "metric"
    return "other"


def _first_non_null(rows, name):
    """Return the first non-null cell for a column across rows, or None."""
    for row in rows:
        value = row.get(name)
        if value is not None:
            return value
    return None


def _columns_metadata(rows, id_columns):
    """Build the per-column {name, role, unit} list, in projection order.

    Column order is the insertion order of the first row's dict (the DB cursor order).
    """
    if not rows:
        return []
    columns = []
    for name in rows[0].keys():
        sample = _first_non_null(rows, name)
        role = _column_role(name, sample, id_columns)
        unit = _unit_for(name) if role in ("metric", "date") else None
        columns.append({"name": name, "role": role, "unit": unit})
    return columns


def _orders_by_metric(sql, metric_name, columns):
    """Tell whether the outermost ORDER BY sorts on the metric column.

    Reads the last ORDER BY clause of the SQL (the outer query's) and accepts the column
    name or alias as a whole word, or its 1-based position in the projection. A bare
    "ORDER BY" elsewhere in the query is not enough (FASTAPI-TEXT2SQL-350).
    """
    clauses = _ORDER_BY_CLAUSE_RE.findall(sql or "")
    if not clauses:
        return False
    clause = clauses[-1]
    if re.search(r"(?<![\w.])(?:\w+\.)?`?" + re.escape(metric_name) + r"`?(?!\w)", clause,
                 re.IGNORECASE):
        return True
    names = [c["name"] for c in columns]
    position = names.index(metric_name) + 1 if metric_name in names else 0
    return bool(position) and re.search(r"(?<![\w.])" + str(position) + r"(?!\w)",
                                        clause) is not None


def _is_entity_ranking(sql, columns, metric_cols, result_entity):
    """Decide whether N entity rows are a ranking (ranked-bars) rather than a grid.

    All must hold: exactly one metric column, not a default projection (POPULARITY,
    VOTE_AVERAGE...), the outer ORDER BY on that metric, and rows that are not images.
    """
    if len(metric_cols) != 1:
        return False
    metric = metric_cols[0]["name"]
    if metric.upper() in _DEFAULT_ENTITY_METRICS:
        return False
    names = {c["name"].upper() for c in columns}
    if str(result_entity or "").lower().endswith("_image") or {"ID_ROW", "TYPE_IMAGE"} <= names:
        return False
    return _orders_by_metric(sql, metric, columns)


def classify_result(sql_query, result_rows, result_entity="", id_columns=None):
    """Classify a result into {result_kind, columns, representation}. Pure, no DB, no LLM.

    Args:
        sql_query: The SQL actually executed (used only to break a shape tie).
        result_rows: The response `result` list, items shaped `{"index", "data"}`; a list
            of plain dicts is accepted too.
        result_entity: The answer entity the pipeline settled on ("" for an aggregate).
        id_columns: The authoritative set of entity id column names; defaults to the
            module's own copy of _RESULT_ENTITY_SOURCES.

    Returns:
        A dict with:
          - result_kind: one of RESULT_KINDS;
          - columns: list of {name, role, unit}, in projection order (empty with no rows);
          - representation: one of REPRESENTATIONS.
    """
    ids = frozenset(id_columns) if id_columns is not None else _DEFAULT_ID_COLUMNS
    rows = [
        (r.get("data", r) if isinstance(r, dict) else {})
        for r in (result_rows or [])
    ]
    columns = _columns_metadata(rows, ids)
    sql = sql_query or ""
    # The result is entity rows only when it actually projects an entity id column. NOT when
    # result_entity is merely set: the answer-entity classifier returns "movie" even for
    # "how many movies are there", whose result is a one-row scalar count with no id column
    # (MOVIE_COUNT alone). Keying the branch on result_entity there drew the count as an
    # entity page. The column structure is the authority; every genuine entity projection
    # carries its ID_ column. result_entity is kept in the signature for callers and future
    # use, but does not decide the shape.
    has_entity = any(c["role"] == "entity_id" for c in columns)
    metric_cols = [c for c in columns if c["role"] == "metric"]
    label_cols = [c for c in columns if c["role"] == "label"]

    # Entity rows: one entity is a page, many are a grid, many ordered by one metric is a
    # ranking (the poster-versus-bar choice is the client's, VOICE-AGENT-244). A ranking needs
    # the ORDER BY on the one metric, a metric that is not a default sort key, and no image
    # rows (FASTAPI-TEXT2SQL-350); a plain list ordered by POPULARITY stays a grid.
    if has_entity:
        if len(rows) <= 1:
            return {"result_kind": "entity_rows", "columns": columns,
                    "representation": "entity-page" if rows else "card-grid"}
        if _is_entity_ranking(sql, columns, metric_cols, result_entity):
            return {"result_kind": "entity_rows", "columns": columns,
                    "representation": "ranked-bars"}
        return {"result_kind": "entity_rows", "columns": columns,
                "representation": "card-grid"}

    # No rows: nothing to inspect, so result_entity is the only signal left for what was
    # searched. An empty entity search degrades to an empty card grid; anything else to a
    # table. Never an empty "Result" card. (A count never reaches here: it has one row.)
    if not rows:
        if str(result_entity or "").strip():
            return {"result_kind": "entity_rows", "columns": columns, "representation": "card-grid"}
        return {"result_kind": "unknown", "columns": columns, "representation": "table"}

    # One row, no entity: the scalar family. A COUNT is a count, otherwise a scalar; one
    # metric is a number card, two to five a stat strip.
    if len(rows) == 1:
        is_count = _COUNT_RE.search(sql) and len(metric_cols) == 1
        kind = "count" if is_count else "scalar"
        if 1 <= len(metric_cols) <= 5 and not _GROUP_BY_RE.search(sql):
            representation = "number-card" if len(metric_cols) == 1 else "stat-strip"
            return {"result_kind": kind, "columns": columns, "representation": representation}
        # A single text fact, or a shape with no metric: fall back to a table.
        return {"result_kind": kind if metric_cols else "unknown",
                "columns": columns, "representation": "table"}

    # Many rows, no entity: a grouped aggregate. A label plus exactly one metric, ordered,
    # is a ranking; anything wider is a table. No clean result_kind in the vocabulary, so
    # `unknown` with a usable representation.
    if label_cols and len(metric_cols) == 1 and _ORDER_BY_RE.search(sql):
        return {"result_kind": "unknown", "columns": columns, "representation": "ranked-bars"}
    return {"result_kind": "unknown", "columns": columns, "representation": "table"}
