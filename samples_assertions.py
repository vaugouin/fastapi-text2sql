"""Parse the evaluation-framework ``ASSERTIONS_QUERY_RESULT`` DSL into structured form.

Each curated sample question in ``T_WC_T2S_EVALUATION`` carries a ground-truth
assertion describing the expected result of running that question through the
Text2SQL pipeline. The assertion is a tiny expression language; across the live
samples it reduces to five shapes:

  * ``<ID_COL> IN (..)`` / ``<ID_COL> == n``      -> an expected set of entity rows
  * ``COUNT(*) <op> n`` / ``COUNT(<COL>) <op> n`` -> a cardinality expectation
  * ``CELL(0, 0) <op> v``                         -> a single scalar cell value
  * ``<COL> <op> v``                              -> a column value / bound
  * any of the above joined by ``AND`` / ``OR``

Operators arrive HTML-escaped in the database (``&gt;``, ``&#039;``); they are
unescaped here before parsing. This module is pure (no DB / network access): it
turns the raw string into clauses and a high-level summary. Row hydration (turning
entity ids into display rows) lives in the API layer, which holds the DB handle.
"""

import html
import re

# Assertion id-columns that denote a concrete entity kind. ``ID_ITEM`` carries
# Wikidata Q-ids (strings) resolved against T_WC_T2S_ITEM.ID_WIKIDATA; ``ID_CONTENT``
# is a movie+series union with no single table. Everything else is an int PK.
ID_COLUMN_ENTITY = {
    "ID_MOVIE": "movie",
    "ID_PERSON": "person",
    "ID_SERIE": "serie",
    "ID_TOPIC": "topic",
    "ID_COMPANY": "company",
    "ID_NETWORK": "network",
    "ID_T2S_LIST": "list",
    "ID_T2S_COLLECTION": "collection",
    "ID_ITEM": "location",
    "ID_CONTENT": "content",
    # Secondary entities: hydrate-able for the showcase (SAMPLE_HYDRATION in main.py).
    # Whether they actually get a showcase sample depends on their image coverage.
    "ID_MOVEMENT": "movement",
    "ID_AWARD": "award",
    "ID_NOMINATION": "nomination",
    "ID_GROUP": "group",
    "ID_DEATH": "death",
    "ID_TECHNICAL": "technical",
    # NB: genre has no standalone entity table (only T_WC_T2S_MOVIE/SERIE_GENRE
    # junctions), so it cannot be hydrated as a result entity.
}


def _coerce_value(token: str):
    """Return an int/float for a numeric token, else the unquoted string."""
    token = token.strip()
    if len(token) >= 2 and token[0] in "'\"" and token[-1] == token[0]:
        return token[1:-1]
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    return token


def _split_in_list(body: str):
    """Split the body of an ``IN (...)`` list into coerced values, order preserved."""
    values = []
    for raw in re.findall(r"'[^']*'|\"[^\"]*\"|[^,\s]+", body):
        values.append(_coerce_value(raw))
    return values


def _parse_clause(clause: str) -> dict:
    """Parse a single (already AND/OR-split) assertion clause into a typed dict."""
    clause = clause.strip()

    m = re.match(r"^([A-Z0-9_]+)\s+IN\s*\((.*)\)$", clause, re.S)
    if m:
        column = m.group(1)
        return {
            "type": "id_set",
            "column": column,
            "entity": ID_COLUMN_ENTITY.get(column),
            "ids": _split_in_list(m.group(2)),
        }

    m = re.match(r"^([A-Z0-9_]+)\s+NOT\s+IN\s*\((.*)\)$", clause, re.S)
    if m:
        column = m.group(1)
        return {
            "type": "id_exclusion",
            "column": column,
            "entity": ID_COLUMN_ENTITY.get(column),
            "ids": _split_in_list(m.group(2)),
        }

    m = re.match(r"^COUNT\(\s*(\*|[A-Z0-9_]+)\s*\)\s*(==|>=|<=|<>|!=|>|<)\s*(-?\d+)$", clause)
    if m:
        return {"type": "count", "arg": m.group(1), "op": m.group(2), "value": int(m.group(3))}

    m = re.match(r"^CELL\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*(==|>=|<=|<>|!=|>|<)\s*(.+)$", clause)
    if m:
        return {
            "type": "cell",
            "row": int(m.group(1)),
            "col": int(m.group(2)),
            "op": m.group(3),
            "value": _coerce_value(m.group(4)),
        }

    m = re.match(r"^([A-Z0-9_]+)\s*(==|>=|<=|<>|!=|>|<|LIKE)\s*(.+)$", clause, re.S)
    if m:
        column, op, value = m.group(1), m.group(2), _coerce_value(m.group(3))
        # `<ID_COL> == n` is just a one-element id set.
        if column in ID_COLUMN_ENTITY and op == "==" and not isinstance(value, str):
            return {"type": "id_set", "column": column, "entity": ID_COLUMN_ENTITY[column], "ids": [value]}
        return {"type": "scalar", "column": column, "op": op, "value": value}

    return {"type": "raw", "expr": clause}


def parse_assertion(raw):
    """Parse a raw ``ASSERTIONS_QUERY_RESULT`` string into ``{clauses, join}`` or None.

    ``join`` is the ordered list of ``AND`` / ``OR`` connectives between successive
    clauses (length ``len(clauses) - 1`` for a well-formed expression). Returns None
    for an empty / missing assertion.
    """
    if raw is None:
        return None
    text = html.unescape(str(raw)).strip()
    if not text:
        return None
    parts = re.split(r"\s+(AND|OR)\s+", text)
    clauses, join = [], []
    for part in parts:
        if part in ("AND", "OR"):
            join.append(part)
        else:
            stripped = part.strip()
            if stripped:
                clauses.append(_parse_clause(stripped))
    if not clauses:
        return None
    return {"clauses": clauses, "join": join}


def _first(parsed, clause_type):
    """Return the first clause of ``clause_type`` in ``parsed``, or None."""
    for clause in parsed["clauses"]:
        if clause["type"] == clause_type:
            return clause
    return None


def parse_failure(parsed, summary):
    """Return a short reason string when an assertion did not parse cleanly, else None.

    Flags the three ways the parser can fall short of fully understanding a non-empty
    assertion, so the caller can log it and surface DB/format drift:
      * the whole expression yielded no clauses (``parsed`` is None / empty);
      * a fragment fell through to the ``raw`` catch-all clause;
      * nothing classified, leaving ``result_kind == "unknown"``.
    Returns None when the assertion parsed into a recognized result kind.
    """
    if not parsed or not parsed.get("clauses"):
        return "no clauses parsed"
    raw_clauses = [c["expr"] for c in parsed["clauses"] if c["type"] == "raw"]
    if raw_clauses:
        return "unrecognized fragment(s): " + " | ".join(raw_clauses)
    if summary and summary.get("result_kind") == "unknown":
        return "unclassified (result_kind=unknown)"
    return None


def summarize(parsed, raw):
    """Build the high-level ``assertion`` summary block exposed by /samples.

    Returns a dict with ``raw`` plus a ``result_kind`` of:
      * ``entity_rows`` - an id_set clause is present (rows are hydratable)
      * ``scalar``      - a known literal value (``COL == v`` or ``CELL(0,0) == v``)
      * ``count``       - only a COUNT cardinality expectation
      * ``bound``       - only an inequality/bound (no exact value)
      * ``unknown``     - none of the above (unparsed / raw)
    ``entity_type``, ``expected_count`` and ``count_operator`` are filled when known.
    """
    if not parsed:
        return None

    id_clause = _first(parsed, "id_set")
    count_clause = _first(parsed, "count")
    summary = {"raw": html.unescape(str(raw)).strip()}

    if id_clause:
        summary["result_kind"] = "entity_rows"
        summary["entity_type"] = id_clause["entity"]
        if count_clause is not None:
            summary["expected_count"] = count_clause["value"]
            summary["count_operator"] = count_clause["op"]
        else:
            summary["expected_count"] = len(id_clause["ids"])
        return summary

    # A known literal value: `COL == 'X'` / `COL == 5` / `CELL(0,0) == 40`.
    literal = next(
        (c for c in parsed["clauses"] if c["type"] in ("scalar", "cell") and c["op"] == "=="),
        None,
    )
    if literal is not None:
        summary["result_kind"] = "scalar"
        if count_clause is not None:
            summary["expected_count"] = count_clause["value"]
            summary["count_operator"] = count_clause["op"]
        return summary

    # A pure exclusion (`<ID_COL> NOT IN (..)`) or an inequality is a constraint
    # with no concrete positive content to materialize.
    if any(c["type"] in ("scalar", "cell", "id_exclusion") for c in parsed["clauses"]):
        summary["result_kind"] = "bound"
        if count_clause is not None:
            summary["expected_count"] = count_clause["value"]
            summary["count_operator"] = count_clause["op"]
        return summary

    if count_clause is not None:
        summary["result_kind"] = "count"
        summary["expected_count"] = count_clause["value"]
        summary["count_operator"] = count_clause["op"]
        return summary

    summary["result_kind"] = "unknown"
    return summary
