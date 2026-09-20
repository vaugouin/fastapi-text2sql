"""Recognition cache for the vision path (FASTAPI-TEXT2SQL-114, point 9).

The three existing cache tiers all key on the QUESTION (exact text, anonymized pattern, or
its embedding). None of them indexes bytes, so without this module the image path caches the
cheap half of the work and repays the expensive one: the same photo re-deposited would cost
another ~4 cents of vision model, whether the question was the same or not.

**The key already exists and costs nothing.** `uploads.f_getuploadfilename` hashes the RAW
BYTES into the deposit filename, so the same photo sent twice produces a different timestamp
and the same MD5. Keying on that MD5 makes a re-deposit free.

Three rules, each one for a defect already paid for elsewhere in this repository.

- **Not in `T_WC_T2S_CACHE`.** That table's contract is question to SQL; this one is image to
  entities. Sharing the table would mean a row whose `QUESTION` is not a question.
- **Scoped by API version**, like every other cache here, because `data/vision_identification.md`
  is hot-reloaded: without the scope, a prompt correction shipped without a version bump would
  keep serving identifications made by the previous prompt. Same trap as *Version management
  workflow* in AGENTS.md.
- **Only the question-independent half is stored.** `about_image` and `image_answer` depend on
  what the user asked and are deliberately dropped (see `identification_payload`). What remains,
  `hints` / `items` / `authoritative_empty` / `justification`, is a property of the image alone,
  which is what makes one row answer any later question about that photo. In particular an
  `authoritative_empty` IS cached, unlike the empty SQL result of Gotcha #8b: a photo of a meal
  will still be a photo of a meal tomorrow, and that is precisely the case where the cache most
  reliably avoids a pointless spend.

**The 30-day purge does not invalidate a row.** The key is the fingerprint of the bytes, not
the file, so an entry outlives the image it came from. It then serves the identification and
never the pixels: a question about the image itself still needs the file, and gets the
`410 Gone` of `uploads.load_vision_image`.

The module degrades gracefully when the table has not been created yet
(`maintenance/vision-recognition-cache.sql` is written and, per this repository's convention,
not applied from a developer machine): on the first "table doesn't exist" the flag below flips
and every later call is a silent miss, so the vision path keeps working, uncached, rather than
returning 500 on a migration that has not run.
"""
import json
from typing import Any, Optional

# Flips to False the first time the table turns out to be missing. Same degrade-once idiom as
# sql_cache._RESULT_ENTITY_COLUMN_AVAILABLE, and for the same reason: a cache is an
# optimisation, and an optimisation must never be the thing that breaks a request.
_VISION_CACHE_TABLE_AVAILABLE = True

# The keys of the vision payload that describe the IMAGE and not the question asked about it.
# Everything outside this set is recomputed per turn.
_CACHEABLE_KEYS = ("hints", "items", "authoritative_empty", "justification")

SELECT_VISION_CACHE_QUERY = """
SELECT IMAGE_MD5, IMAGE_REF, IDENTIFICATION, VISION_MODEL, AUTHORITATIVE_EMPTY,
       VISION_IDENTIFICATION_PROCESSING_TIME, TIM_UPDATED
FROM T_WC_T2S_VISION_CACHE
WHERE IMAGE_MD5 = %s
AND API_VERSION = %s
AND (DELETED IS NULL OR DELETED = 0)
ORDER BY TIM_UPDATED DESC
LIMIT 1
"""

# One row per (image, API version). A re-deposit of the same photo must not pile up rows, and
# a prompt change without a bump must not silently mix two generations, so the unique key does
# the de-duplication and the UPDATE keeps the freshest identification.
INSERT_VISION_CACHE_QUERY = """
INSERT INTO T_WC_T2S_VISION_CACHE
(IMAGE_MD5, API_VERSION, IMAGE_REF, IDENTIFICATION, VISION_MODEL, AUTHORITATIVE_EMPTY,
VISION_IDENTIFICATION_PROCESSING_TIME, DELETED, DAT_CREAT, TIM_UPDATED)
VALUES (%s, %s, %s, %s, %s, %s, %s, 0, CURDATE(), NOW())
ON DUPLICATE KEY UPDATE
IMAGE_REF = VALUES(IMAGE_REF),
IDENTIFICATION = VALUES(IDENTIFICATION),
VISION_MODEL = VALUES(VISION_MODEL),
AUTHORITATIVE_EMPTY = VALUES(AUTHORITATIVE_EMPTY),
VISION_IDENTIFICATION_PROCESSING_TIME = VALUES(VISION_IDENTIFICATION_PROCESSING_TIME),
DELETED = 0,
TIM_UPDATED = NOW()
"""


def _is_missing_table_error(exc: Exception) -> bool:
    """Detect a MariaDB/MySQL "Table doesn't exist" (error 1146) failure."""
    msg = str(exc).lower()
    return "1146" in msg or "doesn't exist" in msg or "does not exist" in msg


def identification_payload(payload: Any) -> dict:
    """Keep only what describes the image, dropping what describes the question.

    `about_image` and `image_answer` answer the user's wording of this turn, so storing them
    would make the cache serve yesterday's answer to today's question. Everything else is a
    property of the pixels.
    """
    if not isinstance(payload, dict):
        return {}
    kept = {k: payload[k] for k in _CACHEABLE_KEYS if k in payload}
    kept["authoritative_empty"] = bool(payload.get("authoritative_empty"))
    return kept


def is_cacheable(payload: Any) -> bool:
    """True when this identification is worth storing.

    A payload carrying an error is never stored: the next request must get its chance. An
    identification with no candidate IS stored when the model affirmed the emptiness, and only
    then, so "I could not read this" is repaid once and "there is nothing of cinema here" is
    paid once.
    """
    if not isinstance(payload, dict):
        return False
    if str(payload.get("error") or "").strip():
        return False
    if payload.get("items"):
        return True
    return bool(payload.get("authoritative_empty"))


def search_vision_cache(connection, image_md5: str, api_version: str) -> dict:
    """Look up a stored identification by the MD5 of the image bytes.

    Args:
        connection: An open DB connection.
        image_md5: The 32-hex fingerprint carried by the deposit filename.
        api_version: The FORMATTED version (``XXX.YYY.ZZZ``), like every other cache here.

    Returns:
        dict: ``{"found": bool, "identification": dict, "image_ref": str,
        "vision_model": str, "processing_time": float}``. A missing table, a malformed stored
        payload or any read failure is a miss, never an exception.
    """
    global _VISION_CACHE_TABLE_AVAILABLE
    miss = {"found": False, "identification": {}, "image_ref": "",
            "vision_model": "", "processing_time": 0.0}
    if not _VISION_CACHE_TABLE_AVAILABLE or not image_md5:
        return miss
    try:
        with connection.cursor() as cursor:
            cursor.execute(SELECT_VISION_CACHE_QUERY, (image_md5, api_version))
            row = cursor.fetchone()
    except Exception as exc:
        if _is_missing_table_error(exc):
            _VISION_CACHE_TABLE_AVAILABLE = False
            print("[vision-cache] T_WC_T2S_VISION_CACHE is absent; the recognition cache is "
                  "disabled for this process. Run maintenance/vision-recognition-cache.sql.")
            return miss
        print(f"[vision-cache] read failed, treating as a miss: {exc}")
        return miss

    if not row:
        return miss
    try:
        identification = json.loads(row.get("IDENTIFICATION") or "{}")
    except Exception as exc:
        print(f"[vision-cache] stored payload is not JSON, treating as a miss: {exc}")
        return miss
    if not isinstance(identification, dict):
        return miss
    return {
        "found": True,
        "identification": identification,
        "image_ref": row.get("IMAGE_REF") or "",
        "vision_model": row.get("VISION_MODEL") or "",
        "processing_time": float(row.get("VISION_IDENTIFICATION_PROCESSING_TIME") or 0.0),
    }


def write_vision_cache_entry(connection, *, image_md5: str, api_version: str,
                             identification: dict, image_ref: str = "",
                             vision_model: str = "",
                             processing_time: float = 0.0) -> dict:
    """Store one identification, keyed on the image fingerprint and the API version.

    Returns ``{"written": bool, "reason": str}``; a write failure is reported, never raised,
    for the same reason as the read above.
    """
    global _VISION_CACHE_TABLE_AVAILABLE
    if not _VISION_CACHE_TABLE_AVAILABLE:
        return {"written": False, "reason": "table absent"}
    if not image_md5:
        return {"written": False, "reason": "no image fingerprint"}
    payload = identification_payload(identification)
    try:
        serialized = json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        return {"written": False, "reason": f"payload not serializable: {exc}"}

    try:
        with connection.cursor() as cursor:
            cursor.execute(INSERT_VISION_CACHE_QUERY, (
                image_md5,
                api_version,
                image_ref or "",
                serialized,
                vision_model or "",
                1 if payload.get("authoritative_empty") else 0,
                float(processing_time or 0.0),
            ))
        connection.commit()
        return {"written": True, "reason": ""}
    except Exception as exc:
        if _is_missing_table_error(exc):
            _VISION_CACHE_TABLE_AVAILABLE = False
            print("[vision-cache] T_WC_T2S_VISION_CACHE is absent; the recognition cache is "
                  "disabled for this process. Run maintenance/vision-recognition-cache.sql.")
            return {"written": False, "reason": "table absent"}
        try:
            connection.rollback()
        except Exception:
            pass
        print(f"[vision-cache] write failed: {exc}")
        return {"written": False, "reason": str(exc)}


def table_available() -> Optional[bool]:
    """Whether the recognition-cache table has answered so far in this process.

    True before the first call (nothing has disproved it), and False once a read or a write
    has met a missing table. Exposed so a health probe can say "uncached" rather than guess.
    """
    return _VISION_CACHE_TABLE_AVAILABLE
