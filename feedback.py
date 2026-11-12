"""User feedback on a search answer, and the cache bypass it opens (FASTAPI-TEXT2SQL-061).

A user rates an answer of `POST /search/text2sql` from t2s-front or voice-agent: thumbs up (+1)
or thumbs down (-1), with an optional comment. `POST /feedback` stores one row per rating in
`T_WC_T2S_FEEDBACK` (DDL: `doc/sql/T_WC_T2S_FEEDBACK.sql`), where Nestor analyses it later
(TEXT2SQL-EVAL-006: the analysis fields `ANALYSIS_STATUS`, `ANALYSIS_NOTE`, `TICKET_ID`,
`EVALUATION_IDS`, `TIM_ANALYSED`).

**The cache rows are never touched.** A thumbs down does not delete, flag or rewrite any row
of `T_WC_T2S_CACHE`: the row is the evidence (question, SQL, answer), and the anonymized row
carries the hash of the ORIGINAL question, so flagging rows by hash would also poison a
template other questions reuse. Instead the search route asks this module, before its cache
tiers, whether the question has an OPEN negative rating (`f_has_open_negative_feedback`). When
it has, the request skips every cache lookup (exact, anonymized, ChromaDB embeddings) and every
cache write (exact, anonymized, ChromaDB), so the answer is computed fresh each time and the
evidence rows stay the latest ones. The bypass closes by itself when the analysis sets
`ANALYSIS_STATUS` to `fixed` or `not_a_defect` (or soft-deletes the rating).

The module also owns the request id: a uuid4 hex generated when the outer search pass starts,
echoed as `request_id` in the response and the JSON journal, and sent back by the client with
its rating so the analysis finds the journal of that very request. Both values live in
ContextVars, with the lifecycle of the other per-request buffers (text2sql.py): set by the outer
pass, inherited by the complex-question retry, which re-enters the endpoint in the same context.
"""

import contextvars
import hashlib
import uuid

import logs

FEEDBACK_TABLE = "T_WC_T2S_FEEDBACK"
FEEDBACK_CLIENTS = ("t2s-front", "voice-agent", "other")
# A rating keeps the cache bypassed while its analysis is in one of these states. `fixed` and
# `not_a_defect` close it; nothing else does, so a new status added later is closed by default.
OPEN_ANALYSIS_STATUSES = ("new", "analysed")
MAX_COMMENT_CHARS = 2000
MAX_QUESTION_CHARS = 4000
MAX_REQUEST_ID_CHARS = 64
MAX_API_VERSION_CHARS = 20
MAX_RESULT_ENTITY_CHARS = 50

_request_id: "contextvars.ContextVar" = contextvars.ContextVar("feedback_request_id", default="")
_cache_bypass: "contextvars.ContextVar" = contextvars.ContextVar("feedback_cache_bypass", default=False)
# Error codes already reported on the console by the bypass check, so a missing table (1146)
# or a missing grant (1142) is said once per process, not on every search.
_reported_errors = set()

OPEN_NEGATIVE_FEEDBACK_QUERY = """
SELECT 1 FROM T_WC_T2S_FEEDBACK
WHERE QUESTION_HASHED IN ({placeholders})
  AND RATING < 0
  AND ANALYSIS_STATUS IN ('new', 'analysed')
  AND (DELETED IS NULL OR DELETED = 0)
  {language_clause}
LIMIT 1
"""

INSERT_FEEDBACK_QUERY = """
INSERT INTO T_WC_T2S_FEEDBACK
(REQUEST_ID, QUESTION, QUESTION_HASHED, UI_LANGUAGE, API_VERSION, CLIENT, RATING, COMMENT,
 SQL_QUERY, RESULT_ENTITY, ANALYSIS_STATUS, DELETED, DAT_CREAT, TIM_CREATED, TIM_UPDATED)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new', 0, %s, %s, %s)
"""


def f_start_request() -> str:
    """Open a new search request: fresh request id, cache bypass reset.

    Called by the outer pass of `/search/text2sql` only; the complex-question retry inherits
    both values.

    Returns:
        str: The new request id, a uuid4 hex string (32 characters).
    """
    strrequestid = uuid.uuid4().hex
    _request_id.set(strrequestid)
    _cache_bypass.set(False)
    return strrequestid


def current_request_id() -> str:
    """Return the request id of the current search request, "" outside one."""
    return _request_id.get()


def set_cache_bypass(intbypass: bool) -> None:
    """Record that the current request runs without the cache because of open feedback."""
    _cache_bypass.set(bool(intbypass))


def cache_bypass_active() -> bool:
    """Return True when the current request (or the outer pass it retries) bypasses the cache."""
    return bool(_cache_bypass.get())


def f_normalize_question(strquestion) -> str:
    """Normalize a question exactly as `/search/text2sql` does before hashing it.

    Mirror of the normalization block at the top of `search_text2sql` in main.py (strip, double
    spaces, `&#039;` and the typographic apostrophe). Keep the two in step: the hash computed
    here must equal the `question_hashed` the search route returned for the same wording.

    Args:
        strquestion: The question as the client holds it.

    Returns:
        str: The normalized question ("" for None).
    """
    strnormalized = str(strquestion or "").strip()
    strnormalized = strnormalized.replace('  ', ' ')
    strnormalized = strnormalized.replace('&#039;', "'").replace('’', "'")
    return strnormalized


def f_question_hash(strquestion) -> str:
    """Return the SHA-256 hex digest of the normalized question, as the search route computes it."""
    return hashlib.sha256(f_normalize_question(strquestion).encode('utf-8')).hexdigest()


def _error_code(exc: Exception):
    """Return the MariaDB error number of a pymysql exception, or None."""
    try:
        if exc.args and isinstance(exc.args[0], int):
            return exc.args[0]
    except Exception:
        pass
    return None


def f_has_open_negative_feedback(cursor_or_conn, arrquestionhashes, strlanguage=None) -> bool:
    """Tell whether a question carries an open thumbs down, so the cache must be bypassed.

    Open means `RATING < 0`, `ANALYSIS_STATUS` in `new` / `analysed` and not soft-deleted. The
    language filter follows the cache's own scoping (`UI_LANGUAGE = %s OR UI_LANGUAGE IS NULL`):
    a cache row is served per language, and so is the answer text a user rated.

    Never raises: a missing table (error 1146, the DDL not yet run), a missing grant (1142) or
    any other failure returns False, so the search carries on with its normal cache behaviour.
    Each error code is printed once per process.

    Args:
        cursor_or_conn: An open pymysql cursor, or a connection (a cursor is then opened and
            closed here).
        arrquestionhashes: The hashes to test (the question's own SHA-256 and, when the client
            sent one, its `question_hashed`). Empty values are ignored.
        strlanguage: The request's UI language, or None to test every language.

    Returns:
        bool: True when at least one open negative rating matches.
    """
    arrhashes = []
    for strhash in arrquestionhashes or ():
        strhash = str(strhash or "").strip()
        if strhash and strhash not in arrhashes:
            arrhashes.append(strhash)
    if not arrhashes or cursor_or_conn is None:
        return False

    strlanguageclause = ""
    arrparams = list(arrhashes)
    if strlanguage:
        strlanguageclause = "AND (UI_LANGUAGE = %s OR UI_LANGUAGE IS NULL)"
        arrparams.append(strlanguage)
    strquery = OPEN_NEGATIVE_FEEDBACK_QUERY.format(
        placeholders=", ".join(["%s"] * len(arrhashes)),
        language_clause=strlanguageclause,
    )

    intownedcursor = not hasattr(cursor_or_conn, "execute")
    cursor = None
    try:
        cursor = cursor_or_conn.cursor() if intownedcursor else cursor_or_conn
        cursor.execute(strquery, arrparams)
        return cursor.fetchone() is not None
    except Exception as exc:
        lngcode = _error_code(exc)
        if lngcode not in _reported_errors:
            _reported_errors.add(lngcode)
            print(
                f"[feedback] open-feedback check on {FEEDBACK_TABLE} failed, cache used as usual "
                f"(error 1146: table missing, run doc/sql/T_WC_T2S_FEEDBACK.sql; error 1142: grant "
                f"missing for the API account). Reported once per process: {exc}",
                flush=True,
            )
        return False
    finally:
        if intownedcursor and cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass


def f_record_feedback(connection, dctfeedback: dict) -> int:
    """Insert one rating in T_WC_T2S_FEEDBACK and return its id.

    Dates are Paris time (`logs.now_paris()`), written naive as the DATETIME columns expect.
    `ANALYSIS_STATUS` starts at `new`; the analysis fields stay NULL until Nestor fills them.

    Args:
        connection: An open pymysql connection (autocommit, as `get_db_connection()` returns).
        dctfeedback: The validated request: request_id, question, question_hashed, ui_language,
            api_version, client, rating, comment, sql_query, result_entity.

    Returns:
        int: The new `ID_FEEDBACK`.

    Raises:
        pymysql.Error: On any database failure; the route turns it into a 503.
    """
    dtnow = logs.now_paris()
    strtimestamp = dtnow.strftime("%Y-%m-%d %H:%M:%S")
    strdate = dtnow.strftime("%Y-%m-%d")
    arrparams = (
        dctfeedback.get("request_id"),
        dctfeedback.get("question"),
        dctfeedback.get("question_hashed"),
        dctfeedback.get("ui_language"),
        dctfeedback.get("api_version"),
        dctfeedback.get("client"),
        int(dctfeedback.get("rating")),
        dctfeedback.get("comment"),
        dctfeedback.get("sql_query"),
        dctfeedback.get("result_entity"),
        strdate,
        strtimestamp,
        strtimestamp,
    )
    with connection.cursor() as cursor:
        cursor.execute(INSERT_FEEDBACK_QUERY, arrparams)
        lngid = cursor.lastrowid
    try:
        connection.commit()  # no-op under autocommit, required without it
    except Exception:
        pass
    return int(lngid)
