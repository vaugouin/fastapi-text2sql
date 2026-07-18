import re
from typing import Any, Optional


# RESULT_ENTITY (the answer entity type the cached SQL projects, e.g. "movie"/"person")
# is stored and returned when the column exists on T_WC_T2S_CACHE. The module degrades
# gracefully when the column is absent (e.g. before the ALTER TABLE migration runs): on the
# first "Unknown column" error this flag flips to False and all subsequent reads/writes use
# the legacy column set, treating result_entity as empty. So a not-yet-migrated DB never
# breaks cache reads/writes — it just doesn't persist result_entity until the column exists.
_RESULT_ENTITY_COLUMN_AVAILABLE = True

_SELECT_CACHE_COLUMNS = """QUESTION, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION, ANSWER,
       ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME,
       TOTAL_PROCESSING_TIME, QUESTION_HASHED, IS_ANONYMIZED"""

SELECT_CACHE_QUERY = """
SELECT {columns}
FROM T_WC_T2S_CACHE
WHERE {where_clause}
AND API_VERSION = %s
AND (DELETED IS NULL OR DELETED = 0)
ORDER BY TIM_UPDATED DESC
LIMIT 1
"""

INSERT_CACHE_QUERY = """
INSERT INTO T_WC_T2S_CACHE
(QUESTION, QUESTION_HASHED, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION, ANSWER, API_VERSION,
ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME, TOTAL_PROCESSING_TIME,
DELETED, DAT_CREAT, TIM_UPDATED, IS_ANONYMIZED, UI_LANGUAGE{result_entity_col})
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), NOW(), %s, %s{result_entity_val})
"""


def _is_unknown_column_error(exc: Exception) -> bool:
    """Detect a MariaDB/MySQL "Unknown column" (error 1054) failure."""
    msg = str(exc).lower()
    return "1054" in msg or "unknown column" in msg


def _normalize_cache_row(row: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Normalize a raw SQL cache row into the API-facing cache payload shape."""
    if not row:
        return {
            "found": False,
            "question": None,
            "question_hashed": None,
            "sql_query": "",
            "sql_query_raw": "",
            "sql_query_processed": "",
            "justification": "",
            "answer": "",
            "entity_extraction_processing_time": 0.0,
            "text2sql_processing_time": 0.0,
            "embeddings_time": 0.0,
            "query_time": 0.0,
            "total_processing_time": 0.0,
            "is_anonymized": False,
            "result_entity": "",
            "used_raw_query_to_preserve_limit": False,
            "row": None,
        }

    sql_query_raw = row.get("SQL_QUERY") or ""
    sql_query_processed = row.get("SQL_PROCESSED") or ""
    sql_query = sql_query_processed or sql_query_raw
    used_raw_query_to_preserve_limit = False

    if sql_query_processed and sql_query_raw and "{{" not in sql_query_raw:
        match_raw_limit = re.search(r"\blimit\b\s+(\d+)", sql_query_raw, re.IGNORECASE)
        match_processed_limit = re.search(r"\blimit\b\s+(\d+)", sql_query_processed, re.IGNORECASE)
        if match_raw_limit and match_processed_limit:
            raw_limit = int(match_raw_limit.group(1))
            processed_limit = int(match_processed_limit.group(1))
            if raw_limit < processed_limit:
                sql_query = sql_query_raw
                used_raw_query_to_preserve_limit = True

    return {
        "found": True,
        "question": row.get("QUESTION"),
        "question_hashed": row.get("QUESTION_HASHED"),
        "sql_query": sql_query,
        "sql_query_raw": sql_query_raw,
        "sql_query_processed": sql_query_processed,
        "justification": row.get("JUSTIFICATION") or "",
        "answer": row.get("ANSWER") or "",
        "entity_extraction_processing_time": row.get("ENTITY_EXTRACTION_PROCESSING_TIME") or 0.0,
        "text2sql_processing_time": row.get("TEXT2SQL_PROCESSING_TIME") or 0.0,
        "embeddings_time": row.get("EMBEDDINGS_TIME") or 0.0,
        "query_time": row.get("QUERY_TIME") or 0.0,
        "total_processing_time": row.get("TOTAL_PROCESSING_TIME") or 0.0,
        "is_anonymized": bool(row.get("IS_ANONYMIZED") or 0),
        "result_entity": row.get("RESULT_ENTITY") or "",
        "used_raw_query_to_preserve_limit": used_raw_query_to_preserve_limit,
        "row": row,
    }


def _fetch_latest_cache_entry(connection, *, where_clause: str, where_params: tuple[Any, ...], api_version: str) -> dict[str, Any]:
    """Fetch the most recent non-deleted cache entry matching the supplied condition.

    Includes RESULT_ENTITY when the column is available, falling back transparently to the
    legacy column set when it is not (see ``_RESULT_ENTITY_COLUMN_AVAILABLE``).
    """
    global _RESULT_ENTITY_COLUMN_AVAILABLE
    params = (*where_params, api_version)
    if _RESULT_ENTITY_COLUMN_AVAILABLE:
        columns = _SELECT_CACHE_COLUMNS + ", RESULT_ENTITY"
        query = SELECT_CACHE_QUERY.format(columns=columns, where_clause=where_clause)
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
            return _normalize_cache_row(row)
        except Exception as exc:
            if not _is_unknown_column_error(exc):
                raise
            _RESULT_ENTITY_COLUMN_AVAILABLE = False  # column not migrated yet; degrade once

    query = SELECT_CACHE_QUERY.format(columns=_SELECT_CACHE_COLUMNS, where_clause=where_clause)
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
    return _normalize_cache_row(row)


def search_sql_cache_by_question_hash(connection, question_hash: str, api_version: str, ui_language: str = "en") -> dict[str, Any]:
    """Look up the latest cache entry by hashed original question text."""
    return _fetch_latest_cache_entry(
        connection,
        # FASTAPI-TEXT2SQL-163: a cache hit is served only for the SAME ui_language. The old
        # `OR UI_LANGUAGE IS NULL` let a language-less legacy row match any language (a
        # cross-language leak); verified in DB that 0 rows have UI_LANGUAGE IS NULL, so the
        # clause was dead and is removed before multilingual serving makes the leak real.
        where_clause="QUESTION_HASHED = %s AND UI_LANGUAGE = %s",
        where_params=(question_hash, ui_language),
        api_version=api_version,
    )


def search_sql_cache_by_question_text(connection, question_text: str, api_version: str, ui_language: str = "en") -> dict[str, Any]:
    """Look up the latest cache entry by exact stored question text."""
    return _fetch_latest_cache_entry(
        connection,
        # FASTAPI-TEXT2SQL-163: same-ui_language-only (see the hash lookup above).
        where_clause="QUESTION = %s AND UI_LANGUAGE = %s",
        where_params=(question_text, ui_language),
        api_version=api_version,
    )


def write_sql_cache_entry(
    connection,
    *,
    question: str,
    question_hashed: str,
    sql_query: str,
    sql_processed: str,
    justification: str,
    answer: str = "",
    api_version: str,
    entity_extraction_processing_time: float,
    text2sql_processing_time: float,
    embeddings_time: float,
    query_time: float,
    total_processing_time: float,
    is_anonymized: bool,
    deleted: int = 0,
    ui_language: str = "en",
    result_entity: str = "",
) -> dict[str, Any]:
    """Insert a cache entry into ``T_WC_T2S_CACHE`` and return a summary payload.

    Persists RESULT_ENTITY when the column is available, falling back transparently to the
    legacy column set when it is not (see ``_RESULT_ENTITY_COLUMN_AVAILABLE``).
    """
    global _RESULT_ENTITY_COLUMN_AVAILABLE
    base_values = (
        question,
        question_hashed,
        sql_query,
        sql_processed,
        justification,
        answer,
        api_version,
        entity_extraction_processing_time,
        text2sql_processing_time,
        embeddings_time,
        query_time,
        total_processing_time,
        deleted,
        1 if is_anonymized else 0,
        ui_language,
    )

    if _RESULT_ENTITY_COLUMN_AVAILABLE:
        query = INSERT_CACHE_QUERY.format(result_entity_col=", RESULT_ENTITY", result_entity_val=", %s")
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, (*base_values, result_entity or ""))
            connection.commit()
            return _write_summary(question, question_hashed, is_anonymized, sql_query, sql_processed, justification, answer, result_entity)
        except Exception as exc:
            if not _is_unknown_column_error(exc):
                raise
            _RESULT_ENTITY_COLUMN_AVAILABLE = False  # column not migrated yet; degrade once
            try:
                connection.rollback()
            except Exception:
                pass

    query = INSERT_CACHE_QUERY.format(result_entity_col="", result_entity_val="")
    with connection.cursor() as cursor:
        cursor.execute(query, base_values)
    connection.commit()
    return _write_summary(question, question_hashed, is_anonymized, sql_query, sql_processed, justification, answer, result_entity)


def _write_summary(question, question_hashed, is_anonymized, sql_query, sql_processed, justification, answer, result_entity):
    """Build the summary payload returned by ``write_sql_cache_entry``."""
    return {
        "written": True,
        "question": question,
        "question_hashed": question_hashed,
        "is_anonymized": bool(is_anonymized),
        "sql_query": sql_query,
        "sql_processed": sql_processed,
        "justification": justification,
        "answer": answer,
        "result_entity": result_entity or "",
    }
