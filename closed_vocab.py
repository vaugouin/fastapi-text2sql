"""Closed-vocabulary entity resolution.

Loads canonical values from the database, loads aliases from a hot-reloaded
JSON config in ``data/closed_vocabularies.json`` plus (for genres) from a
multilingual DB table, and exposes a typo-tolerant matcher built on RapidFuzz.

Design:
- Canonical values come from the database (Status, Serie_type, Genre) so the
  source code never hard-codes a list. Genre id<->name uses T_WC_TMDB_GENRE,
  split into Movie_genre / Serie_genre via APPLIES_TO_MOVIE / APPLIES_TO_SERIE
  flags so a query against the movie junction cannot resolve to a TV-only
  genre and vice versa.
- Multilingual genre aliases come from T_WC_TMDB_GENRE_LANG (currently French;
  extensible to any LANG code by adding rows), filtered by the same flags.
- Additional English colloquialisms and per-entity synonyms come from a JSON
  file watched by ``data_watcher`` so editors can add aliases ("annule" ->
  "Canceled", "rom-com" -> "Romance") without restarting the API.
- Every entity goes through the same ``_resolve_closed_vocab`` matcher so
  alias resolution and typo tolerance are uniform across all entities.
"""

from __future__ import annotations

import json
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


def _load_genre_id_map(connection, query: str) -> dict[str, int]:
    """Run a query returning (id, name) rows and produce {normalized_name: id}."""
    result: dict[str, int] = {}
    with connection.cursor() as cursor:
        cursor.execute(query)
        for row in cursor.fetchall():
            if isinstance(row, dict):
                gid = row.get("id")
                name = row.get("name")
            else:
                gid = row[0] if len(row) > 0 else None
                name = row[1] if len(row) > 1 else None
            if gid is None or name is None:
                continue
            name_str = str(name).strip()
            if not name_str:
                continue
            try:
                result[_normalize(name_str)] = int(gid)
            except (TypeError, ValueError):
                continue
    return result


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
_DEPARTMENT_QUERY = (
    "SELECT DISTINCT CREW_DEPARTMENT AS V FROM T_WC_T2S_PERSON_MOVIE "
    "WHERE CREW_DEPARTMENT IS NOT NULL AND CREW_DEPARTMENT NOT IN ('Actors', 'Acting') "
    "UNION SELECT DISTINCT CREW_DEPARTMENT AS V FROM T_WC_T2S_PERSON_SERIE "
    "WHERE CREW_DEPARTMENT IS NOT NULL AND CREW_DEPARTMENT NOT IN ('Actors', 'Acting') "
    "UNION SELECT DISTINCT KNOWN_FOR_DEPARTMENT AS V FROM T_WC_T2S_PERSON "
    "WHERE KNOWN_FOR_DEPARTMENT IS NOT NULL AND KNOWN_FOR_DEPARTMENT NOT IN ('Actors', 'Acting')"
)
_MOVIE_GENRE_CANONICALS_QUERY = (
    "SELECT id, name FROM T_WC_TMDB_GENRE "
    "WHERE name IS NOT NULL AND APPLIES_TO_MOVIE = 1"
)
_SERIE_GENRE_CANONICALS_QUERY = (
    "SELECT id, name FROM T_WC_TMDB_GENRE "
    "WHERE name IS NOT NULL AND APPLIES_TO_SERIE = 1"
)
_MOVIE_GENRE_DB_ALIASES_QUERY = (
    "SELECT l.id, l.name FROM T_WC_TMDB_GENRE_LANG l "
    "JOIN T_WC_TMDB_GENRE g ON g.id = l.id "
    "WHERE l.name IS NOT NULL AND g.APPLIES_TO_MOVIE = 1"
)
_SERIE_GENRE_DB_ALIASES_QUERY = (
    "SELECT l.id, l.name FROM T_WC_TMDB_GENRE_LANG l "
    "JOIN T_WC_TMDB_GENRE g ON g.id = l.id "
    "WHERE l.name IS NOT NULL AND g.APPLIES_TO_SERIE = 1"
)
_TECHNICAL_CANONICALS_QUERY = (
    "SELECT ID_TECHNICAL AS id, DESCRIPTION AS name FROM T_WC_T2S_TECHNICAL "
    "WHERE DESCRIPTION IS NOT NULL AND (DELETED = 0 OR DELETED IS NULL)"
)


def init(connection) -> None:
    """Load canonical maps from the database; called once at startup."""
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
        loaded["Department_name"] = _load_distinct(connection, _DEPARTMENT_QUERY)
    except Exception as e:
        print(f"[closed_vocab] Failed to load Department_name canonicals: {e}")
        loaded["Department_name"] = {}

    try:
        loaded["Movie_genre"] = _load_genre_id_map(connection, _MOVIE_GENRE_CANONICALS_QUERY)
    except Exception as e:
        print(f"[closed_vocab] Failed to load Movie_genre canonicals: {e}")
        loaded["Movie_genre"] = {}

    try:
        loaded["Movie_genre_db_aliases"] = _load_genre_id_map(connection, _MOVIE_GENRE_DB_ALIASES_QUERY)
    except Exception as e:
        print(f"[closed_vocab] Failed to load Movie_genre DB aliases: {e}")
        loaded["Movie_genre_db_aliases"] = {}

    try:
        loaded["Serie_genre"] = _load_genre_id_map(connection, _SERIE_GENRE_CANONICALS_QUERY)
    except Exception as e:
        print(f"[closed_vocab] Failed to load Serie_genre canonicals: {e}")
        loaded["Serie_genre"] = {}

    try:
        loaded["Serie_genre_db_aliases"] = _load_genre_id_map(connection, _SERIE_GENRE_DB_ALIASES_QUERY)
    except Exception as e:
        print(f"[closed_vocab] Failed to load Serie_genre DB aliases: {e}")
        loaded["Serie_genre_db_aliases"] = {}

    try:
        loaded["Technical_format"] = _load_genre_id_map(connection, _TECHNICAL_CANONICALS_QUERY)
    except Exception as e:
        print(f"[closed_vocab] Failed to load Technical_format canonicals: {e}")
        loaded["Technical_format"] = {}

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
    """Resolve a string-canonical value (Status_name / Serie_type / Department_name)
    to its canonical form, applying alias and typo tolerance."""
    canonical = _CANONICAL.get(entity, {})
    aliases = _aliases_for(entity)
    return _resolve_closed_vocab(raw_value, canonical, aliases)


def _resolve_genre_for(entity: str, raw_value: Any) -> int | None:
    """Resolve a genre name to its integer ID for a given side ("Movie_genre"
    or "Serie_genre"). The canonical map is filtered to the genres that apply
    to that side via APPLIES_TO_MOVIE / APPLIES_TO_SERIE on T_WC_TMDB_GENRE,
    so a query against the movie junction cannot resolve to a TV-only genre
    and vice versa.
    """
    canonical = _CANONICAL.get(entity, {})
    if not canonical:
        return None
    db_aliases = _CANONICAL.get(f"{entity}_db_aliases", {}) or {}
    json_aliases = _aliases_for(entity, target_canonical=canonical)
    aliases = {**db_aliases, **json_aliases}
    return _resolve_closed_vocab(raw_value, canonical, aliases)


def resolve_movie_genre(raw_value: Any) -> int | None:
    """Resolve a genre name to its integer ID, restricted to movie-applicable
    genres (TMDb /genre/movie/list). Multilingual aliases come from
    T_WC_TMDB_GENRE_LANG joined against APPLIES_TO_MOVIE; English colloquialisms
    ("scifi", "biopic", "rom-com", ...) live under "Movie_genre" in
    data/closed_vocabularies.json. DB and JSON aliases are merged (JSON wins on
    conflict) and run through the same RapidFuzz-backed resolver as the other
    closed vocabularies.
    """
    return _resolve_genre_for("Movie_genre", raw_value)


def resolve_serie_genre(raw_value: Any) -> int | None:
    """Resolve a genre name to its integer ID, restricted to series-applicable
    genres (TMDb /genre/tv/list). Same alias machinery as
    ``resolve_movie_genre`` but reads from "Serie_genre" canonicals, the
    APPLIES_TO_SERIE-filtered multilingual aliases, and the "Serie_genre" block
    in data/closed_vocabularies.json. This is what lets "scifi series" resolve
    to "Sci-Fi & Fantasy" (10765) instead of "Science Fiction" (878).
    """
    return _resolve_genre_for("Serie_genre", raw_value)


def resolve_technical(raw_value: Any) -> int | None:
    """Resolve a technical-format name (sound system, color tech, film tech, format) to its integer ID.

    Canonicals come from T_WC_T2S_TECHNICAL.DESCRIPTION (English / loanword
    surface forms such as "imax", "technicolor", "cinemascope", "35 mm").
    Aliases (typo / format / multilingual variants like "35mm", "scope",
    "dolby digital", "todd-ao") live in data/closed_vocabularies.json under
    the Technical_format key. The matcher merges JSON aliases with the
    canonical map and goes through the same RapidFuzz-backed resolver as
    Status_name / Serie_type / Movie_genre / Serie_genre.
    """
    canonical = _CANONICAL.get("Technical_format", {})
    if not canonical:
        return None
    json_aliases = _aliases_for("Technical_format", target_canonical=canonical)
    return _resolve_closed_vocab(raw_value, canonical, json_aliases)


def get_canonical_size(entity: str) -> int:
    """Diagnostic: number of canonical entries currently loaded for an entity."""
    return len(_CANONICAL.get(entity, {}))
