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
from math import gcd
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
    "value-cards",   # N entity rows, each with the quantity the question asked (-354)
    "timeline",      # N entity rows placed on a time axis by the date the question asked (phase 2 lot A)
    "sequence-strip",  # N entity rows in their order (by date or collection order), numbered (phase 2 lot A)
    "trend-columns",   # N rows of a year or decade plus one metric, one column per period (phase 2 lot A)
    "compare-cards",   # 2 to 4 named entities side by side, one or two quantities, the winner marked (phase 2 lot B)
    "fact-card",       # one entity and the one quantity or date the question asks about (phase 2 lot B)
    "verdict",         # a yes/no answer read from the rows: a row exists, none does, a count above zero (phase 2 lot B)
    "histogram",       # rows that are bins of one quantity plus a count, drawn in bin order (phase 2 lot C)
    "share-bar",       # 2 to 8 parts of a complete whole, or one share, as one 100% bar (phase 2 lot C)
    "flag-list",       # countries with their flag and name, and the count when there is one (phase 2 lot C)
    "scatter",         # N entity rows as dots over two quantities, x against y (phase 3 lot A)
    "map",             # the countries of a flag list shaded on a world outline (phase 3 lot B)
    "table",         # the honest fallback, never an empty card
)

# Intent tasks that ask for a quantity per item rather than an order (FASTAPI-TEXT2SQL-354):
# "the Harry Potter films with their runtime" and "which is longer, Titanic or Avatar?".
_VALUE_TASKS = ("value", "compare")
# Views the question can name explicitly (result_intent.REQUESTED_VIEWS) and the representation
# each one asks for; honoured only when that representation is a valid option for the shape.
_REQUESTED_VIEW_REPRESENTATIONS = {
    "table": ("table",),
    "chart": ("ranked-bars", "trend-columns", "timeline", "histogram"),
    "cards": ("value-cards", "card-grid"),
    "share": ("share-bar",),
    "scatter": ("scatter",),
    "map": ("map",),
}
# Phase 3 lot A. A scatter needs five points carrying both quantities: fewer is a handful of
# cards, which value-cards or compare-cards already draw better than a near-empty plot.
_SCATTER_MIN_POINTS = 5
# The quantity a scatter axis carries, read from the column name; a date is a year. Two columns
# of one quantity (IMDB_RATING and IMDB_RATING_WEIGHTED, DAT_RELEASE and RELEASE_YEAR) are one
# axis, never a plot of a rating against itself. Checked in order (VOTE_COUNT is votes, not a
# rating; VOTE_AVERAGE is a rating).
_SCATTER_QUANTITIES = (
    ("votes", re.compile(r"VOTE_COUNT|VOTES\b", re.IGNORECASE)),
    ("rating", re.compile(r"RATING|VOTE_AVERAGE|SCORE|\bNOTE", re.IGNORECASE)),
    ("budget", re.compile(r"BUDGET", re.IGNORECASE)),
    ("revenue", re.compile(r"REVENUE|GROSS|BOX_?OFFICE|EARNING|RECETTE", re.IGNORECASE)),
    ("profit", re.compile(r"PROFIT|BENEFI", re.IGNORECASE)),
    ("runtime", re.compile(r"RUNTIME|DURATION|DUREE|MINUTE", re.IGNORECASE)),
    ("seasons", re.compile(r"SEASON|SAISON", re.IGNORECASE)),
    ("episodes", re.compile(r"EPISODE", re.IGNORECASE)),
    ("popularity", re.compile(r"POPULARITY", re.IGNORECASE)),
    ("age", re.compile(r"\bAGE\b|_AGE\b|^AGE_", re.IGNORECASE)),
)
# Which of the two quantities goes across: "A against B" is read both ways by the people who
# ask it ("plot the budget against the revenue" means budget across as often as up), so the
# API fixes the axes by a convention instead of the word order: time always across, then what
# goes in (budget, runtime, seasons, votes), and what comes out (revenue, profit, rating) up.
_SCATTER_X_ORDER = ("year", "budget", "runtime", "seasons", "episodes", "count", "votes", "popularity",
                    "age", "other", "revenue", "profit", "rating")
# IMDb votes run from a few dozen to millions on one director's films: a linear axis crushes all
# but the three biggest into one corner. A votes axis is logarithmic when its largest value is a
# hundred times its smallest; no other quantity is (money and minutes read in plain amounts).
_SCATTER_LOG_RATIO = 100
# Phase 2 lot C. A share bar holds two to eight parts: more falls back to ranked-bars (a bar of
# thirty slivers says nothing), one part says nothing a number card does not.
_SHARE_MIN_PARTS, _SHARE_MAX_PARTS = 2, 8
# Phase 3 lot B. The shading of a map with a count: at most five steps from light to dark, each
# holding about as many countries (quantiles: film counts run from a handful to thousands, and
# equal ranges would leave all but the United States in the lightest step).
_MAP_STEPS = 5
# A histogram fills the empty bins between two filled ones (a missing bin would read as no gap)
# as long as the filled axis stays readable; past this many bins it keeps the bins it was given.
_HISTOGRAM_MAX_FILLED_BINS = 60
# The name of a bin column says which quantity it cuts: a measure word, or a bin word. A numeric
# GROUP BY key that says neither (GENDER, an ID, a STATUS code) is a category, not a bin.
_BIN_NAME_RE = re.compile(
    r"RUNTIME|DURATION|DUREE|MINUTE|BUDGET|REVENUE|GROSS|RECETTE|RATING|VOTE|SCORE|NOTE|SEASON|SAISON"
    r"|EPISODE|\bAGE\b|_AGE\b|^AGE_|POPULARITY|BIN|BUCKET|BAND|RANGE|TRANCHE|INTERVAL|CLASSE?\b", re.IGNORECASE)
# Of two bin columns, the one whose name says it is the top of the range.
_BIN_HIGH_RE = re.compile(r"END|MAX|HIGH|UPPER|_TO\b|FIN\b", re.IGNORECASE)
# One share of a whole, as the model names it: FILM_SHARE 0.74, PERCENT_OF_FILMS 27.27.
_SHARE_NAME_RE = re.compile(r"SHARE|PROPORTION|FRACTION|PERCENT|PCT|POURCENT|PART\b", re.IGNORECASE)
_PERCENT_NAME_RE = re.compile(r"PERCENT|PCT|POURCENT", re.IGNORECASE)
# TMDb's gender code (0 not set, 1 woman, 2 man, 3 non-binary): a category, never a measure.
_GENDER_RE = re.compile(r"^GENDER$|_GENDER$|^GENRE_SEXE$|^SEXE$", re.IGNORECASE)
# A country code column: COUNTRY_CODE, ORIGIN_COUNTRY, COUNTRY_OF_BIRTH, PAYS.
_COUNTRY_COLUMN_RE = re.compile(r"COUNTRY|PAYS", re.IGNORECASE)
_LOCATION_COUNTRY_SQL_RE = re.compile(r"LOCATION_TYPE\s*=\s*'country'", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?(?:\s+OFFSET\s+(\d+))?", re.IGNORECASE)
# Phase 2 lot B. A comparison is drawn side by side for two to four entities; more rows (homonyms
# of a named title, a set) keep value-cards. A comparison shows at most two quantities.
_COMPARE_MIN_ROWS, _COMPARE_MAX_ROWS, _COMPARE_MAX_COLUMNS = 2, 4, 2
# A month or a day projected beside a year (BIRTH_MONTH, BIRTH_DAY for "born before") is a part
# of a date, not a quantity to compare.
_DATE_PART_RE = re.compile(r"_(?:MONTH|DAY)$", re.IGNORECASE)
# An ORDER BY on the collection's own order (the prompt sorts a collection on DISPLAY_ORDER,
# which it does not project): summary_facts.order is then "collection".
_COLLECTION_ORDER_RE = re.compile(r"DISPLAY_ORDER|COLLECTION_ORDER", re.IGNORECASE)

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
# A 0/1 flag such as APPLIES_TO_MOVIE is numeric but never a measure: counted as a metric it
# turned "movies per genre" (one count plus two flags) into a three-metric grid.
_FLAG_RE = re.compile(r"^(?:IS|HAS|APPLIES_TO)_|_FLAG$", re.IGNORECASE)
# A code column (COUNTRY_CODE, LANGUAGE_CODE) names the group of a grouped aggregate.
_CODE_RE = re.compile(r"_CODE$|^CODE$", re.IGNORECASE)
# A year or a decade is a point in time, not a quantity: a GROUP BY key such as DECADE typed
# metric made "average runtime by decade" a two-metric result, and DECENNIE ordered ASC a
# ranking (FASTAPI-TEXT2SQL-351 side note). The French aliases the model writes are covered.
_DATE_NAME_RE = re.compile(
    r"^DAT_|_DATE$|^DATE_|_YEAR$|^YEAR$|DECADE|DECENNIE|^ANNEE$|_ANNEE$", re.IGNORECASE)
# An identifier that is not an entity key (ID_IMDB, ID_CRITERION_SPINE, ID_RECORD) is a number
# to sort on, never a measure to draw: "ORDER BY ID_CRITERION_SPINE" is a sequence, not a ranking.
_OTHER_ID_RE = re.compile(r"^ID_", re.IGNORECASE)
_AGGREGATE_RE = re.compile(r"\b(?:SUM|COUNT|AVG|MIN|MAX|TOTAL)\s*\(", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_COUNT_RE = re.compile(r"\bCOUNT\s*\(", re.IGNORECASE)
_ORDER_BY_CLAUSE_RE = re.compile(
    r"\bORDER\s+BY\b(.*?)(?:\bLIMIT\b|\bOFFSET\b|\)|;|$)", re.IGNORECASE | re.DOTALL)
_ORDER_DIRECTION_RE = re.compile(r"\s+(ASC|DESC)\s*$", re.IGNORECASE)

# Metrics the pipeline projects by default on entity rows (FASTAPI-TEXT2SQL-350, -351). A list
# of actors carries POPULARITY, an image wall VOTE_AVERAGE, a movie list IMDB_RATING_WEIGHTED
# (the prompt's default sort, kept even for "best rated"), a collection or location list
# IMDB_RATING and the stored MOVIE_COUNT / SERIE_COUNT, and each is ordered on it, so "one
# metric plus ORDER BY" fired ranked-bars on 103 plain lists of the 2026-10-29 campaign. They
# are sort keys, not the measure the question asked for: never a ranking on their own. The
# exception is a COMPUTED column that happens to reuse one of these names (`COUNT(DISTINCT
# T_WC_T2S_MOVIE.ID_MOVIE) AS MOVIE_COUNT` for "directors with the most films"): an aggregate
# the model wrote is the measure the question asked for (_COMPUTED_ALIAS_RE below).
# A ranking on a rating stays a grid in phase 0: the SQL alone cannot tell "ordered by IMDb
# rating because asked" (2216) from the default sort of a collection list (2481); the intent of
# phase 1 (FASTAPI-TEXT2SQL-353, -354) breaks that tie, and a grid is the cheaper miss.
_DEFAULT_ENTITY_METRICS = frozenset({
    "POPULARITY", "VOTE_AVERAGE", "VOTE_COUNT", "IMDB_VOTES", "IMDB_RATING", "IMDB_RATING_WEIGHTED",
    "MOVIE_COUNT", "SERIE_COUNT",
})


def _is_computed_alias(sql, name):
    """Tell whether `name` is the alias of an expression in the SQL (`... ) AS name`).

    A stored column is projected bare (`T_WC_T2S_LOCATION.MOVIE_COUNT`); an aggregate or any
    parenthesised expression the model wrote closes with `)` right before its alias.
    """
    return re.search(r"\)\s*AS\s+`?" + re.escape(name) + r"`?(?!\w)", sql or "",
                     re.IGNORECASE) is not None


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
    if _FLAG_RE.search(name) or _OTHER_ID_RE.search(name) or _GENDER_RE.search(name):
        return "other"
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
        unit = _unit_for(name) if role == "metric" else None  # a date (BIRTH_YEAR) is a point in time, never "years" (2026-11-08)
        columns.append({"name": name, "role": role, "unit": unit})
    return columns


def _split_order_terms(clause):
    """Split an ORDER BY clause on the commas outside parentheses, stripped, empties dropped."""
    terms, current, depth = [], [], 0
    for ch in clause:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            terms.append("".join(current))
            current = []
        else:
            current.append(ch)
    terms.append("".join(current))
    return [t.strip() for t in terms if t.strip()]


def _order_key(sql, columns):
    """Return (column name, "asc" | "desc") for the column the outer ORDER BY sorts on first.

    Reads the last ORDER BY clause of the SQL (the outer query's) and walks its terms in
    order; the first one that resolves to a projected column, by name or alias (optionally
    table-qualified or backquoted) or by its 1-based position, wins. A term that resolves to
    nothing is skipped, which is what lets the NULLs-last guard the prompt prescribes
    (`CASE WHEN x IS NULL THEN 1 ELSE 0 END, x ASC`) name `x` (FASTAPI-TEXT2SQL-155). A
    bare "ORDER BY" elsewhere in the query is not enough (FASTAPI-TEXT2SQL-350).

    Returns (None, None) when there is no ORDER BY or no term resolves.
    """
    clauses = _ORDER_BY_CLAUSE_RE.findall(sql or "")
    if not clauses:
        return None, None
    names = [c["name"] for c in columns]
    for term in _split_order_terms(clauses[-1]):
        direction = "desc" if re.search(r"\bDESC\s*$", term, re.IGNORECASE) else "asc"
        body = _ORDER_DIRECTION_RE.sub("", term).strip()
        for name in names:
            if re.fullmatch(r"(?:\w+\.)?`?" + re.escape(name) + r"`?", body, re.IGNORECASE):
                return name, direction
        if body.isdigit() and 1 <= int(body) <= len(names):
            return names[int(body) - 1], direction
    return None, None


def _is_entity_ranking(sql, order_col, columns, result_entity):
    """Decide whether N entity rows are a ranking (ranked-bars) rather than a grid.

    A ranking is the metric the outer ORDER BY names, whatever else is projected
    (FASTAPI-TEXT2SQL-351: the standard movie projection carries four metrics, so "exactly
    one metric" missed every "highest grossing" or "most seasons" question). All must hold:
    the outer ORDER BY resolves to a projected column (`order_col`), that column has the
    metric role, it is not a default sort key (POPULARITY, IMDB_RATING_WEIGHTED, a stored
    MOVIE_COUNT...) unless the model computed it, and the rows are not images.
    """
    if not order_col:
        return False
    column = next((c for c in columns if c["name"] == order_col), None)
    if column is None or column["role"] != "metric":
        return False
    if order_col.upper() in _DEFAULT_ENTITY_METRICS and not _is_computed_alias(sql, order_col):
        return False
    names = {c["name"].upper() for c in columns}
    if str(result_entity or "").lower().endswith("_image") or {"ID_ROW", "TYPE_IMAGE"} <= names:
        return False
    return True


def _is_image_rows(columns, result_entity):
    names = {c["name"].upper() for c in columns}
    return str(result_entity or "").lower().endswith("_image") or {"ID_ROW", "TYPE_IMAGE"} <= names


def _focus_names(intent, columns):
    """The projected metric or date columns the intent's focus names, in projection order.

    Uses `intent["focus_columns"]` when the caller already resolved them, else maps
    `intent["focus"]` through result_intent.focus_columns (lazy import, so this module still
    loads on its own, as the census loads it from a file path).
    """
    if not isinstance(intent, dict):
        return []
    names = intent.get("focus_columns")
    if not isinstance(names, list):
        try:
            import result_intent
            names = result_intent.focus_columns(intent.get("focus") or [], columns)
        except ImportError:
            names = []
    by_name = {c["name"]: c for c in columns}
    return [n for n in names if n in by_name and by_name[n]["role"] in ("metric", "date")]


def _value_column(sql, columns, focus, order_col):
    """The column that carries the quantity of each row, or None.

    The intent's focus first; else the ordered metric when it is the measure the model chose
    (not a default sort key, or computed); else a metric the model added to the standard
    projection (a computed alias, or a metric outside the default sort keys and RUNTIME, which
    every movie row carries).
    """
    if focus:
        return focus[0]
    by_name = {c["name"]: c for c in columns}
    if order_col and by_name.get(order_col, {}).get("role") == "metric" and (
            order_col.upper() not in _DEFAULT_ENTITY_METRICS or _is_computed_alias(sql, order_col)):
        return order_col
    for c in columns:
        if c["role"] != "metric":
            continue
        name = c["name"].upper()
        if _is_computed_alias(sql, c["name"]) or (name not in _DEFAULT_ENTITY_METRICS and name != "RUNTIME"):
            return c["name"]
    return None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 4)


def _summary_facts(sql, rows, result_rows, columns, value_col, order_col, order_dir):
    """Language-neutral numbers about the result; each front writes the sentence.

    count: the rows returned (one page; `total` stays None, decision of 2026-10-31: no second
    count query, the fronts say "the first N"); unit and value_column: the quantity shown;
    order: "collection", "date", a metric column name, or None; top: the row with the extreme
    value (the minimum when the SQL sorts that column ascending, else the maximum), with its
    label, entity id and row index.
    """
    by_name = {c["name"]: c for c in columns}
    clauses = _ORDER_BY_CLAUSE_RE.findall(sql or "")
    order = None
    if clauses and _COLLECTION_ORDER_RE.search(clauses[-1]):
        order = "collection"
    elif order_col and by_name.get(order_col, {}).get("role") == "date":
        order = "date"
    elif order_col and by_name.get(order_col, {}).get("role") == "metric":
        order = order_col
    facts = {
        "count": len(rows),
        "total": None,
        "value_column": value_col,
        "unit": by_name[value_col]["unit"] if value_col in by_name else None,
        "order": order,
        "order_direction": order_dir if order else None,
        "top": None,
    }
    if value_col not in by_name or by_name[value_col]["role"] != "metric" or len(rows) < 2:
        return facts
    label_col = next((c["name"] for c in columns if c["role"] == "label"), None)
    id_col = next((c["name"] for c in columns if c["role"] == "entity_id"), None)
    lowest = order_col == value_col and order_dir == "asc"
    best = None
    for i, row in enumerate(rows):
        v = _number(row.get(value_col)) if _is_numeric(row.get(value_col)) else None
        if v is None:
            continue
        if best is None or (v < best[1] if lowest else v > best[1]):
            best = (i, v)
    if best is not None:
        i, v = best
        raw = result_rows[i] if i < len(result_rows) and isinstance(result_rows[i], dict) else {}
        facts["top"] = {
            "label": rows[i].get(label_col) if label_col else None,
            "id": rows[i].get(id_col) if id_col else None,
            "index": raw.get("index", i) if "data" in raw else i,
            "value": v,
            "extreme": "min" if lowest else "max",
        }
    return facts


def _fold_label(value):
    """A title folded for comparison: lowercase, accents stripped, spaces collapsed."""
    table = str.maketrans("àâäáãåéèêëíìîïóòôöõúùûüçñœæ", "aaaaaaeeeeiiiiooooouuuucnoe")
    return " ".join(str(value or "").lower().translate(table).split())


def _same_label(rows, columns):
    """True when every row carries the same non-empty label: homonyms of the one title asked for."""
    label_col = next((c["name"] for c in columns if c["role"] == "label"), None)
    if not label_col:
        return False
    labels = {_fold_label(r.get(label_col)) for r in rows}
    return len(labels) == 1 and "" not in labels


def _compare_columns(focus, value_col, by_name):
    """The quantities a comparison shows: the focus columns, else the value column; two at most.

    A date part (BIRTH_MONTH) is dropped, and so is IMDB_RATING_WEIGHTED beside IMDB_RATING
    (the "rating" focus names both; the weighted one is the prompt's sort key, not the rating).
    """
    names = [n for n in (focus or ([value_col] if value_col else []))
             if n in by_name and by_name[n]["role"] in ("metric", "date") and not _DATE_PART_RE.search(n)]
    upper = {n.upper() for n in names}
    if "IMDB_RATING" in upper:
        names = [n for n in names if n.upper() != "IMDB_RATING_WEIGHTED"]
    return names[:_COMPARE_MAX_COLUMNS]


def _comparable(value):
    """A cell as a number to compare: a metric, a year, or the year-month-day of a date string."""
    if _is_numeric(value):
        return float(value)
    if isinstance(value, (date, datetime)):
        return float(value.strftime("%Y%m%d"))
    m = re.match(r"^\s*(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", str(value or ""))
    if m:
        return float(m.group(1) + (m.group(2) or "00") + (m.group(3) or "00"))
    return None


def _winners(rows, columns, compare_cols, order_col, order_dir):
    """One entry per compared quantity: the row that wins it, or a tie, or no winner.

    The row the outer ORDER BY puts first wins the column it sorts on (the model ordered the
    answer: "who was born first" sorts BIRTH_YEAR ascending); another metric is won by its
    maximum; another date has no direction, so no winner. Equal values are a tie.
    """
    by_name = {c["name"]: c for c in columns}
    label_col = next((c["name"] for c in columns if c["role"] == "label"), None)
    id_col = next((c["name"] for c in columns if c["role"] == "entity_id"), None)
    out = []
    for name in compare_cols:
        role = by_name[name]["role"]
        values = [(i, _comparable(r.get(name))) for i, r in enumerate(rows)]
        values = [(i, v) for i, v in values if v is not None]
        entry = {"column": name, "unit": by_name[name].get("unit"), "role": role,
                 "index": None, "id": None, "label": None, "value": None, "extreme": None, "tie": False}
        if len(values) >= 2 and len({v for _, v in values}) == 1:
            entry["tie"] = True
        elif values:
            if name == order_col and values[0][0] == 0:
                index = 0
                if role == "metric":
                    extreme = "min" if order_dir == "asc" else "max"
                else:
                    extreme = "earliest" if order_dir == "asc" else "latest"
            elif role == "metric":
                index, extreme = max(values, key=lambda iv: iv[1])[0], "max"
            else:
                index, extreme = None, None
            if index is not None:
                raw = rows[index].get(name)
                entry.update({"index": index, "id": rows[index].get(id_col) if id_col else None,
                              "label": rows[index].get(label_col) if label_col else None,
                              "value": _number(raw) if _is_numeric(raw) else raw, "extreme": extreme})
        out.append(entry)
    return out


def _fact(rows, columns, fact_col):
    """The fact of a fact-card: the first row and the value of the column the question asked for."""
    by_name = {c["name"]: c for c in columns}
    label_col = next((c["name"] for c in columns if c["role"] == "label"), None)
    id_col = next((c["name"] for c in columns if c["role"] == "entity_id"), None)
    raw = rows[0].get(fact_col)
    return {"index": 0, "id": rows[0].get(id_col) if id_col else None,
            "label": rows[0].get(label_col) if label_col else None,
            "column": fact_col, "role": by_name[fact_col]["role"], "unit": by_name[fact_col].get("unit"),
            "value": _number(raw) if _is_numeric(raw) else raw, "others": len(rows) - 1}


def _aggregate_alias(sql, name, functions=("COUNT", "SUM")):
    """Tell whether `name` is the alias of a COUNT (or SUM) the model wrote: `COUNT(DISTINCT x) AS name`.

    The aggregate must be the whole expression before the alias, so a ratio of two counts
    (`COUNT(...) / NULLIF(COUNT(...), 0) AS FILM_SHARE`) is not a count.
    """
    funcs = "|".join(functions)
    return re.search(r"\b(?:" + funcs + r")\s*\((?:[^()]|\([^()]*\))*\)\s*AS\s+`?" + re.escape(name) + r"`?(?!\w)",
                     sql or "", re.IGNORECASE) is not None


def _limit_truncates(sql, row_count):
    """True when the outer LIMIT may have cut the rows: they reach it (a page, a top N) or an OFFSET skips some."""
    matches = list(_LIMIT_RE.finditer(sql or ""))
    if not matches:
        return False
    m = matches[-1]
    if m.group(2):
        offset, limit = int(m.group(1)), int(m.group(2))
    else:
        limit, offset = int(m.group(1)), int(m.group(3) or 0)
    return offset > 0 or row_count >= limit


def _bin_step(lows):
    """The regular step of sorted bin starts (the greatest common divisor of their gaps), or None."""
    decimals = 0
    for v in lows:
        text = repr(float(v))
        if "e" in text:
            return None
        decimals = max(decimals, len(text.split(".")[1].rstrip("0")) if "." in text else 0)
    if decimals > 4:
        return None
    scale = 10 ** decimals
    ints = [round(float(v) * scale) for v in lows]
    step = 0
    for a, b in zip(ints, ints[1:]):
        if b > a:
            step = gcd(step, b - a)
    return _number(step / scale) if step else None


def _histogram(sql, rows, columns, order_col):
    """The bins of a histogram, or None (phase 2 lot C).

    The rows must already be bins: a grouped aggregate with no entity, exactly one COUNT the model
    wrote (the measure), and every other column a bin of one quantity: one or two numeric columns
    whose name says the quantity or the bin (RATING_BAND, RUNTIME_RANGE_START and _END,
    NUMBER_OF_SEASONS, IMDB_RATING), or one text column so named (a CASE label "under 90 min")
    when the rows are not ordered by the count. A year or a decade is a date, never a bin
    (trend-columns); a numeric code (GENDER) is a category (share-bar). The API never bins entity
    rows itself.

    Numeric bins come back sorted by their start; when the starts are regular, the bins missing
    between two filled ones are added with a count of 0 (`empty`), up to _HISTOGRAM_MAX_FILLED_BINS,
    so an empty range shows as a gap and not as nothing. A row whose bin is NULL is counted apart.
    """
    if len(rows) < 2 or not _GROUP_BY_RE.search(sql or ""):
        return None
    measures = [c for c in columns if c["role"] == "metric" and _aggregate_alias(sql, c["name"], ("COUNT",))]
    if len(measures) != 1:
        return None
    measure = measures[0]
    others = [c for c in columns if c is not measure]
    if not others or any(c["role"] in ("entity_id", "date") for c in others):
        return None
    numeric = [c for c in others if c["role"] == "metric" and _BIN_NAME_RE.search(c["name"])]
    facts = {"column": None, "high_column": None, "unit": None, "width": None, "value_column": measure["name"],
             "bins": [], "total": 0, "unbinned": 0}
    if numeric and len(numeric) == len(others) and len(numeric) <= 2:
        low_col, high_col = numeric[0], None
        if len(numeric) == 2:
            first_high, second_high = (bool(_BIN_HIGH_RE.search(c["name"])) for c in numeric)
            if second_high and not first_high:
                low_col, high_col = numeric
            elif first_high and not second_high:
                high_col, low_col = numeric
            else:
                return None
        binned = []
        for i, row in enumerate(rows):
            count = _number(row.get(measure["name"])) if _is_numeric(row.get(measure["name"])) else None
            low = row.get(low_col["name"])
            if count is None:
                continue
            if not _is_numeric(low):
                facts["unbinned"] += count
                continue
            high = row.get(high_col["name"]) if high_col else None
            binned.append((float(low), i, _number(high) if _is_numeric(high) else None, count))
        if len(binned) < 2:
            return None
        binned.sort()
        width = _bin_step([b[0] for b in binned])
        facts.update({"column": low_col["name"], "high_column": high_col["name"] if high_col else None,
                      "unit": low_col.get("unit"), "width": width})
        by_low = {round(b[0], 6): b for b in binned}
        lo, hi = binned[0][0], binned[-1][0]
        fill = width and (hi - lo) / width + 1 <= _HISTOGRAM_MAX_FILLED_BINS
        lows = ([lo + k * width for k in range(int(round((hi - lo) / width)) + 1)] if fill else [b[0] for b in binned])
        for low in lows:
            b = by_low.get(round(low, 6))
            if b:
                facts["bins"].append({"index": b[1], "low": _number(b[0]), "high": b[2], "label": None,
                                      "value": b[3], "empty": False})
            else:
                facts["bins"].append({"index": None, "low": _number(low), "high": None, "label": None,
                                      "value": 0, "empty": True})
        low_col["bin"] = "low"
        if high_col:
            high_col["bin"] = "high"
    elif (len(others) == 1 and others[0]["role"] in ("label", "other") and _BIN_NAME_RE.search(others[0]["name"])
          and isinstance(_first_non_null(rows, others[0]["name"]), str) and order_col != measure["name"]):
        label_col = others[0]
        for i, row in enumerate(rows):
            count = _number(row.get(measure["name"])) if _is_numeric(row.get(measure["name"])) else None
            if count is None:
                continue
            if row.get(label_col["name"]) in (None, ""):
                facts["unbinned"] += count
                continue
            facts["bins"].append({"index": i, "low": None, "high": None, "label": row.get(label_col["name"]),
                                  "value": count, "empty": False})
        if len(facts["bins"]) < 2:
            return None
        facts["column"] = label_col["name"]
        label_col["bin"] = "label"
    else:
        return None
    facts["total"] = _number(sum(b["value"] for b in facts["bins"]) + facts["unbinned"])
    peak = max(range(len(facts["bins"])), key=lambda k: facts["bins"][k]["value"])
    facts["peak"] = peak
    return facts


def _label_column(columns, rows):
    """The column that names each row of a grouped result: a label, else a code, a text or a gender."""
    named = next((c for c in columns if c["role"] == "label"), None)
    if named:
        return named
    return next((c for c in columns if c["role"] == "other" and (
        _CODE_RE.search(c["name"]) or _GENDER_RE.search(c["name"])
        or isinstance(_first_non_null(rows, c["name"]), str))), None)


def _share(sql, rows, columns, has_entity, is_images):
    """Parts of a whole for a share bar, or None (phase 2 lot C).

    Two shapes. One share: one row, no entity, no GROUP BY, one metric named as a share
    (FILM_SHARE, PERCENT_OF_FILMS) between 0 and 1, or between 0 and 100 when the name says
    percent or the value is above 1: the part and the rest. Parts: two to eight rows, one COUNT or
    SUM the model wrote and no other metric, a column that names each part (a label, a code, a
    text, GENDER), every value zero or more, and a complete result (the outer LIMIT did not cut it,
    no OFFSET): the shares are of the sum of the rows shown, never of a page.
    """
    if len(rows) == 1 and not has_entity and not _GROUP_BY_RE.search(sql or ""):
        metrics = [c for c in columns if c["role"] == "metric"]
        if len(metrics) != 1 or not _SHARE_NAME_RE.search(metrics[0]["name"]):
            return None
        raw = rows[0].get(metrics[0]["name"])
        value = _number(raw) if _is_numeric(raw) else None
        if value is None:
            return None
        scale = 100 if (_PERCENT_NAME_RE.search(metrics[0]["name"]) or value > 1) else 1
        part = value / scale
        if not 0 <= part <= 1:
            return None
        return {"kind": "single", "value_column": metrics[0]["name"], "label_column": None,
                "scale": scale, "total": None,
                "parts": [{"index": 0, "label": None, "value": value, "share": round(part, 4), "rest": False},
                          {"index": None, "label": None, "value": None, "share": round(1 - part, 4), "rest": True}]}
    if not (_SHARE_MIN_PARTS <= len(rows) <= _SHARE_MAX_PARTS) or is_images:
        return None
    metrics = [c for c in columns if c["role"] == "metric"]
    if len(metrics) != 1 or not _aggregate_alias(sql, metrics[0]["name"]):
        return None
    label = _label_column(columns, rows)
    if label is None or _limit_truncates(sql, len(rows)):
        return None
    values = [_number(r.get(metrics[0]["name"])) if _is_numeric(r.get(metrics[0]["name"])) else None for r in rows]
    if any(v is None or v < 0 for v in values) or not sum(values):
        return None
    total = sum(values)
    return {"kind": "parts", "value_column": metrics[0]["name"], "label_column": label["name"], "scale": 1,
            "total": _number(total),
            "parts": [{"index": i, "label": rows[i].get(label["name"]), "value": v,
                       "share": round(v / total, 4), "rest": False} for i, v in enumerate(values)]}


def _countries(sql, rows, columns, has_entity, id_columns):
    """The countries of a flag list, or None (phase 2 lot C).

    Three shapes, each giving one ISO 3166-1 alpha-2 code per row for the flag (result_countries):
    (a) no entity: a country code column (COUNTRY_CODE, ORIGIN_COUNTRY, COUNTRY_OF_BIRTH grouped)
    and at most one metric, the count drawn beside the flag; (b) location rows of type country
    (LOCATION_TYPE projected as 'country', or the SQL filters on it), two or more: the code comes
    from the place's name (Wikidata's English label; England, Scotland and Wales give GB and keep
    their own name); (c) one entity repeated once per country (a film and its production
    countries), two rows or more. A person list carrying COUNTRY_OF_BIRTH stays a person list.
    """
    if not rows:
        return None
    try:
        import result_countries
    except ImportError:
        return None
    by_name = {c["name"]: c for c in columns}

    def code_column():
        for c in columns:
            if not _COUNTRY_COLUMN_RE.search(c["name"]) or c["role"] not in ("label", "other"):
                continue
            # Two letters on every row, and a known code on nine rows in ten at least (TMDb files a
            # few productions under codes no table holds).
            values = [str(r.get(c["name"])).strip() for r in rows if r.get(c["name"]) not in (None, "")]
            known = sum(1 for v in values if result_countries.is_code(v))
            if values and all(len(v) == 2 and v.isalpha() for v in values) and known >= 0.9 * len(values):
                return c
        return None

    def entry(i, code, label, value=None):
        code = str(code).upper() if code else None
        return {"index": i, "code": code, "label": label, "value": value,
                "name": result_countries.names_for(code) if code else None,
                "flag": bool(code) and code in result_countries.NAMES,
                "numeric": result_countries.numeric_for(code) if code else None}

    out = None
    if not has_entity:
        col = code_column()
        metrics = [c for c in columns if c["role"] == "metric"]
        if col is None or len(metrics) > 1:
            return None
        value_col = metrics[0]["name"] if metrics else None
        out = {"source": "codes", "column": col["name"], "value_column": value_col,
               "countries": [entry(i, r.get(col["name"]) or None, None,
                                   _number(r.get(value_col)) if value_col and _is_numeric(r.get(value_col)) else None)
                             for i, r in enumerate(rows)]}
    elif len(rows) >= 2 and "ID_LOCATION" in by_name and (
            all(str(r.get("LOCATION_TYPE") or "").lower() == "country" for r in rows) if "LOCATION_TYPE" in by_name
            else _LOCATION_COUNTRY_SQL_RE.search(sql or "")):
        label = next((c["name"] for c in columns if c["role"] == "label"), None)
        if label is None:
            return None
        found = []
        for i, r in enumerate(rows):
            code = result_countries.code_for_name(r.get(label)) or result_countries.code_for_name(r.get("LOCATION_NAME_FR"))
            found.append(entry(i, code, r.get(label)))
        if not any(f["code"] for f in found):
            return None
        out = {"source": "locations", "column": label, "value_column": None, "countries": found}
    elif len(rows) >= 2:
        id_col = next((c["name"] for c in columns if c["role"] == "entity_id"), None)
        col = code_column()
        if id_col is None or col is None or len({r.get(id_col) for r in rows}) != 1:
            return None
        seen, found = set(), []
        for i, r in enumerate(rows):
            code = str(r.get(col["name"]) or "").upper()
            if code and code not in seen:
                seen.add(code)
                found.append(entry(i, code, None))
        if len(found) < 2:
            return None
        out = {"source": "repeated", "column": col["name"], "value_column": None, "countries": found}
    return out


def _scatter_quantity(column):
    """The quantity a column carries on a scatter axis: "year" for a date, a named quantity, else
    "other:<name>" (each unnamed metric is its own quantity)."""
    if column["role"] == "date":
        return "year"
    for quantity, rx in _SCATTER_QUANTITIES:
        if rx.search(column["name"]):
            return quantity
    return "count" if column.get("unit") == "count" else "other:" + column["name"].upper()


def _scatter_value(value, quantity):
    """A cell as a number on its axis, or None when missing. A date gives its year. Zero is a
    missing value except on a count (TMDb stores an unknown budget, revenue or runtime as 0)."""
    if quantity == "year":
        if _is_numeric(value):
            v = float(value)
        elif isinstance(value, (date, datetime)):
            v = float(value.year)
        else:
            m = re.match(r"^\s*(\d{4})", str(value or ""))
            v = float(m.group(1)) if m else None
        return v if v and v > 0 else None
    if not _is_numeric(value):
        return None
    v = float(value)
    if quantity == "count":
        return v if v >= 0 else None
    return v if v > 0 else None


def _scatter(rows, result_rows, columns, focus):
    """summary_facts.scatter, or None: entity rows plotted over exactly two quantities.

    The two quantities are the ones the intent's focus names (projected metric or date columns);
    one column per quantity (IMDB_RATING over its weighted twin, a numeric year over a date
    string). Three quantities or more is not a scatter (which two?), one is a ranking or cards.
    Rows missing either value are left out and counted per axis; five points at least.
    """
    by_name = {c["name"]: c for c in columns}
    picked = {}
    for name in focus or []:
        column = by_name.get(name)
        if column is None or column["role"] not in ("metric", "date") or _DATE_PART_RE.search(name):
            continue
        quantity = _scatter_quantity(column)
        current = picked.get(quantity)
        if current is None:
            picked[quantity] = column
        elif quantity == "rating" and "WEIGHTED" in current["name"].upper() and "WEIGHTED" not in name.upper():
            picked[quantity] = column
        elif quantity == "year" and not _is_numeric(_first_non_null(rows, current["name"])) and _is_numeric(
                _first_non_null(rows, name)):
            picked[quantity] = column
    if len(picked) != 2:
        return None

    def rank(quantity):
        key = "other" if quantity.startswith("other:") else quantity
        return _SCATTER_X_ORDER.index(key) if key in _SCATTER_X_ORDER else len(_SCATTER_X_ORDER)

    (qx, cx), (qy, cy) = sorted(picked.items(), key=lambda kv: (rank(kv[0]), kv[1]["name"]))
    label_col = next((c["name"] for c in columns if c["role"] == "label"), None)
    id_col = next((c["name"] for c in columns if c["role"] == "entity_id"), None)
    points, missing_x, missing_y = [], 0, 0
    for i, row in enumerate(rows):
        x = _scatter_value(row.get(cx["name"]), qx)
        y = _scatter_value(row.get(cy["name"]), qy)
        missing_x += x is None
        missing_y += y is None
        if x is None or y is None:
            continue
        raw = result_rows[i] if i < len(result_rows) and isinstance(result_rows[i], dict) else {}
        points.append({
            "index": raw.get("index", i) if "data" in raw else i,
            "label": row.get(label_col) if label_col else None,
            "id": row.get(id_col) if id_col else None,
            "x": _number(x),
            "y": _number(y),
        })
    if len(points) < _SCATTER_MIN_POINTS:
        return None

    def axis(column, quantity, values):
        if quantity == "year":
            unit = "year"
        elif quantity in ("rating", "votes"):
            unit = quantity
        else:
            unit = column.get("unit")
        lo, hi = min(values), max(values)
        scale = "log" if quantity == "votes" and lo > 0 and hi / lo >= _SCATTER_LOG_RATIO else "linear"
        return {"column": column["name"], "quantity": "other" if quantity.startswith("other:") else quantity,
                "unit": unit, "scale": scale, "min": lo, "max": hi}

    xs = [p["x"] for p in points]
    ys = [p["y"] for p in points]
    return {
        "x": axis(cx, qx, xs),
        "y": axis(cy, qy, ys),
        "points": points,
        "count": len(rows),
        "plotted": len(points),
        "left_out": len(rows) - len(points),
        "missing": {"x": missing_x, "y": missing_y},
        "extremes": {"x_min": xs.index(min(xs)), "x_max": xs.index(max(xs)),
                     "y_min": ys.index(min(ys)), "y_max": ys.index(max(ys))},
    }


def _map_steps(values):
    """The shading steps of a map, light to dark: [{"min", "max"}], each the smallest and the
    largest value of the countries it holds, or [] with no value. Five distinct values or fewer
    give one step each; more are cut at the quantiles, a value never split across two steps."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return []
    distinct = sorted(set(vals))
    if len(distinct) <= _MAP_STEPS:
        return [{"min": _number(v), "max": _number(v)} for v in distinct]
    n = len(vals)
    bounds = sorted({vals[0]} | {vals[(i * n) // _MAP_STEPS] for i in range(1, _MAP_STEPS)})
    steps = []
    for i, lo in enumerate(bounds):
        hi = bounds[i + 1] if i + 1 < len(bounds) else None
        members = [v for v in vals if v >= lo and (hi is None or v < hi)]
        if members:
            steps.append({"min": _number(members[0]), "max": _number(members[-1])})
    return steps


def _map(countries):
    """summary_facts.map (phase 3 lot B): what the two fronts need beyond summary_facts.countries
    to shade the same countries the same way. located: the countries with an ISO numeric code
    (the outline is keyed by it); unlocated: the indexes, in countries.countries, of the others
    (a dissolved state, Kosovo), which the fronts list under the map; steps: the shading."""
    entries = countries["countries"]
    return {
        "count": len(entries),
        "located": sum(1 for c in entries if c.get("numeric")),
        "unlocated": [i for i, c in enumerate(entries) if not c.get("numeric")],
        "value_column": countries["value_column"],
        "steps": _map_steps([c["value"] for c in entries if c.get("numeric")]) if countries["value_column"] else [],
    }


def _with_option(options, rep):
    """`options` with `rep` added before "table" (the fallback stays last)."""
    if rep in options:
        return options
    if "table" in options:
        k = options.index("table")
        return options[:k] + [rep] + options[k:]
    return options + [rep]


def _options(representation, family, has_value_col, has_bar_col, has_time_axis=False, has_sequence=False,
             has_compare=False):
    """The valid representations for the shape, default first (FASTAPI-TEXT2SQL-354).

    Phase 2 lot A: a timeline when the value column is a date, a sequence strip when the rows
    come in date or collection order; the other forms of the shape stay offered beside them.
    Phase 2 lot B: compare cards for two to four entities with a quantity. The fact card and the
    verdict are put first by the caller, over the options of the shape they stand on.
    """
    if family == "entity_many":
        candidates = ["card-grid"] + (["timeline"] if has_time_axis else []) + (
            ["sequence-strip"] if has_sequence else []) + (["compare-cards"] if has_compare else []) + (
            ["value-cards"] if has_value_col else []) + (["ranked-bars"] if has_bar_col else []) + ["table"]
    elif family == "entity_images":
        candidates = ["card-grid", "table"]
    elif family == "entity_one":
        candidates = ["entity-page", "table"]
    else:
        candidates = [representation, "table"]
    out = [representation]
    for c in candidates:
        if c not in out:
            out.append(c)
    return out


def classify_result(sql_query, result_rows, result_entity="", id_columns=None, intent=None):
    """Classify a result into its rendering hint. Pure, no DB, no LLM.

    The intent (FASTAPI-TEXT2SQL-353, -354) is a prior, never an order: it picks within the
    representations the shape allows and never invents one the rows cannot carry. Without an
    intent, `representation` is exactly what the shape rules of -349 to -351 give.

    Args:
        sql_query: The SQL actually executed (used only to break a shape tie).
        result_rows: The response `result` list, items shaped `{"index", "data"}`; a list
            of plain dicts is accepted too.
        result_entity: The answer entity the pipeline settled on ("" for an aggregate).
        id_columns: The authoritative set of entity id column names; defaults to the
            module's own copy of _RESULT_ENTITY_SOURCES.
        intent: The core intent {task, focus, requested_view, source} of result_intent.py
            (optionally with `focus_columns` already resolved), or None.

    Returns:
        A dict with:
          - result_kind: one of RESULT_KINDS;
          - columns: list of {name, role, unit}, in projection order (empty with no rows);
            the one column the outer ORDER BY sorts on first, when it is projected, also
            carries `"ordered": "asc" | "desc"` (FASTAPI-TEXT2SQL-351), so a client draws
            the ranked quantity and not the first metric it meets; the column(s) carrying the
            quantity of each row carry `"focus": true` (-354: the intent's focus, else the
            value column the shape rules found);
          - representation: one of REPRESENTATIONS;
          - representation_options: the valid representations for this shape, default first
            (always contains `representation`); what the fronts offer as override chips;
          - summary_facts: language-neutral numbers (count, total, value_column, unit, order,
            order_direction, top), or None with no rows; phase 2 lot B adds `winners` when
            compare-cards is an option, `fact` on a fact-card, `verdict` and `verdict_basis` on
            a verdict (an empty verdict is the one rowless result with summary_facts); phase 2
            lot C `histogram`, `share`, `countries`, phase 3 lot A `scatter`, lot B `map` (with
            `countries`, whose entries carry their ISO `numeric` code), each where its
            representation is an option.
    """
    ids = frozenset(id_columns) if id_columns is not None else _DEFAULT_ID_COLUMNS
    result_rows = list(result_rows or [])
    rows = [
        (r.get("data", r) if isinstance(r, dict) else {})
        for r in result_rows
    ]
    columns = _columns_metadata(rows, ids)
    sql = sql_query or ""
    order_col, order_dir = _order_key(sql, columns)
    for c in columns:
        if c["name"] == order_col:
            c["ordered"] = order_dir
    task = str((intent or {}).get("task") or "") if isinstance(intent, dict) else ""
    requested_view = str((intent or {}).get("requested_view") or "") if isinstance(intent, dict) else ""
    focus = _focus_names(intent, columns)
    by_name = {c["name"]: c for c in columns}
    # The result is entity rows only when it actually projects an entity id column. NOT when
    # result_entity is merely set: the answer-entity classifier returns "movie" even for
    # "how many movies are there", whose result is a one-row scalar count with no id column
    # (MOVIE_COUNT alone). Keying the branch on result_entity there drew the count as an
    # entity page. The column structure is the authority; every genuine entity projection
    # carries its ID_ column. result_entity is kept in the signature for callers and future
    # use, but does not decide the shape.
    has_entity = any(c["role"] == "entity_id" for c in columns)
    order_clauses = _ORDER_BY_CLAUSE_RE.findall(sql)
    in_sequence = bool(order_clauses and _COLLECTION_ORDER_RE.search(order_clauses[-1])) or (
        by_name.get(order_col, {}).get("role") == "date")
    metric_cols = [c for c in columns if c["role"] == "metric"]
    label_cols = [c for c in columns if c["role"] == "label"]
    value_col = None
    family = "other"
    compare_cols = []
    ranking = False
    histogram = None
    scatter = None

    # Entity rows: one entity is a page, many are a grid, many ordered by a metric is a
    # ranking (the poster-versus-bar choice is the client's, VOICE-AGENT-244). A ranking is
    # the metric the outer ORDER BY names, whatever else is projected (FASTAPI-TEXT2SQL-351),
    # a metric that is not a default sort key, and no image rows (FASTAPI-TEXT2SQL-350); a
    # plain list ordered by POPULARITY or IMDB_RATING_WEIGHTED stays a grid, and so does a
    # sequence ordered by a date or a collection order.
    # With an intent (-354): a value per item or a comparison with its quantity projected is
    # `value-cards`, whatever the order; a ranking the question asks for is `ranked-bars` when
    # the outer ORDER BY is on a metric the question names (the rating rankings 2573 and 2578,
    # which the SQL alone cannot tell from the default sort), or on any metric when the
    # question names none.
    if has_entity:
        if len(rows) <= 1:
            kind, representation = "entity_rows", ("entity-page" if rows else "card-grid")
            family = "entity_one" if rows else "empty"
        elif _is_image_rows(columns, result_entity):
            kind, representation, family = "entity_rows", "card-grid", "entity_images"
        else:
            kind, family = "entity_rows", "entity_many"
            value_col = _value_column(sql, columns, focus, order_col)
            order_is_metric = by_name.get(order_col, {}).get("role") == "metric"
            ranking = _is_entity_ranking(sql, order_col, columns, result_entity)
            # Phase 2 lot B: two to four named entities and the quantity compared, side by side.
            # A yes/no question that compares ("Is Titanic longer than Avatar?") lands here too
            # when its focus names the quantity; without a focus a verdict is an existence test.
            compare_cols = _compare_columns(focus, value_col if task == "compare" else None, by_name)
            if not (_COMPARE_MIN_ROWS <= len(rows) <= _COMPARE_MAX_ROWS):
                compare_cols = []
            if task in ("compare", "verdict") and compare_cols:
                representation = "compare-cards"
            elif task == "compare" and value_col:
                representation = "value-cards"
            elif task == "value" and value_col and not ranking and by_name.get(value_col, {}).get("role") == "date":
                # Phase 2 lot A: "when were the Alien films released?" asks for a date per
                # item, which a time axis shows better than a date under each poster.
                representation = "timeline"
            elif task == "value" and value_col and not ranking:
                representation = "value-cards"
            elif task == "sequence" and in_sequence:
                # Phase 2 lot A: "the Godfather trilogy in order", rows already in date or
                # collection order. A sequence the SQL ordered otherwise (by rating) stays a
                # grid: a numbered strip would state a wrong order.
                representation = "sequence-strip"
            elif ranking:
                representation = "ranked-bars"
            elif task == "rank" and order_is_metric and order_col in focus:
                # A default sort key (IMDB_RATING_WEIGHTED, POPULARITY) is a ranking only when
                # the question names it: "the 12 highest-rated Studio Ghibli films" is bars,
                # "the best romance movies" (no quantity named) stays a grid.
                representation = "ranked-bars"
            else:
                representation = "card-grid"
    # No rows: nothing to inspect, so result_entity is the only signal left for what was
    # searched. An empty entity search degrades to an empty card grid; anything else to a
    # table. Never an empty "Result" card. (A count never reaches here: it has one row.)
    elif not rows:
        family = "empty"
        if str(result_entity or "").strip():
            kind, representation = "entity_rows", "card-grid"
        else:
            kind, representation = "unknown", "table"
    # One row, no entity: the scalar family. A COUNT is a count, otherwise a scalar; one
    # metric is a number card, two to five a stat strip.
    elif len(rows) == 1:
        is_count = _COUNT_RE.search(sql) and len(metric_cols) == 1
        kind = "count" if is_count else "scalar"
        if 1 <= len(metric_cols) <= 5 and not _GROUP_BY_RE.search(sql):
            representation = "number-card" if len(metric_cols) == 1 else "stat-strip"
            value_col = metric_cols[0]["name"] if len(metric_cols) == 1 else None
        else:
            # A single text fact, or a shape with no metric: fall back to a table.
            kind = kind if metric_cols else "unknown"
            representation = "table"
    # Many rows, no entity: a grouped aggregate. A label plus exactly one metric, ordered,
    # is a ranking; anything wider is a table. No clean result_kind in the vocabulary, so
    # `unknown` with a usable representation.
    # With no *_NAME column, a code or text column names the group (COUNTRY_CODE for "the ten
    # countries that produced the most movies"); without it the ranking fell to a table.
    else:
        kind = "unknown"
        date_cols = [c for c in columns if c["role"] == "date"]
        trend_metric = (focus[0] if focus and by_name[focus[0]]["role"] == "metric"
                        else metric_cols[0]["name"] if len(metric_cols) == 1 else None)
        # Phase 2 lot C: rows that are bins of one quantity plus a count (read before a text bin
        # turns into a label below).
        histogram = _histogram(sql, rows, columns, order_col)
        if not label_cols:
            label_cols = [c for c in columns if c["role"] == "other" and (
                _CODE_RE.search(c["name"]) or _GENDER_RE.search(c["name"])
                or isinstance(_first_non_null(rows, c["name"]), str))][:1]
            for c in label_cols:
                c["role"] = "label"  # so a client labels the bars without guessing
        if histogram:
            # "How are Kubrick's films distributed by runtime?": one column per bin, in bin order,
            # whatever the order of the rows; never a ranking of the bins by their count.
            representation = "histogram"
            value_col = histogram["value_column"]
            family = "histogram"
        elif task == "trend" and len(date_cols) == 1 and trend_metric and not label_cols:
            # Phase 2 lot A: "how many films were released per decade", one period column
            # (year or decade) plus the metric, drawn as one column per period.
            representation = "trend-columns"
            value_col = trend_metric
            family = "trend"
        elif label_cols and len(metric_cols) == 1 and _ORDER_BY_RE.search(sql):
            representation = "ranked-bars"
            value_col = order_col if by_name.get(order_col, {}).get("role") == "metric" else metric_cols[0]["name"]
        elif task == "rank" and label_cols and by_name.get(order_col, {}).get("role") == "metric":
            # -354: "which directors made the most films" grouped with two metrics, ordered on
            # one: the question asks for the order, the ordered metric is the bar.
            representation = "ranked-bars"
            value_col = order_col
        else:
            representation = "table"
            value_col = focus[0] if focus else None

    # The columns that carry the quantity: the intent's focus, else the value column found.
    for name in (focus or ([value_col] if value_col else [])):
        if name in by_name:
            by_name[name]["focus"] = True

    # Bars need a metric worth drawing: the value column, else an ordered metric that is not a
    # default sort key ("the Godfather trilogy in order" offers no bars of IMDB_RATING_WEIGHTED).
    if by_name.get(value_col, {}).get("role") == "metric":
        bar_col = value_col
    elif by_name.get(order_col, {}).get("role") == "metric" and (
            order_col.upper() not in _DEFAULT_ENTITY_METRICS or _is_computed_alias(sql, order_col)):
        bar_col = order_col
    else:
        bar_col = None
    has_time_axis = family == "entity_many" and by_name.get(value_col, {}).get("role") == "date"
    # Offered only when the question asks for an order: every list the prompt sorts by date
    # would otherwise grow a strip chip it never asked for.
    has_sequence = family == "entity_many" and in_sequence and task == "sequence"
    options = _options(representation, family, value_col is not None, bar_col is not None,
                       has_time_axis, has_sequence, bool(compare_cols))

    # Phase 2 lot C. share-bar: offered wherever the rows are the parts of a complete whole; the
    # default when the question asks for parts ("what share", "split", "as a pie": requested_view
    # share, applied below with the other requested views) and for one share alone (FILM_SHARE
    # 0.74 is a part, never a bare 0.74). flag-list: the default wherever the rows are countries,
    # over ranked-bars or the poster grid, which stay offered.
    histogram = histogram if family == "histogram" else None
    share = None if histogram else _share(sql, rows, columns, has_entity, family == "entity_images")
    countries = None if histogram else _countries(sql, rows, columns, has_entity, ids)
    if share:
        options = _with_option(options, "share-bar")
        if share["kind"] == "single":
            representation = "share-bar"
            value_col = share["value_column"]
            options = ["share-bar"] + [o for o in options if o != "share-bar"]
    if countries:
        if share and share["kind"] == "single":
            countries = None
        else:
            representation = "flag-list"
            options = ["flag-list"] + [o for o in options if o != "flag-list"]
            if countries["value_column"] and not value_col:
                value_col = countries["value_column"]
    # Phase 3 lot B. map: offered wherever the flag list is and one country at least has a place
    # on the outline (an ISO numeric code), right after the flag list; the default only when the
    # question asks for a map (requested_view map, applied below: "on a world map", "sur une
    # carte"). The flag list stays the default otherwise: it names every country, the map hides
    # the small ones and has no place for a dissolved state.
    if countries and any(c.get("numeric") for c in countries["countries"]):
        options = [o for o in options if o != "map"]
        options.insert(options.index("flag-list") + 1 if "flag-list" in options else max(len(options) - 1, 0), "map")

    # Phase 3 lot A. scatter: entity rows over the two quantities the question names, offered
    # wherever five rows carry both; the default when the question asks how the two relate
    # (task relate: "Is there a link between runtime and rating?", "Does a bigger budget mean a
    # better rating?") or names the plot (requested_view scatter, below: "budget against revenue",
    # "en fonction de", "as a scatter plot"), and for a chart of two quantities that is not a
    # ranking ("Plot the runtime and the rating of the Ghibli films": a bar shows one quantity).
    if family == "entity_many" and not countries:
        scatter = _scatter(rows, result_rows, columns, focus)
    if scatter:
        options = _with_option(options, "scatter")
        if task == "relate" or (requested_view == "chart" and task != "rank"):
            representation = "scatter"
            options = ["scatter"] + [o for o in options if o != "scatter"]

    # Phase 2 lot B, over the options of the shape they stand on (each is put first).
    # fact-card: a value task on one entity, or on homonyms of one title (every row carries the
    # same label and the rows come in the default sort, so the first row is the title meant),
    # with a focus column projected: "How long is Lawrence of Arabia?", "When was Vertigo
    # released?" (eleven films named Vertigo).
    fact_col = None
    if task == "value" and focus and family in ("entity_one", "entity_many"):
        default_order = order_col is None or (
            order_col.upper() in _DEFAULT_ENTITY_METRICS and not _is_computed_alias(sql, order_col))
        if family == "entity_one" or (_same_label(rows, columns) and default_order and not ranking):
            fact_col = next(iter(_compare_columns(focus, None, by_name)), None)
    # verdict: a yes/no question the rows answer without reading the question again. Entity
    # rows and no focus: the SQL is an existence test ("Did Spielberg direct Jaws?"), a row is
    # Yes. No row at all: No. One count with no entity: above zero is Yes. A yes/no question
    # with a focus is a comparison (compare-cards above) and gets no Yes/No (README limits).
    verdict = basis = None
    if task == "verdict":
        if has_entity and rows and not focus and family != "entity_images":
            verdict, basis = "yes", "rows"
        elif not rows:
            verdict, basis = "no", "empty"
        elif not has_entity and len(rows) == 1 and kind == "count" and metric_cols:
            count = _number(rows[0].get(metric_cols[0]["name"]))
            if count is not None:
                verdict, basis = ("yes" if count > 0 else "no"), "count"
    if fact_col:
        representation = "fact-card"
        by_name[fact_col]["focus"] = True
    elif verdict:
        representation = "verdict"
    if representation in ("fact-card", "verdict"):
        options = [representation] + [o for o in options if o != representation]

    # An explicit "as a table" / "as a chart" / "as cards" wins when the shape allows it; a
    # compare-cards or fact-card default already is cards; a scatter chosen above already is the
    # chart of two quantities.
    keep = (requested_view == "cards" and representation in ("compare-cards", "fact-card")) or (
        requested_view == "chart" and representation == "scatter")
    for wanted in (() if keep else _REQUESTED_VIEW_REPRESENTATIONS.get(requested_view, ())):
        if wanted in options:
            representation = wanted
            options = [wanted] + [o for o in options if o != wanted]
            break
    summary = _summary_facts(sql, rows, result_rows, columns, value_col, order_col, order_dir) if rows else None
    if compare_cols and "compare-cards" in options:
        summary["winners"] = _winners(rows, columns, compare_cols, order_col, order_dir)
    if fact_col:
        summary["fact"] = _fact(rows, columns, fact_col)
    if verdict:
        if summary is None:
            summary = {"count": 0, "total": None, "value_column": None, "unit": None, "order": None,
                       "order_direction": None, "top": None}
        summary["verdict"], summary["verdict_basis"] = verdict, basis
    # Phase 2 lot C, each where its form is offered.
    if histogram and "histogram" in options:
        summary["histogram"] = histogram
    if share and "share-bar" in options:
        summary["share"] = share
    if countries and ("flag-list" in options or "map" in options):
        summary["countries"] = countries
    if countries and "map" in options:
        summary["map"] = _map(countries)
    if scatter and "scatter" in options:
        summary["scatter"] = scatter
    return {"result_kind": kind, "columns": columns, "representation": representation,
            "representation_options": options, "summary_facts": summary}
