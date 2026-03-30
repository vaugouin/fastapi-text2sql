import re
from typing import Any, Optional


SELECT_CACHE_QUERY = """
SELECT QUESTION, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION,
       ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME,
       TOTAL_PROCESSING_TIME, QUESTION_HASHED, IS_ANONYMIZED
FROM T_WC_T2S_CACHE
WHERE {where_clause}
AND API_VERSION = %s
AND (DELETED IS NULL OR DELETED = 0)
ORDER BY TIM_UPDATED DESC
LIMIT 1
"""

INSERT_CACHE_QUERY = """
INSERT INTO T_WC_T2S_CACHE
(QUESTION, QUESTION_HASHED, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION, API_VERSION,
ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME, TOTAL_PROCESSING_TIME,
DELETED, DAT_CREAT, TIM_UPDATED, IS_ANONYMIZED)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), NOW(), %s)
"""


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
            "entity_extraction_processing_time": 0.0,
            "text2sql_processing_time": 0.0,
            "embeddings_time": 0.0,
            "query_time": 0.0,
            "total_processing_time": 0.0,
            "is_anonymized": False,
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
        "entity_extraction_processing_time": row.get("ENTITY_EXTRACTION_PROCESSING_TIME") or 0.0,
        "text2sql_processing_time": row.get("TEXT2SQL_PROCESSING_TIME") or 0.0,
        "embeddings_time": row.get("EMBEDDINGS_TIME") or 0.0,
        "query_time": row.get("QUERY_TIME") or 0.0,
        "total_processing_time": row.get("TOTAL_PROCESSING_TIME") or 0.0,
        "is_anonymized": bool(row.get("IS_ANONYMIZED") or 0),
        "used_raw_query_to_preserve_limit": used_raw_query_to_preserve_limit,
        "row": row,
    }


def _fetch_latest_cache_entry(connection, *, where_clause: str, where_params: tuple[Any, ...], api_version: str) -> dict[str, Any]:
    """Fetch the most recent non-deleted cache entry matching the supplied condition."""
    query = SELECT_CACHE_QUERY.format(where_clause=where_clause)
    with connection.cursor() as cursor:
        cursor.execute(query, (*where_params, api_version))
        row = cursor.fetchone()
    return _normalize_cache_row(row)


def search_sql_cache_by_question_hash(connection, question_hash: str, api_version: str) -> dict[str, Any]:
    """Look up the latest cache entry by hashed original question text."""
    return _fetch_latest_cache_entry(
        connection,
        where_clause="QUESTION_HASHED = %s",
        where_params=(question_hash,),
        api_version=api_version,
    )


def search_sql_cache_by_question_text(connection, question_text: str, api_version: str) -> dict[str, Any]:
    """Look up the latest cache entry by exact stored question text."""
    return _fetch_latest_cache_entry(
        connection,
        where_clause="QUESTION = %s",
        where_params=(question_text,),
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
    api_version: str,
    entity_extraction_processing_time: float,
    text2sql_processing_time: float,
    embeddings_time: float,
    query_time: float,
    total_processing_time: float,
    is_anonymized: bool,
    deleted: int = 0,
) -> dict[str, Any]:
    """Insert a cache entry into ``T_WC_T2S_CACHE`` and return a summary payload."""
    with connection.cursor() as cursor:
        cursor.execute(
            INSERT_CACHE_QUERY,
            (
                question,
                question_hashed,
                sql_query,
                sql_processed,
                justification,
                api_version,
                entity_extraction_processing_time,
                text2sql_processing_time,
                embeddings_time,
                query_time,
                total_processing_time,
                deleted,
                1 if is_anonymized else 0,
            ),
        )
    connection.commit()
    return {
        "written": True,
        "question": question,
        "question_hashed": question_hashed,
        "is_anonymized": bool(is_anonymized),
        "sql_query": sql_query,
        "sql_processed": sql_processed,
        "justification": justification,
    }
