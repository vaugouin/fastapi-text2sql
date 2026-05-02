"""Closed-vocabulary entity resolution.

Loads canonical values from the database (or, for genres, from the
text_to_sql.md prompt), loads aliases from a hot-reloaded JSON config in
``data/closed_vocabularies.json``, and exposes a typo-tolerant matcher built
on RapidFuzz.

Design:
- Canonical values come from the database when a column actually stores them
  (Status, Serie_type) so the source code never hard-codes a list. Genre
  id <-> name mappings have no DB reference table, so they are parsed once
  from the text_to_sql.md prompt.
- Aliases come from a JSON file watched by ``data_watcher`` so editors can add
  synonyms ("annule" -> "Canceled", "academy ratio" -> "1.37") without
  restarting the API.
- Every entity goes through the same ``_resolve_closed_vocab`` matcher so
  alias resolution and typo tolerance are uniform across all entities.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz, process

import data_watcher


SCORE_CUTOFF = 85
SCORE_MARGIN = 5

# In-memory canonical maps. Keys are normalized (lowercase, accent-stripped,
# whitespace-collapsed). Values are the canonical form to substitute into
# SQL: a string for textual columns, an integer for ID columns (Genre).
_CANONICAL: dict[str, dict[str, Any]] = {}

# Aliases loaded from data/closed_vocabularies.json. Outer key is the entity
# name; the inner dict has shape {"aliases": {"alias text": "canonical name"}}.
_ALIASES_RAW: dict[str, dict[str, Any]] = {}


def _normalize(value: Any) -> str:
    """Return a normalized matching key (lower, accent-stripped, whitespace-collapsed)."""
    if value is None:
        return ""
    s = str(value).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = " ".join(s.split())
    return s


def _resolve_closed_vocab(
    raw: Any,
    canonical: dict[str, Any],
    aliases: dict[str, Any] | None = None,
    score_cutoff: int = SCORE_CUTOFF,
    margin: int = SCORE_MARGIN,
) -> Any:
    """Resolve a raw value to its canonical form, with alias and typo tolerance."""
    norm = _normalize(raw)
    if not norm or not canonical:
        return None
    if norm in canonical:
        return canonical[norm]
    if aliases and norm in aliases:
        return aliases[norm]
    keys = list(canonical.keys()) + list((aliases or {}).keys())
    if not keys:
        return None
    matches = process.extract(norm, keys, scorer=fuzz.WRatio, limit=2)
    if not matches:
        return None
    best_key, best_score, _ = matches[0]
    if best_score < score_cutoff:
        return None
    if len(matches) > 1 and (best_score - matches[1][1]) < margin:
        return None
    if aliases and best_key in aliases:
        return aliases[best_key]
    return canonical.get(best_key)


def _load_distinct(connection, query: str) -> dict[str, str]:
    """Run a SELECT DISTINCT-style query and return {normalized: canonical_value}."""
    result: dict[str, str] = {}
    with connection.cursor() as cursor:
        cursor.execute(query)
        for row in cursor.fetchall():
            if isinstance(row, dict):
                value = next(iter(row.values()), None)
            else:
                value = row[0] if row else None
            if value is None:
                continue
            value_str = str(value).strip()
            if not value_str:
                continue
            result[_normalize(value_str)] = value_str
    return result


_GENRE_HEADER_MOVIE = "### Genre Reference for movies T_WC_T2S_MOVIE_GENRE"
_GENRE_HEADER_SERIE = "### Genre Reference for series T_WC_T2S_SERIE_GENRE"
_GENRE_PAIR_RE = re.compile(r"(\d+)\s*:\s*([^,\n]+?)(?=,|\n|$)")
_GENRE_ALT_RE = re.compile(r"^(.+?)\s*\(\s*or\s+(.+?)\s*\)\s*$", re.IGNORECASE)


def _parse_genre_section(prompt_text: str, header: str) -> dict[str, int]:
    """Parse the 'id: Name, id: Name, ...' table that follows ``header`` in the prompt."""
    start = prompt_text.find(header)
    if start == -1:
        return {}
    next_section = prompt_text.find("\n###", start + len(header))
    end = next_section if next_section != -1 else len(prompt_text)
    section = prompt_text[start + len(header) : end]

    result: dict[str, int] = {}
    for match in _GENRE_PAIR_RE.finditer(section):
        genre_id = int(match.group(1))
        raw_name = match.group(2).strip()
        alt_match = _GENRE_ALT_RE.match(raw_name)
        if alt_match:
            primary = alt_match.group(1).strip()
            alternative = alt_match.group(2).strip()
            result[_normalize(primary)] = genre_id
            result[_normalize(alternative)] = genre_id
        else:
            result[_normalize(raw_name)] = genre_id
    return result


def _read_data_file(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "data", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _on_aliases_change(content: str) -> None:
    """Hot-reload callback for data/closed_vocabularies.json."""
    global _ALIASES_RAW
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("closed_vocabularies.json must be a JSON object")
        _ALIASES_RAW = parsed
    except Exception as e:
        print(f"[closed_vocab] Failed to reload closed_vocabularies.json, keeping previous: {e}")


# Aliases hot-reload via data_watcher; canonicals are loaded once by init().
data_watcher.register("closed_vocabularies.json", _on_aliases_change)


_STATUS_QUERY = (
    "SELECT STATUS AS V FROM T_WC_T2S_MOVIE WHERE STATUS IS NOT NULL "
    "UNION SELECT STATUS AS V FROM T_WC_T2S_SERIE WHERE STATUS IS NOT NULL"
)
_SERIE_TYPE_QUERY = (
    "SELECT DISTINCT SERIE_TYPE AS V FROM T_WC_T2S_SERIE WHERE SERIE_TYPE IS NOT NULL"
)


def init(connection) -> None:
    """Load canonical maps from the database and prompt; called once at startup."""
    global _CANONICAL
    loaded: dict[str, dict[str, Any]] = {}

    try:
        loaded["Status_name"] = _load_distinct(connection, _STATUS_QUERY)
    except Exception as e:
        print(f"[closed_vocab] Failed to load Status_name canonicals: {e}")
        loaded["Status_name"] = {}

    try:
        loaded["Serie_type"] = _load_distinct(connection, _SERIE_TYPE_QUERY)
    except Exception as e:
        print(f"[closed_vocab] Failed to load Serie_type canonicals: {e}")
        loaded["Serie_type"] = {}

    try:
        prompt_text = _read_data_file("text_to_sql.md")
        loaded["Genre_name_movie"] = _parse_genre_section(prompt_text, _GENRE_HEADER_MOVIE)
        loaded["Genre_name_serie"] = _parse_genre_section(prompt_text, _GENRE_HEADER_SERIE)
    except Exception as e:
        print(f"[closed_vocab] Failed to parse Genre canonicals from text_to_sql.md: {e}")
        loaded.setdefault("Genre_name_movie", {})
        loaded.setdefault("Genre_name_serie", {})

    _CANONICAL = loaded
    summary = ", ".join(f"{k}={len(v)}" for k, v in _CANONICAL.items())
    print(f"[closed_vocab] Loaded canonical maps: {summary}")


def refresh(connection) -> None:
    """Reload canonical maps from the database and prompt without restarting."""
    init(connection)


def _aliases_for(entity: str, target_canonical: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return normalized {alias_norm: canonical_value} for an entity.

    The JSON config maps alias text -> canonical NAME (a string the user would
    expect to see). When ``target_canonical`` is provided (Genre case), the
    canonical NAME is looked up in that map to produce an integer ID; otherwise
    the canonical name is returned as-is (Status, Serie_type).
    """
    raw = (_ALIASES_RAW.get(entity) or {}).get("aliases") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for alias_text, canonical_name in raw.items():
        if alias_text is None or canonical_name is None:
            continue
        alias_key = _normalize(alias_text)
        if not alias_key:
            continue
        if target_canonical is None:
            out[alias_key] = str(canonical_name)
        else:
            canonical_id = target_canonical.get(_normalize(canonical_name))
            if canonical_id is not None:
                out[alias_key] = canonical_id
    return out


def resolve(entity: str, raw_value: Any) -> Any:
    """Resolve a Status_name / Serie_type value to its canonical string form."""
    canonical = _CANONICAL.get(entity, {})
    aliases = _aliases_for(entity)
    return _resolve_closed_vocab(raw_value, canonical, aliases)


def resolve_genre(raw_value: Any, sql_query: str | None = None) -> int | None:
    """Resolve a genre name to its integer ID, picking movie vs serie context from the SQL."""
    movie_map = _CANONICAL.get("Genre_name_movie", {})
    serie_map = _CANONICAL.get("Genre_name_serie", {})
    if not movie_map and not serie_map:
        return None

    sql_upper = (sql_query or "").upper()
    mentions_serie_genre = "SERIE_GENRE" in sql_upper
    mentions_movie_genre = "MOVIE_GENRE" in sql_upper

    if mentions_serie_genre and not mentions_movie_genre:
        primary, secondary = serie_map, movie_map
    elif mentions_movie_genre and not mentions_serie_genre:
        primary, secondary = movie_map, serie_map
    else:
        primary, secondary = movie_map, serie_map

    # ``primary`` wins over ``secondary`` for keys present in both, matching
    # the previous behaviour of _resolve_genre_id.
    combined: dict[str, int] = {**secondary, **primary}
    aliases = _aliases_for("Genre_name", target_canonical=combined)
    return _resolve_closed_vocab(raw_value, combined, aliases)


def get_canonical_size(entity: str) -> int:
    """Diagnostic: number of canonical entries currently loaded for an entity."""
    return len(_CANONICAL.get(entity, {}))
