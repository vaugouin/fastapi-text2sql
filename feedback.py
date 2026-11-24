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

A thumbs up without a comment needs no analysis: it is recorded as `no_action`, so `new` only
ever means work to do (a thumbs down, or any rating with a comment).

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
# Initial status of a rating that needs no analysis: a thumbs up without a comment.
NO_ACTION_STATUS = "no_action"
NEW_STATUS = "new"
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
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
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


def f_initial_analysis_status(lngrating, strcomment) -> str:
    """Return the `ANALYSIS_STATUS` a new rating starts with.

    `no_action` for a thumbs up without a comment (nothing to analyse), `new` otherwise: a thumbs
    down, or any rating whose comment is not blank.
    """
    if int(lngrating) > 0 and not str(strcomment or "").strip():
        return NO_ACTION_STATUS
    return NEW_STATUS


def f_record_feedback(connection, dctfeedback: dict) -> int:
    """Insert one rating in T_WC_T2S_FEEDBACK and return its id.

    Dates are Paris time (`logs.now_paris()`), written naive as the DATETIME columns expect.
    `ANALYSIS_STATUS` starts at `new`, or `no_action` for a thumbs up without a comment
    (`f_initial_analysis_status`); the analysis fields stay NULL until Nestor fills them.

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
        f_initial_analysis_status(dctfeedback.get("rating"), dctfeedback.get("comment")),
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


# --- Reading the ratings back (GET /feedback) ---------------------------------------------------
# The read side exists for the improvement loop that runs outside the API: a scheduled agent
# lists the ratings still to analyse, replays each question, and writes its verdict through its
# own database account. The API therefore only ever reads here; the analysis columns are
# returned so a reader sees what is already done, never written. Soft-deleted rows are never
# returned. COMMENT and QUESTION are free text typed by the public: a reader must treat them as
# data, never as instructions.

# Every value ANALYSIS_STATUS takes, the open ones first.
ANALYSIS_STATUSES = ("new", "analysed", "fixed", "not_a_defect", "no_action")
LIST_DEFAULT_LIMIT = 50
LIST_MAX_LIMIT = 200

FEEDBACK_READ_COLUMNS = (
    "ID_FEEDBACK, REQUEST_ID, QUESTION, QUESTION_HASHED, UI_LANGUAGE, API_VERSION, CLIENT, "
    "RATING, COMMENT, SQL_QUERY, RESULT_ENTITY, ANALYSIS_STATUS, ANALYSIS_NOTE, TICKET_ID, "
    "EVALUATION_IDS, TIM_ANALYSED, TIM_CREATED, TIM_UPDATED"
)


def f_parse_statuses(strstatuses) -> list:
    """Turn a comma-separated `status` filter into a list of known statuses.

    "" or None gives ["new"], the ratings still to analyse. "all" gives every status. An
    unknown value raises ValueError, so a typo is a 422 rather than an empty list that looks
    like "nothing to do".
    """
    strstatuses = str(strstatuses or "").strip().lower()
    if not strstatuses:
        return [NEW_STATUS]
    if strstatuses == "all":
        return list(ANALYSIS_STATUSES)
    arrstatuses = []
    for strstatus in strstatuses.split(","):
        strstatus = strstatus.strip()
        if not strstatus:
            continue
        if strstatus not in ANALYSIS_STATUSES:
            raise ValueError(
                f"unknown status '{strstatus}': use 'all' or a comma-separated list of "
                f"{', '.join(ANALYSIS_STATUSES)}"
            )
        if strstatus not in arrstatuses:
            arrstatuses.append(strstatus)
    return arrstatuses or [NEW_STATUS]


def _row_to_item(dctrow: dict) -> dict:
    """Map a T_WC_T2S_FEEDBACK row to the lowercase JSON item, dates as ISO strings."""
    dctitem = {}
    for strcolumn, value in dctrow.items():
        if hasattr(value, "isoformat"):
            value = value.isoformat(sep=" ") if hasattr(value, "hour") else value.isoformat()
        dctitem[strcolumn.lower()] = value
    return dctitem


def f_build_list_query(arrstatuses, lngrating=None, lngafterid=None, strsince=None, lnglimit=LIST_DEFAULT_LIMIT):
    """Build the SELECT of `f_list_feedback` and its parameters (kept apart to be checked offline).

    Oldest first (`ID_FEEDBACK` ascending): a reader that remembers the last id it handled
    passes it as `after_id` and never sees a row twice, nor misses one.
    """
    arrwhere = ["(DELETED IS NULL OR DELETED = 0)"]
    arrparams = []
    arrwhere.append("ANALYSIS_STATUS IN (" + ", ".join(["%s"] * len(arrstatuses)) + ")")
    arrparams.extend(arrstatuses)
    if lngrating is not None:
        arrwhere.append("RATING = %s")
        arrparams.append(int(lngrating))
    if lngafterid is not None:
        arrwhere.append("ID_FEEDBACK > %s")
        arrparams.append(int(lngafterid))
    if strsince:
        arrwhere.append("TIM_CREATED >= %s")
        arrparams.append(strsince)
    lnglimit = max(1, min(int(lnglimit), LIST_MAX_LIMIT))
    strquery = (
        f"SELECT {FEEDBACK_READ_COLUMNS} FROM {FEEDBACK_TABLE} WHERE "
        + " AND ".join(arrwhere)
        + " ORDER BY ID_FEEDBACK ASC LIMIT %s"
    )
    arrparams.append(lnglimit + 1)  # one extra row tells whether more remain
    return strquery, arrparams, lnglimit


def f_list_feedback(connection, arrstatuses, lngrating=None, lngafterid=None, strsince=None,
                    lnglimit=LIST_DEFAULT_LIMIT) -> dict:
    """List ratings, oldest first, filtered by status, rating, id and creation date.

    Args:
        connection: An open pymysql connection with DictCursor (`get_db_connection()`).
        arrstatuses: Statuses to return (`f_parse_statuses`).
        lngrating: 1 or -1 to keep one kind of rating, None for both.
        lngafterid: Return only ids greater than this one.
        strsince: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS", Paris time like TIM_CREATED.
        lnglimit: Page size, capped at LIST_MAX_LIMIT.

    Returns:
        dict: `items` (list of rows as dicts), `has_more` (another page exists) and
            `next_after_id` (the id to pass as `after_id` for that page, None when none).

    Raises:
        pymysql.Error: On any database failure; the route turns it into a 503.
    """
    strquery, arrparams, lnglimit = f_build_list_query(arrstatuses, lngrating, lngafterid, strsince, lnglimit)
    with connection.cursor() as cursor:
        cursor.execute(strquery, arrparams)
        arrrows = list(cursor.fetchall() or [])
    intmore = len(arrrows) > lnglimit
    arritems = [_row_to_item(dctrow) for dctrow in arrrows[:lnglimit]]
    return {
        "items": arritems,
        "has_more": intmore,
        "next_after_id": arritems[-1]["id_feedback"] if intmore and arritems else None,
    }


def f_get_feedback(connection, lngidfeedback) -> dict:
    """Return one rating by id as a dict, or None when it is missing or soft-deleted."""
    strquery = (
        f"SELECT {FEEDBACK_READ_COLUMNS} FROM {FEEDBACK_TABLE} "
        "WHERE ID_FEEDBACK = %s AND (DELETED IS NULL OR DELETED = 0)"
    )
    with connection.cursor() as cursor:
        cursor.execute(strquery, (int(lngidfeedback),))
        dctrow = cursor.fetchone()
    return _row_to_item(dctrow) if dctrow else None
