"""Authorize model-generated MariaDB queries before they reach a cursor.

The model, cache, and entity-rescue paths all use the same execution helper in
main.py. This module is deliberately independent of the API and database.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.tokens import Tokenizer


class GeneratedSqlRejected(ValueError):
    """A safe reason code for a rejected generated query; never contains SQL."""


# Explicit inventory from data/text_to_sql.md. Do not admit tables by prefix:
# cache and feedback tables share T_WC_T2S_ and the API account can write them.
_READ_MODEL_SUFFIXES = """
AWARD COLLECTION COMPANY COMPANY_IMAGE DEATH EPISODE EPISODE_LOCATION
GENRE GROUP GROUP_MOVIE GROUP_SERIE LIST LOCATION LOCATION_ANCESTOR
MOVEMENT MOVIE MOVIE_AWARD MOVIE_COLLECTION MOVIE_COMPANY MOVIE_GENRE
MOVIE_IMAGE MOVIE_LIST MOVIE_LOCATION MOVIE_MOVEMENT MOVIE_NOMINATION
MOVIE_PRODUCTION_COUNTRY MOVIE_RECOMMENDATION MOVIE_SIMILAR
MOVIE_SOURCE_WORK MOVIE_SPOKEN_LANGUAGE MOVIE_TECHNICAL MOVIE_TOPIC
MOVIE_VIDEO NETWORK NETWORK_IMAGE NOMINATION PERSON PERSON_AWARD
PERSON_DEATH PERSON_GROUP PERSON_IMAGE PERSON_MOVIE PERSON_NOMINATION
PERSON_SERIE SERIE SERIE_AWARD SERIE_COLLECTION SERIE_COMPANY SERIE_GENRE
SERIE_IMAGE SERIE_LIST SERIE_LOCATION SERIE_MOVEMENT SERIE_NETWORK
SERIE_NOMINATION SERIE_PRODUCTION_COUNTRY SERIE_RECOMMENDATION
SERIE_SIMILAR SERIE_SOURCE_WORK SERIE_SPOKEN_LANGUAGE SERIE_TOPIC
SERIE_VIDEO SOURCE_WORK TECHNICAL TOPIC
"""
READ_MODEL_TABLES = frozenset(f"T_WC_T2S_{name}" for name in _READ_MODEL_SUFFIXES.split())

# Built-in, side-effect-free functions needed for aggregations, formatting and
# date arithmetic. Unknown functions (including stored functions and UDFs) fail
# closed. Extend this set from a reviewed production query, not a model request.
SAFE_FUNCTIONS = frozenset("""
ABS AND AVG CASE CAST CEIL CEILING CHAR_LENGTH COALESCE CONCAT CONCAT_WS
COUNT CURDATE CURRENT_DATE DATE DATE_ADD DATE_FORMAT DATE_SUB DATEDIFF DAY
DAYOFMONTH EXISTS FLOOR GREATEST GROUP_CONCAT IF IFNULL LCASE LEAST LEFT
LENGTH LOWER LPAD LTRIM MAX MIN MOD MONTH NULLIF OR PAD RAND ROUND RPAD
RTRIM RIGHT STR_POSITION STR_TO_DATE SUBSTR SUBSTRING SUM TIME_TO_STR
TIMESTAMPDIFF TRIM TS_OR_DS_TO_DATE TS_OR_DS_TO_TIMESTAMP UCASE UPPER YEAR
""".split())

_FORBIDDEN_NODES = (
    exp.Command, exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop,
    exp.Alter, exp.Merge, exp.Into, exp.Lock, exp.Parameter,
    exp.SessionParameter,
)


def validate_generated_sql(sql_text: str) -> None:
    """Raise GeneratedSqlRejected unless SQL is one allowed read query.

    The original SQL is executed after validation. We never execute a rendered
    AST, because rendering could silently remove unsupported MariaDB syntax.
    """
    if not isinstance(sql_text, str) or not sql_text.strip():
        raise GeneratedSqlRejected("empty_sql")
    try:
        # MariaDB executes versioned /*!...*/ comments. SQLGlot treats them
        # as comments, so inspecting only its AST would miss executable SQL.
        tokens = Tokenizer().tokenize(sql_text)
        if any(token.comments for token in tokens):
            raise GeneratedSqlRejected("sql_comment")
        if not tokens or tokens[0].text.upper() not in {"SELECT", "WITH", "("}:
            raise GeneratedSqlRejected("not_one_select")
        statements = sqlglot.parse(sql_text, read="mysql", error_level="RAISE")
    except GeneratedSqlRejected:
        raise
    except (ParseError, TokenError, ValueError) as exc:
        raise GeneratedSqlRejected("invalid_sql") from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        raise GeneratedSqlRejected("not_one_select")

    statement = statements[0]
    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise GeneratedSqlRejected("prohibited_construct")
        if isinstance(node, exp.Func) and node.sql_name().upper() not in SAFE_FUNCTIONS:
            raise GeneratedSqlRejected("prohibited_function")
        if isinstance(node, exp.Table) and (node.db or node.catalog):
            raise GeneratedSqlRejected("qualified_table")

    try:
        for scope in traverse_scope(statement):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table) and source.name.upper() not in READ_MODEL_TABLES | {"DUAL"}:
                    raise GeneratedSqlRejected("table_not_allowed")
    except GeneratedSqlRejected:
        raise
    except Exception as exc:
        raise GeneratedSqlRejected("unresolved_source") from exc
