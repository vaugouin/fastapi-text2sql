from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import httpx
from fastmcp import FastMCP
from auth import get_api_key
from pydantic import BaseModel, field_validator, model_validator
import pandas as pd 
import numpy as np 
import text2sql as t2s
import os
import json
import hashlib
from datetime import datetime
import time
import threading
from urllib.parse import unquote_plus
import pymysql.cursors
from dotenv import load_dotenv
import re
import html
import openai
import chromadb
import cleanup
import entity
import logs
import sql_cache
import closed_vocab
import samples_assertions as sa

# Load environment variables from .env file
load_dotenv()

# Convert API version to XXX.YYY.ZZZ format for comparison
def format_api_version(version: str) -> str:
    """Convert version string to XXX.YYY.ZZZ format for comparison."""
    version_parts = version.split('.')
    return f"{int(version_parts[0]):03d}.{int(version_parts[1]):03d}.{int(version_parts[2]):03d}"

def compare_versions(version1: str, version2: str) -> int:
    """
    Compare two version strings.
    Returns: -1 if version1 < version2, 0 if equal, 1 if version1 > version2
    """
    v1_formatted = format_api_version(version1)
    v2_formatted = format_api_version(version2)
    
    if v1_formatted < v2_formatted:
        return -1
    elif v1_formatted > v2_formatted:
        return 1
    else:
        return 0

def _extract_retry_metadata(error_text: str) -> dict:
    error_raw = str(error_text or "")
    error_upper = error_raw.upper()
    retry_after_seconds = None
    for pattern in [
        r"Please retry in\s+([0-9]+(?:\.[0-9]+)?)s",
        r"retryDelay['\"]?\s*[:=]\s*['\"]?([0-9]+(?:\.[0-9]+)?)s",
        r"retry after\s+([0-9]+(?:\.[0-9]+)?)s",
    ]:
        match = re.search(pattern, error_raw, flags=re.IGNORECASE)
        if match:
            try:
                retry_after_seconds = float(match.group(1))
                break
            except (TypeError, ValueError):
                pass

    error_code = None
    if "429" in error_upper or "RESOURCE_EXHAUSTED" in error_upper or "RATE_LIMIT" in error_upper:
        error_code = "429"

    is_retryable = bool(
        error_code == "429"
        or "RESOURCE_EXHAUSTED" in error_upper
        or "QUOTA EXCEEDED" in error_upper
        or "RATE_LIMIT" in error_upper
    )

    provider = None
    if "GOOGLE" in error_upper or "GENERATIVELANGUAGE.GOOGLEAPIS.COM" in error_upper or "AI.GOOGLE.DEV" in error_upper:
        provider = "google"
    elif "OPENROUTER" in error_upper:
        provider = "openrouter"
    elif "OPENAI" in error_upper:
        provider = "openai"
    elif "ANTHROPIC" in error_upper or "CLAUDE" in error_upper:
        provider = "anthropic"

    return {
        "error_code": error_code,
        "is_retryable": is_retryable,
        "retry_after_seconds": retry_after_seconds,
        "provider": provider,
    }


def _is_retryable_quota_error_text(error_text: str) -> bool:
    retry_metadata = _extract_retry_metadata(error_text)
    return bool(retry_metadata.get("is_retryable") and str(retry_metadata.get("error_code") or "") == "429")

# Change API version each time the prompt file in the data folder is updated and text2sql API container is restarted
strapiversion = "1.1.17"
# Convert API version to XXX.YYY.ZZZ format
strapiversionformatted = format_api_version(strapiversion)

API_PORT_BLUE = int(os.getenv('API_PORT_BLUE', 8000))
API_PORT_GREEN = int(os.getenv('API_PORT_GREEN', 8001))
_mcp_patch = int(strapiversion.split('.')[2])
MCP_API_KEY = os.getenv("MCP_API_KEY", "")
_api_keys_raw = os.getenv("API_KEYS") or os.getenv("API_KEY", "")
_api_keys_first = next((k.strip() for k in _api_keys_raw.split(",") if k.strip()), "")
MCP_INTERNAL_API_KEY = os.getenv("MCP_INTERNAL_API_KEY", _api_keys_first)
MCP_INTERNAL_BASE_URL = os.getenv(
    "MCP_INTERNAL_BASE_URL",
    f"http://127.0.0.1:{API_PORT_BLUE if _mcp_patch % 2 == 0 else API_PORT_GREEN}"
)

intcleanupenabled = False
#intcleanupenabled = True

_startup_t0 = time.perf_counter()
print(f"[startup] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
print(f"[startup] Booting Text2SQL API version {strapiversion}...", flush=True)

# Set your OpenAI API key from environment variable
print("[startup] Loading OpenAI API key from environment...", flush=True)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Validate that the API key was loaded
if not openai.api_key:
    raise ValueError("OPENAI_API_KEY not found in environment variables. Please check your .env file.")
print("[startup] OpenAI API key loaded.", flush=True)

class OpenAIEmbeddingFunction:
    def __init__(self, model="text-embedding-3-large"):
        """Initialize the ChromaDB-compatible embedding wrapper with an OpenAI model name."""
        self.model = model

    def __call__(self, input):
        """Generate embeddings for a list of texts using OpenAI's embedding model."""
        response = openai.embeddings.create(
            input=input, # Ensure parameter name matches ChromaDB's expectations
            model=self.model
        )
        # Convert to numpy arrays for ChromaDB compatibility
        embeddings = [item.embedding for item in response.data]
        return [np.array(embedding) for embedding in embeddings]
    
    def embed_query(self, input):
        """Generate embedding for a single query text - required by ChromaDB."""
        # Handle both single string and list inputs
        if isinstance(input, str):
            query_input = [input]
        else:
            query_input = input
            
        response = openai.embeddings.create(
            input=query_input,
            model=self.model
        )
        # Return as a list of numpy arrays (same format as __call__ method)
        embeddings = [item.embedding for item in response.data]
        return [np.array(embedding) for embedding in embeddings]
    
    def name(self):
        """Return the name of the embedding function for ChromaDB compatibility."""
        return f"openai_{self.model.replace('-', '_')}"

# Initialize ChromaDB with persistent storage
_chromadb_host = os.getenv("CHROMADB_HOST", "localhost")
_chromadb_port = os.getenv("CHROMADB_PORT", 8000)
print(f"[startup] Connecting to ChromaDB at {_chromadb_host}:{_chromadb_port}...", flush=True)
_t0 = time.perf_counter()
chroma_client = chromadb.HttpClient(host=_chromadb_host, port=_chromadb_port)
print(f"[startup] ChromaDB connected in {time.perf_counter() - _t0:.2f}s.", flush=True)

# Initialize ChromaDB with OpenAI's embedding function
embedding_function = OpenAIEmbeddingFunction(model="text-embedding-3-large")
print("[startup] OpenAI embedding function initialized (text-embedding-3-large).", flush=True)

# Create or load entity collections with the custom embedding function
_collection_names = [
    "persons",
    "movies",
    "series",
    "companies",
    "networks",
    "topics",
    "locations",
    "groups",
    "characters",
    "lists",
    "collections",
    "deaths",
    "awards",
    "nominations",
    "movements",
]
print(f"[startup] Creating/loading {len(_collection_names)} ChromaDB entity collections...", flush=True)
_t0 = time.perf_counter()
CHROMADB_COLLECTIONS_BY_NAME = {
    name: chroma_client.get_or_create_collection(name=name, embedding_function=embedding_function)
    for name in _collection_names
}
print(f"[startup] ChromaDB entity collections ready ({len(CHROMADB_COLLECTIONS_BY_NAME)}) in {time.perf_counter() - _t0:.2f}s.", flush=True)

#Anonymized queries collection
strentitycollection = "anonymizedqueries"
print(f"[startup] Creating/loading {strentitycollection} cache collection...", flush=True)
_t0 = time.perf_counter()
anonymizedqueries = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
print(f"[startup] {strentitycollection} collection ready in {time.perf_counter() - _t0:.2f}s.", flush=True)

# By default, do not use embeddings-based question cache (read/write) for anonymized queries.
USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE = False

if intcleanupenabled:
    if USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE:
        print(f"[startup] Cleaning up {strentitycollection} embeddings for previous API versions...", flush=True)
        _t0 = time.perf_counter()
        cleanup.cleanup_anonymized_queries_collection(anonymizedqueries, strapiversion)
        print(f"[startup] {strentitycollection} cleanup done in {time.perf_counter() - _t0:.2f}s.", flush=True)

# How many rows per page in the result set
lngrowsperpagedefault = 50
#similarity_threshold = 0.1
"""
Similarity 0.2 is too wide because the following queries are deemed similar:
Movies with Humphrey Bogart
Movies with Humphrey Bogart and Lauren Bacall
Which is wrong
"""
#similarity_threshold = 0.2  
similarity_threshold = 0.15

CAST_CHARACTER_EXCLUSIONS = {
    "Self",
    "Himself",
    "Herself",
    "(archive footage)",
    "Self (archive footage)",
    "Self (archive footage) (uncredited)",
    "Self (uncredited)",
}

mcp = FastMCP("text2sql")
mcp_app = mcp.http_app(stateless_http=True)
# FastMCP lifespan: Pass mcp_app.lifespan to the FastAPI constructor
app = FastAPI(title="Text2SQL API", version=strapiversion, description="Text2SQL API for text to SQL query conversion", lifespan=mcp_app.lifespan)

def get_db_connection():
    """Establish and return a database connection to MySQL.
    
    Reads database configuration from environment variables and creates
    a PyMySQL connection with DictCursor for dictionary-based results.
    
    Returns:
        pymysql.Connection: Database connection object with DictCursor
        
    Raises:
        pymysql.Error: If database connection fails
        ValueError: If required environment variables are missing
    """
    strdbhost = os.getenv('DB_HOST')
    lngdbport = int(os.getenv('DB_PORT', 3306))
    strdbuser = os.getenv('DB_USER')
    strdbpassword = os.getenv('DB_PASSWORD')
    strdbname = os.getenv('DB_NAME')

    return pymysql.connect(
        host=strdbhost,
        port=lngdbport,
        user=strdbuser,
        password=strdbpassword,
        database=strdbname,
        cursorclass=pymysql.cursors.DictCursor
    )

answer=42

_db_host = os.getenv('DB_HOST', '?')
_db_port = os.getenv('DB_PORT', 3306)
_db_name = os.getenv('DB_NAME', '?')
print(f"[startup] Connecting to MariaDB {_db_name} at {_db_host}:{_db_port}...", flush=True)
_t0 = time.perf_counter()
connection = get_db_connection()
print(f"[startup] MariaDB connected in {time.perf_counter() - _t0:.2f}s.", flush=True)

if intcleanupenabled:
    print("[startup] Cleaning up SQL cache for current API version...", flush=True)
    _t0 = time.perf_counter()
    cleanup.cleanup_sql_cache(connection, strapiversion)
    print(f"[startup] SQL cache cleanup done in {time.perf_counter() - _t0:.2f}s.", flush=True)

print("[startup] Loading closed-vocabulary canonicals from DB (Status_name, Serie_type, Department_name, Movie_genre, Serie_genre, Technical_format)...", flush=True)
_t0 = time.perf_counter()
closed_vocab.init(connection)
print(f"[startup] Closed-vocabulary canonicals loaded in {time.perf_counter() - _t0:.2f}s.", flush=True)

# BK-tree warm-up runs in the BACKGROUND (FASTAPI-TEXT2SQL-145) so uvicorn serves
# immediately instead of blocking for minutes on large person tables. The warm-up
# thread uses its OWN DB connection; any RapidFuzz query that arrives before a tree is
# ready lazy-builds it, and get_or_build_bktree makes that race-safe (built once).
print("[startup] Starting RapidFuzz BK-tree warm-up in the background (API available immediately; first RapidFuzz query may lazy-build)...", flush=True)
def _warm_bktrees_background():
    _t = time.perf_counter()
    conn_bg = None
    try:
        conn_bg = get_db_connection()
        entity.prebuild_bktrees(conn_bg)
        print(f"[startup] BK-tree warm-up complete in {time.perf_counter() - _t:.1f}s.", flush=True)
    except Exception as e:
        print(f"[startup] BK-tree warm-up failed: {e}", flush=True)
    finally:
        if conn_bg is not None:
            try:
                conn_bg.close()
            except Exception:
                pass
threading.Thread(target=_warm_bktrees_background, name="bktree-warmup", daemon=True).start()

print(f"[startup] Startup tasks complete in {time.perf_counter() - _startup_t0:.2f}s. Handing off to uvicorn.", flush=True)

# ---------------------------------------------------------------------------
# UI language handling
# ---------------------------------------------------------------------------
# The user-oriented `answer` field is written in the requested UI language.
# Only English and French are supported; any missing, empty, or unsupported
# value falls back to the default ("en"). This is the single source of truth
# for both the REST API (via the Text2SQLRequest validator) and the MCP tools.
DEFAULT_UI_LANGUAGE = "en"
SUPPORTED_UI_LANGUAGES = frozenset({"en", "fr"})


def normalize_ui_language(value) -> str:
    """Normalize a requested UI language to a supported code.

    Supported languages are English ("en") and French ("fr"). Region/script
    variants are reduced to their base subtag (e.g. "fr-FR" -> "fr",
    "EN_us" -> "en"). Any missing, empty, or unsupported value falls back to
    the default ("en").

    Args:
        value: Raw ui_language value from a request (any type; typically str or None).

    Returns:
        str: A supported language code, one of SUPPORTED_UI_LANGUAGES.
    """
    if value is None:
        return DEFAULT_UI_LANGUAGE
    code = str(value).strip().lower().replace("_", "-").split("-")[0]
    if code in SUPPORTED_UI_LANGUAGES:
        return code
    return DEFAULT_UI_LANGUAGE


def localize_row(row: dict, ui_language: str) -> dict:
    """Collapse every ``<COL>`` / ``<COL>_FR`` pair in a DB row into one localized field.

    The data-driven contract: for any key ending in ``_FR``, the matching base
    column ``<COL>`` becomes the localized value and the ``<COL>_FR`` key is
    removed, so the response exposes a single clean field per column regardless of
    language. For ``ui_language == "fr"`` the base takes its ``_FR`` value when that
    value is present (non-empty), otherwise it keeps the English base as a fallback.
    For any other language the English base is kept untouched. Rows without ``_FR``
    keys are returned unchanged. Mutates and returns the same dict.
    """
    if not isinstance(row, dict):
        return row
    use_fr = ui_language == "fr"
    for fr_key in [k for k in row if k.endswith("_FR")]:
        base_key = fr_key[:-3]
        if use_fr:
            fr_value = row.get(fr_key)
            if fr_value is not None and (not isinstance(fr_value, str) or fr_value.strip() != ""):
                row[base_key] = fr_value
        del row[fr_key]
    return row


def apply_localized_main_image(entity: dict, image_rows, path_key: str, ui_language: str) -> None:
    """Override an entity's main picture path with its localized image for non-default languages.

    For ``ui_language`` other than the default ("en"), pick the main picture (the
    lowest ``DISPLAY_ORDER`` row) whose ``LANG`` matches the requested language from
    the entity's own related image rows (``image_rows`` — e.g. its posters or
    portraits, already ordered by ``DISPLAY_ORDER ASC``) and write its ``IMAGE_PATH``
    onto ``entity[path_key]`` (e.g. ``POSTER_PATH`` / ``PROFILE_PATH``). When no image
    in the requested language exists, the entity keeps its canonical (English/default)
    path as a fallback. For the default language the entity is left untouched. Mutates
    ``entity`` in place.
    """
    if ui_language == DEFAULT_UI_LANGUAGE or not isinstance(entity, dict) or not image_rows:
        return
    for row in image_rows:
        if not isinstance(row, dict) or row.get("LANG") != ui_language:
            continue
        image_path = row.get("IMAGE_PATH")
        if image_path is not None and (not isinstance(image_path, str) or image_path.strip() != ""):
            entity[path_key] = image_path
            return


def apply_localized_text(entity: dict, conn, table: str, id_column: str, id_value, ui_language: str, columns=("OVERVIEW", "TAGLINE")) -> None:
    """Override an entity's English display text with its localized row for non-default languages.

    The T2S base tables (``T_WC_T2S_MOVIE`` / ``T_WC_T2S_SERIE``) carry English
    ``OVERVIEW`` / ``TAGLINE`` only; the localized text lives in sibling
    row-per-language tables (``T_WC_T2S_MOVIE_LANG`` / ``T_WC_T2S_SERIE_LANG``, one row
    per ``(id, LANG)``, built by tmdb-movie-preprocess). For a non-default
    ``ui_language`` look up the matching ``(id, LANG)`` row and overwrite each column
    when its localized value is non-empty (never overwrite with a blank -- same
    empty-guard as ``localize_row``). When no localized row exists (or the column is
    empty there) the entity keeps its canonical English text as a fallback. For the
    default language the entity is left untouched. Mutates ``entity`` in place.

    ``table``, ``id_column`` and ``columns`` are fixed code-supplied identifiers (never
    request input), so their interpolation into the query is safe; ``id_value`` and the
    language are bound as parameters.
    """
    if ui_language == DEFAULT_UI_LANGUAGE or not isinstance(entity, dict):
        return
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(columns)} FROM {table} WHERE {id_column} = %s AND LANG = %s",
                (id_value, ui_language),
            )
            localized = cursor.fetchone()
    except Exception:
        # Localized text is an enhancement over the English base already present in
        # ``entity``; a lookup failure (e.g. the _LANG table not yet built on a fresh
        # environment, since it is created by tmdb-movie-preprocess) must never break
        # the detail response. Degrade silently to the English fallback.
        return
    if not localized:
        return
    for col in columns:
        value = localized.get(col)
        if value is not None and (not isinstance(value, str) or value.strip() != ""):
            entity[col] = value


# Nested related-entity kinds whose main picture can be localized, mapped to the
# language-tagged image table that supplies the localized path:
#   kind -> (image_table, id_column, type_image, path_key)
# Each nested row carries id_column + path_key but not its own image array, so the
# localized main image is fetched in one batched query per kind (see
# apply_localized_related_images). The `season` kind reads the TMDb source image
# table, matching the /seasons endpoint's own poster source.
_RELATED_IMAGE_SOURCES = {
    "movie": ("T_WC_T2S_MOVIE_IMAGE", "ID_MOVIE", "poster", "POSTER_PATH"),
    "serie": ("T_WC_T2S_SERIE_IMAGE", "ID_SERIE", "poster", "POSTER_PATH"),
    "person": ("T_WC_T2S_PERSON_IMAGE", "ID_PERSON", "profile", "PROFILE_PATH"),
    "season": ("T_WC_TMDB_SEASON_IMAGE", "ID_SEASON", "poster", "POSTER_PATH"),
}

# Single source of truth: result_entity -> (id column, primary table).
# Drives the answer-entity guard (FASTAPI-TEXT2SQL-117/-136) for EVERY entity the
# text-to-SQL prompt can emit as `result_entity` (see data/text_to_sql.md line 16),
# not just the original movie/serie/person trio. Keys mirror that vocabulary; the
# id column / primary table mirror the entity detail-endpoint registry documented
# in README.md. The `movie_serie` UNION value is intentionally absent — those
# queries project ID_CONTENT + CONTENT_TYPE and are skipped by the guard.
_RESULT_ENTITY_SOURCES = {
    "movie": ("ID_MOVIE", "T_WC_T2S_MOVIE"),
    "serie": ("ID_SERIE", "T_WC_T2S_SERIE"),
    "person": ("ID_PERSON", "T_WC_T2S_PERSON"),
    "collection": ("ID_T2S_COLLECTION", "T_WC_T2S_COLLECTION"),
    "list": ("ID_T2S_LIST", "T_WC_T2S_LIST"),
    "topic": ("ID_TOPIC", "T_WC_T2S_TOPIC"),
    "movement": ("ID_MOVEMENT", "T_WC_T2S_MOVEMENT"),
    "technical": ("ID_TECHNICAL", "T_WC_T2S_TECHNICAL"),
    "group": ("ID_GROUP", "T_WC_T2S_GROUP"),
    "death": ("ID_DEATH", "T_WC_T2S_DEATH"),
    "award": ("ID_AWARD", "T_WC_T2S_AWARD"),
    "nomination": ("ID_NOMINATION", "T_WC_T2S_NOMINATION"),
    "company": ("ID_COMPANY", "T_WC_T2S_COMPANY"),
    "network": ("ID_NETWORK", "T_WC_T2S_NETWORK"),
    "location": ("ID_WIKIDATA", "T_WC_T2S_ITEM"),
    # Genres are a closed-vocabulary reference (T_WC_TMDB_GENRE, legacy lowercase
    # PK `id`). They are listable in their own right ("what are the movie genres?")
    # but are ALSO the most common filter word ("Sci-Fi movies"); the classifier
    # (text2sql.f_classify_result_entity) is what tells the two apart. The guard's
    # id token is ID_GENRE, so the "Genres" Result Columns block MUST project the
    # PK as `id AS ID_GENRE`.
    "genre": ("ID_GENRE", "T_WC_TMDB_GENRE"),
    # Image queries ("Show Zendaya pictures", "Dune posters") return the entity's *_IMAGE
    # rows, NOT the entity card. Guard id = ID_ROW (the image-row PK) -> the Result Columns
    # MUST project ID_ROW; the image path is aliased AS POSTER_PATH so the front renders it.
    "person_image": ("ID_ROW", "T_WC_T2S_PERSON_IMAGE"),
    "movie_image": ("ID_ROW", "T_WC_T2S_MOVIE_IMAGE"),
    "serie_image": ("ID_ROW", "T_WC_T2S_SERIE_IMAGE"),
}

# --- Name/title ambiguity detection (FASTAPI-TEXT2SQL-157) --------------------
# When the generated SQL is *nothing but* an exact-equality match on an entity's
# name/title column(s) against a SINGLE literal and returns >=2 distinct rows, the
# result is a same-name cluster (homonym person, duplicate movie/serie title): the
# user named ONE entity but the database holds several. `compute_name_ambiguity`
# emits a NEUTRAL, DESCRIPTIVE flag stating that fact. It does NOT decide whether a
# client should disambiguate or list — that is *intent*, which is NOT in the SQL
# ("tell me about Dracula" and "list all movies called Dracula" produce the identical
# WHERE, differing only by an incidental ORDER BY). A conversational client
# (voice-agent) reads the flag and asks "which one?"; a plain display client
# (tmdb-front) ignores it. The field is None otherwise, so ignoring clients are
# unaffected.
#
# Detection reads the SQL, not the display titles, because the match can hit any of
# several title columns (a "Le bonheur" row can carry MOVIE_TITLE="Happiness" with the
# French/original title holding the anchor). Strict "=" is guaranteed (never LIKE) by
# data/text_to_sql.md, so equality parsing cannot be bypassed by a fuzzy predicate.
# Extend the map per entity table as needed (columns longest-first for regex safety).
_NAME_AMBIGUITY_ENTITIES = {
    "movie": {
        "columns": ("MOVIE_TITLE_FR", "ORIGINAL_TITLE", "MOVIE_TITLE"),
        "id": "ID_MOVIE", "display": "MOVIE_TITLE", "year": "DAT_RELEASE",
        "imdb": "ID_IMDB",
    },
    "serie": {
        "columns": ("SERIE_TITLE_FR", "ORIGINAL_TITLE", "SERIE_TITLE"),
        "id": "ID_SERIE", "display": "SERIE_TITLE", "year": "DAT_FIRST_AIR",
        "imdb": "ID_IMDB",
    },
    "person": {
        "columns": ("PERSON_NAME",),
        "id": "ID_PERSON", "display": "PERSON_NAME", "year": "BIRTH_YEAR",
    },
}


def _extract_year(value):
    """Best-effort 4-digit year from a DATE / date-string / int; None if not derivable."""
    if value is None:
        return None
    match = re.search(r"\d{4}", str(value))
    return int(match.group(0)) if match else None


def _iso_date(value):
    """Full YYYY-MM-DD from a DATE / date-string / datetime; None if not derivable.

    Used by the name_ambiguity discriminator so two same-year candidates (e.g. The
    Odyssey's two 2026 films) expose distinct dates and a "most recent" pick can
    resolve to a single candidate (year alone reads as an unresolvable tie).
    """
    if value is None:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
    return match.group(0) if match else None


def _where_pure_name_equality_anchor(sql_query, columns):
    """Return the single anchor literal L when the WHERE clause is composed ONLY of
    exact-equality predicates ``col = 'L'`` on the given name/title ``columns`` (all
    sharing the same literal L, joined by OR), with no other predicate, JOIN, or
    subquery. Return None otherwise.

    Robust to arbitrary literal content: each ``col = '...'`` predicate (with '' escaping)
    is captured whole and subtracted; only OR/parentheses/whitespace plus the trailing
    ORDER BY / LIMIT tail may remain. Any residue (AND, another column, a function) → None.
    """
    if not sql_query:
        return None
    sql = sql_query.strip().rstrip(";").strip()
    # Single-table, no subquery: a JOIN or a second SELECT means the user's entity was
    # narrowed or the query is not a plain name lookup.
    if re.search(r"\bJOIN\b", sql, re.I):
        return None
    if len(re.findall(r"\bSELECT\b", sql, re.I)) != 1:
        return None
    where_match = re.search(r"\bWHERE\b", sql, re.I)
    if not where_match:
        return None
    body = sql[where_match.end():]
    col_alt = "|".join(re.escape(c) for c in columns)  # already longest-first
    pred_re = re.compile(
        r"(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:" + col_alt + r")\b\s*=\s*'((?:[^']|'')*)'",
        re.I,
    )
    literals = []

    def _grab(match):
        literals.append(match.group(1))
        return " "

    residue = pred_re.sub(_grab, body)
    if not literals:
        return None
    # Strip the trailing ORDER BY / LIMIT / OFFSET tail (never quoted).
    residue = re.sub(r"\bORDER\s+BY\b.*$", " ", residue, flags=re.I | re.S)
    residue = re.sub(r"\bLIMIT\b.*$", " ", residue, flags=re.I | re.S)
    # A narrowing conjunction disqualifies a pure name cluster.
    if re.search(r"\bAND\b", residue, re.I):
        return None
    # Remove OR connectives, parentheses, separators; anything left → not pure equality.
    residue = re.sub(r"\bOR\b", " ", residue, flags=re.I)
    residue = re.sub(r"[()\s;,]+", "", residue)
    if residue:
        return None
    # All disjuncts must target the SAME literal (the user's single anchor).
    unescaped = {lit.replace("''", "'") for lit in literals}
    if len(unescaped) != 1:
        return None
    return next(iter(unescaped))


def _candidate_chrono_key(candidate):
    """Sort key ordering name_ambiguity candidates oldest -> newest.

    FASTAPI-TEXT2SQL-161. The rows come back in DB order, which is neither chronological
    nor meaningful (The Odyssey returned 1969, 1991, 2016, 2004, 2012, 2026-07-15,
    2026-07-03). That misleads a consumer twice: an agent enumerating the candidates reads
    them out of order, and a *positional* reading of a superlative ("the latest one" = the
    last item) lands on the wrong film. Ordering by date makes position agree with time.

    Uses the full release_date when known, else the year (placed at the start of its year),
    with undated candidates last. Python's sort is stable, so ties keep DB order.
    """
    discriminator = candidate.get("discriminator") or {}
    release_date = discriminator.get("release_date")
    if release_date:
        return (0, str(release_date))
    # movie/serie carry "year"; person carries "birth_year".
    year = discriminator.get("year") or discriminator.get("birth_year")
    if year:
        return (0, f"{int(year):04d}-00-00")
    return (1, "")


def compute_name_ambiguity(sql_query, result_entity, query_results):
    """Neutral name/title-ambiguity flag, or None. See _NAME_AMBIGUITY_ENTITIES.

    Call on page 1 only (the small same-name cluster fits one page). Returns
    ``{entity, anchor, count, candidates:[{id, display, discriminator}]}`` when the
    generated SQL is a pure name/title equality on one literal AND >=2 *distinct*
    candidates remain after collapsing data duplicates (same display + same year);
    None otherwise.
    """
    spec = _NAME_AMBIGUITY_ENTITIES.get((result_entity or "").strip().lower())
    if not spec or not isinstance(query_results, list) or len(query_results) < 2:
        return None
    anchor = _where_pure_name_equality_anchor(sql_query, spec["columns"])
    if anchor is None:
        return None
    candidates, seen_imdb = [], set()
    imdb_col = spec.get("imdb")
    for item in query_results:
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict):
            continue
        display = data.get(spec["display"])
        year = _extract_year(data.get(spec["year"]))
        if (result_entity or "").strip().lower() == "person":
            discriminator = {
                "birth_year": year,
                "death_year": _extract_year(data.get("DEATH_YEAR")),
                "role": data.get("KNOWN_FOR_DEPARTMENT"),
            }
        else:
            # Keep the year for human phrasing ("the 1969 one") and add the full
            # release date as a tiebreaker: two same-year candidates then differ
            # (FASTAPI-TEXT2SQL-160). spec["year"] is DAT_RELEASE / DAT_FIRST_AIR.
            discriminator = {"year": year, "release_date": _iso_date(data.get(spec["year"]))}
        # Collapse ONLY true duplicates: rows sharing a non-empty external id (ID_IMDB)
        # are the same work double-recorded. Never collapse on (title, year) — distinct
        # films share those (two different "Dracula" from 2025: tt31434030 vs tt32448239).
        # Persons carry no ID_IMDB in the projection, so they never collapse.
        imdb = ""
        if imdb_col:
            raw_imdb = data.get(imdb_col)
            imdb = str(raw_imdb).strip() if raw_imdb not in (None, "") else ""
        if imdb and imdb in seen_imdb:
            continue
        if imdb:
            seen_imdb.add(imdb)
        candidates.append({
            "id": data.get(spec["id"]),
            "display": display,
            "discriminator": discriminator,
        })
    if len(candidates) < 2:
        return None
    # Oldest -> newest, so an enumerating agent reads them in order and a positional
    # "the latest one" lands on the actual latest (FASTAPI-TEXT2SQL-161).
    candidates.sort(key=_candidate_chrono_key)
    return {
        "entity": (result_entity or "").strip().lower(),
        "anchor": anchor,
        "count": len(candidates),
        "candidates": candidates,
    }


# --- Bare-identifier fast path (FASTAPI-TEXT2SQL-137) -------------------------
# A question that is JUST a self-identifying id (tt… / nm… / Q…) is answered with
# a direct indexed SQL lookup, skipping the entire LLM pipeline (entity extraction
# + text-to-SQL + resolution): ID_IMDB / ID_WIKIDATA are indexed, so this is a
# sub-millisecond, zero-token lookup. Only prefix-unambiguous ids qualify; bare
# integers (TMDb / Criterion / year / TVDB) and P… (Wikidata property) deliberately
# fall through to the normal pipeline.

# Fallback columns projected per result_entity, mirroring the "Result Columns"
# section of data/text_to_sql.md. At runtime the live (hot-reloaded) prompt is the
# source of truth — see _fast_path_columns() — and this dict is only the safety net
# used when the prompt can't be parsed or a parsed column list fails to execute.
# `location` uses the base T_WC_T2S_ITEM columns because the prompt's Locations list
# includes ID_PROPERTY, which lives on the join table, not on the item table reached
# by a direct ID_WIKIDATA lookup.
_FAST_PATH_SELECT_COLUMNS_FALLBACK = {
    "movie": "ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, ID_IMDB, IMDB_RATING, IMDB_RATING_WEIGHTED, POSTER_PATH, RUNTIME, TAGLINE",
    "serie": "ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, DAT_LAST_AIR, ID_IMDB, IMDB_RATING, IMDB_RATING_WEIGHTED, POSTER_PATH, NUMBER_OF_SEASONS, NUMBER_OF_EPISODES, TAGLINE",
    "person": "ID_PERSON, PERSON_NAME, POPULARITY, KNOWN_FOR_DEPARTMENT, BIRTH_YEAR, DEATH_YEAR, PROFILE_PATH",
    "collection": "ID_T2S_COLLECTION, COLLECTION_NAME, COLLECTION_SOURCE, COLLECTION_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, OVERVIEW, MOVIE_COUNT, SERIE_COUNT, IMDB_RATING",
    "list": "ID_T2S_LIST, LIST_NAME, LIST_SOURCE, LIST_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, OVERVIEW, MOVIE_COUNT, SERIE_COUNT, IMDB_RATING",
    "topic": "ID_TOPIC, TOPIC_NAME, TOPIC_TYPE, TOPIC_SOURCE, LANG, ID_RECORD, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING",
    "movement": "ID_MOVEMENT, MOVEMENT_NAME, MOVEMENT_SOURCE, MOVEMENT_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, OVERVIEW, MOVIE_COUNT, SERIE_COUNT, IMDB_RATING",
    "technical": "ID_TECHNICAL, DESCRIPTION, DESCRIPTION_FR, TECHNICAL_TYPE, OVERVIEW, WIKIPEDIA_IMAGE_PATH, MOVIE_COUNT, IMDB_RATING_WEIGHTED, POPULARITY",
    "group": "ID_GROUP, GROUP_NAME, GROUP_SOURCE, GROUP_TYPE, PROFILE_PATH, WIKIPEDIA_IMAGE_PATH, OVERVIEW, PERSON_COUNT, POPULARITY",
    "death": "ID_DEATH, DEATH_NAME, DEATH_SOURCE, DEATH_TYPE, PROFILE_PATH, WIKIPEDIA_IMAGE_PATH, OVERVIEW, PERSON_COUNT, POPULARITY",
    "award": "ID_AWARD, AWARD_NAME, AWARD_SOURCE, AWARD_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, OVERVIEW, MOVIE_COUNT, SERIE_COUNT, PERSON_COUNT, IMDB_RATING",
    "nomination": "ID_NOMINATION, NOMINATION_NAME, NOMINATION_SOURCE, NOMINATION_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, OVERVIEW, MOVIE_COUNT, SERIE_COUNT, PERSON_COUNT, IMDB_RATING",
    "location": "ID_WIKIDATA, ITEM_LABEL, DESCRIPTION, INSTANCE_OF, WIKIPEDIA_IMAGE_PATH",
    "genre": "id AS ID_GENRE, name AS GENRE_NAME, APPLIES_TO_MOVIE, APPLIES_TO_SERIE",
    "person_image": "ID_ROW, ID_PERSON, TYPE_IMAGE, LANG, IMAGE_PATH AS POSTER_PATH, VOTE_AVERAGE",
    "movie_image": "ID_ROW, ID_MOVIE, TYPE_IMAGE, LANG, IMAGE_PATH AS POSTER_PATH, VOTE_AVERAGE",
    "serie_image": "ID_ROW, ID_SERIE, TYPE_IMAGE, LANG, IMAGE_PATH AS POSTER_PATH, VOTE_AVERAGE",
}

# result_entity precedence when a Q… id could match several T2S tables; first hit
# wins (a Wikidata entity is, in practice, exactly one kind of thing).
_WIKIDATA_FAST_PATH_PRECEDENCE = [
    "movie", "serie", "person", "collection", "list", "topic", "movement",
    "group", "death", "award", "nomination", "technical", "location",
]

# Heading name (in the prompt's "Result Columns" section) -> result_entity.
_RESULT_SECTION_NAME_TO_ENTITY = {
    "persons": "person", "movies": "movie", "series": "serie", "topics": "topic",
    "lists": "list", "collections": "collection", "movements": "movement",
    "technicals": "technical", "groups": "group", "deaths": "death",
    "awards": "award", "nominations": "nomination", "companies": "company",
    "networks": "network", "locations": "location", "genres": "genre",
}

# A "Result Columns" sub-heading, e.g. "#### Movies – return:" (en dash or hyphen).
_RESULT_COLUMNS_HEADING_RE = re.compile(r"^#{2,4}\s*(.+?)\s*[–-]\s*return", re.IGNORECASE)


def _parse_result_columns_from_prompt(template_text):
    """Parse the "Result Columns" section of text_to_sql.md → {result_entity: 'col, col, …'}.

    Makes the bare-id fast path follow the live, hot-reloaded prompt instead of a
    static copy (FASTAPI-TEXT2SQL-137). Returns {} when the section is absent or
    unparseable, so callers fall back to _FAST_PATH_SELECT_COLUMNS_FALLBACK. The
    UNION and image/video sub-sections are ignored (their heading names are not
    entity names and so are absent from _RESULT_SECTION_NAME_TO_ENTITY).
    """
    if not template_text:
        return {}
    sec = re.search(r"^#{2,3}\s*Result Columns\s*$", template_text, re.IGNORECASE | re.MULTILINE)
    if not sec:
        return {}
    lines = template_text[sec.end():].splitlines()
    out = {}
    i = 0
    while i < len(lines):
        hm = _RESULT_COLUMNS_HEADING_RE.match(lines[i].strip())
        if not hm:
            i += 1
            continue
        name = re.sub(r"[^a-z]", "", hm.group(1).lower())
        entity = _RESULT_SECTION_NAME_TO_ENTITY.get(name)
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if entity and j < len(lines):
            cols = lines[j].strip()
            if cols and not cols.startswith("#"):
                out[entity] = cols
        i = j + 1
    return out


# Cache the parse keyed on the prompt-string identity (hot-reload reassigns it).
_fast_path_columns_cache = {"template": None, "map": {}}


def _fast_path_columns(entity):
    """Return the SELECT column list for ``entity``, preferring the live prompt.

    Single source of truth = the hot-reloaded text_to_sql.md "Result Columns"
    section; falls back to _FAST_PATH_SELECT_COLUMNS_FALLBACK per entity. ``location``
    is always taken from the fallback (base T_WC_T2S_ITEM columns) because the
    prompt's Locations list includes the join-only ID_PROPERTY column.
    """
    if entity == "location":
        return _FAST_PATH_SELECT_COLUMNS_FALLBACK["location"]
    tmpl = getattr(t2s, "text2sql_prompt_template", "") or ""
    if _fast_path_columns_cache["template"] is not tmpl:
        _fast_path_columns_cache["template"] = tmpl
        _fast_path_columns_cache["map"] = _parse_result_columns_from_prompt(tmpl)
    return _fast_path_columns_cache["map"].get(entity) or _FAST_PATH_SELECT_COLUMNS_FALLBACK[entity]


_BARE_ID_PATTERNS = {
    "imdb_person": re.compile(r"^(?:imdb\s+)?(nm\d+)$", re.IGNORECASE),
    "imdb_title": re.compile(r"^(?:imdb\s+)?(tt\d+)$", re.IGNORECASE),
    "wikidata": re.compile(r"^(?:wikidata\s+)?(Q\d+)$", re.IGNORECASE),
}


def _detect_bare_id(question):
    """Return ``(kind, normalized_id)`` when the whole question is a bare id, else None.

    ``kind`` is one of ``imdb_person`` / ``imdb_title`` / ``wikidata``. The id is
    normalized to its canonical casing (``tt…`` / ``nm…`` lowercase, ``Q…`` with an
    uppercase Q) so it matches the stored ``ID_IMDB`` / ``ID_WIKIDATA`` values. An
    optional leading keyword (``imdb`` / ``wikidata``) is tolerated.
    """
    q = (question or "").strip()
    if not q:
        return None
    m = _BARE_ID_PATTERNS["imdb_person"].match(q)
    if m:
        return ("imdb_person", m.group(1).lower())
    m = _BARE_ID_PATTERNS["imdb_title"].match(q)
    if m:
        return ("imdb_title", m.group(1).lower())
    m = _BARE_ID_PATTERNS["wikidata"].match(q)
    if m:
        return ("wikidata", "Q" + m.group(1)[1:])
    return None


def _run_bare_id_fast_path(connection, kind, id_value, lngpage, lngrowsperpage):
    """Resolve a bare-id question with a direct indexed SQL lookup (no LLM).

    Returns ``{result_entity, id_column, candidates_checked, sql_query, rows, resolved_via}``.
    ``rows`` holds the raw DB dict rows of the first candidate table that matches
    (precedence order for a Q… id); ``result_entity`` is ``""`` when nothing matched.
    A ``tt…`` id that is actually a season/episode IMDb id resolves to its parent
    series (``resolved_via`` = ``"season"`` / ``"episode"``). Columns come from the
    live prompt via :func:`_fast_path_columns`, retrying with the static fallback if a
    parsed list fails to execute, so one bad table never aborts the scan. The id is
    parameter-bound; ``sql_query`` is a display string with the regex-validated id
    inlined for the response trace.
    """
    limit = lngrowsperpage
    offset = (lngpage - 1) * lngrowsperpage
    checked = []

    with connection.cursor() as cursor:
        def _lookup(entity, table, id_column, filter_value):
            """Project one entity; prefer live-prompt columns, fall back on error. Returns (rows, display_sql)."""
            tried = []
            for columns in (_fast_path_columns(entity), _FAST_PATH_SELECT_COLUMNS_FALLBACK[entity]):
                if columns in tried:
                    continue
                tried.append(columns)
                try:
                    cursor.execute(
                        f"SELECT {columns} FROM {table} WHERE {id_column} = %s LIMIT %s OFFSET %s",
                        (filter_value, limit, offset),
                    )
                    rows = list(cursor.fetchall())
                except Exception as exc:
                    print(f"Bare-id fast path: lookup on {table} failed: {exc}")
                    continue
                display = f"SELECT {columns} FROM {table} WHERE {id_column} = '{filter_value}' LIMIT {limit} OFFSET {offset}"
                return rows, display
            return None, None

        if kind == "imdb_person":
            id_column = "ID_IMDB"
            candidates = [("person", "T_WC_T2S_PERSON")]
        elif kind == "imdb_title":
            id_column = "ID_IMDB"
            candidates = [("movie", "T_WC_T2S_MOVIE"), ("serie", "T_WC_T2S_SERIE")]
        else:  # wikidata
            id_column = "ID_WIKIDATA"
            candidates = [(e, _RESULT_ENTITY_SOURCES[e][1]) for e in _WIKIDATA_FAST_PATH_PRECEDENCE]

        for entity, table in candidates:
            checked.append(entity)
            rows, display = _lookup(entity, table, id_column, id_value)
            if rows:
                return {
                    "result_entity": entity, "id_column": id_column,
                    "candidates_checked": checked, "sql_query": display,
                    "rows": rows, "resolved_via": None,
                }

        # A tt… that is actually a season/episode IMDb id: resolve to its parent
        # series and return the series fiche (seasons/episodes have ID_IMDB + ID_SERIE
        # but no result_entity of their own).
        if kind == "imdb_title":
            for src_table, src_label in (("T_WC_TMDB_SEASON", "season"), ("T_WC_TMDB_EPISODE", "episode")):
                checked.append(src_label)
                try:
                    cursor.execute(
                        f"SELECT ID_SERIE FROM {src_table} WHERE ID_IMDB = %s LIMIT 1",
                        (id_value,),
                    )
                    parent = cursor.fetchone()
                except Exception as exc:
                    print(f"Bare-id fast path: {src_table} lookup failed: {exc}")
                    parent = None
                if parent and parent.get("ID_SERIE"):
                    rows, display = _lookup("serie", "T_WC_T2S_SERIE", "ID_SERIE", parent["ID_SERIE"])
                    if rows:
                        return {
                            "result_entity": "serie", "id_column": "ID_IMDB",
                            "candidates_checked": checked, "sql_query": display,
                            "rows": rows, "resolved_via": src_label,
                        }

    return {
        "result_entity": "", "id_column": id_column,
        "candidates_checked": checked, "sql_query": "",
        "rows": [], "resolved_via": None,
    }


def _fetch_localized_main_image_paths(cursor, image_table, id_column, type_image, id_values, ui_language):
    """Return ``{id_value: image_path}`` for each id's main localized image.

    Runs one batched query against ``image_table`` and keeps, per id, the lowest
    ``DISPLAY_ORDER`` row whose ``LANG`` matches ``ui_language`` (mirroring how
    ``apply_localized_main_image`` picks the main image from an ordered array). Ids
    with no localized image are simply absent from the returned mapping. The table /
    column identifiers are trusted internal constants (interpolated like the other DB
    helpers); the ids and filter values are passed as bound parameters.
    """
    ids = [v for v in dict.fromkeys(id_values) if v is not None]
    if not ids:
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""SELECT {id_column} AS ID_KEY, IMAGE_PATH, DISPLAY_ORDER
            FROM {image_table}
            WHERE {id_column} IN ({placeholders}) AND TYPE_IMAGE = %s AND LANG = %s
            ORDER BY {id_column}, DISPLAY_ORDER ASC""",
        (*ids, type_image, ui_language),
    )
    paths = {}
    for row in cursor.fetchall():
        key = row.get("ID_KEY")
        if key in paths:
            continue  # first row per id is the lowest DISPLAY_ORDER (main) image
        image_path = row.get("IMAGE_PATH")
        if image_path is not None and (not isinstance(image_path, str) or image_path.strip() != ""):
            paths[key] = image_path
    return paths


def _overwrite_localized_field(data: dict, key: str, value) -> None:
    """Overwrite an existing search-row field with a localized value (English fallback per field).

    Rewrites ``data[key]`` only when the key is already present (never adds a key, so the
    result shape stays identical to the English contract) and the localized ``value`` is
    non-empty, applying the same ``html.unescape`` the search assembly applies to strings.
    """
    if key not in data or value is None:
        return
    if isinstance(value, str):
        if value.strip() == "":
            return
        value = html.unescape(value)
    data[key] = value


def _localize_search_rows(cursor, rows_by_id, ui_language, base_table, lang_table, image_table, id_column, title_column) -> None:
    """Localize one entity type's search rows in place: title + tagline (one join) + poster.

    ``rows_by_id`` maps an id to the list of ``(data, title_key)`` search rows carrying it.
    Two batched lookups per type: the localized title (``title_column`` on ``base_table``)
    and tagline (``lang_table``) in a single LEFT JOIN, then the main localized poster via
    ``_fetch_localized_main_image_paths``. Only fields already present in a row are
    overwritten. Table/column names are trusted internal constants (interpolated like the
    other DB helpers); ids and language are bound as parameters.
    """
    ids = [v for v in rows_by_id if v is not None]
    if not ids:
        return
    placeholders = ",".join(["%s"] * len(ids))
    title_fr, tagline_fr = {}, {}
    cursor.execute(
        f"""SELECT b.{id_column} AS ID_KEY, b.{title_column} AS TITLE_FR, l.TAGLINE AS TAGLINE_FR
            FROM {base_table} b
            LEFT JOIN {lang_table} l ON l.{id_column} = b.{id_column} AND l.LANG = %s
            WHERE b.{id_column} IN ({placeholders})""",
        (ui_language, *ids),
    )
    for row in cursor.fetchall():
        title_fr[row.get("ID_KEY")] = row.get("TITLE_FR")
        tagline_fr[row.get("ID_KEY")] = row.get("TAGLINE_FR")
    poster_fr = _fetch_localized_main_image_paths(cursor, image_table, id_column, "poster", ids, ui_language)
    for id_value, rows in rows_by_id.items():
        for data, title_key in rows:
            _overwrite_localized_field(data, title_key, title_fr.get(id_value))
            _overwrite_localized_field(data, "TAGLINE", tagline_fr.get(id_value))
            _overwrite_localized_field(data, "POSTER_PATH", poster_fr.get(id_value))


def localize_search_results(query_results, ui_language: str, conn) -> None:
    """Localize the movie/serie rows of a /search result set in place, for non-default languages.

    The generated SQL projects English columns (title / tagline / poster) whatever the
    ui_language, and the search path applies no other localization. Here each movie/serie
    row is rehydrated BY ID from its localized siblings (``MOVIE_TITLE_FR`` / ``SERIE_TITLE_FR``
    on the base table, ``TAGLINE`` from ``T_WC_T2S_*_LANG``, the main FR poster from
    ``T_WC_T2S_*_IMAGE``) WITHOUT touching the prompt or the generated SQL. Rows are typed by
    the id column the search contract guarantees: ``ID_MOVIE`` / ``ID_SERIE`` for a
    single-type result, or ``ID_CONTENT`` + ``CONTENT_TYPE`` ('movie'|'serie') with
    ``CONTENT_TITLE`` for a movie+serie UNION. Every other row kind (person, topic, image
    rows, scalar answers, ...) is left untouched. Only fields already present are overwritten
    (shape unchanged), only with a non-empty value. The English default path is a no-op, and a
    lookup failure degrades silently to the English rows. Mutates the rows in place.
    """
    if ui_language == DEFAULT_UI_LANGUAGE or not query_results:
        return
    movie_rows, serie_rows = {}, {}
    for item in query_results:
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict):
            continue
        content_type = str(data.get("CONTENT_TYPE") or "").strip().lower()
        if "ID_CONTENT" in data and content_type in ("movie", "serie"):
            entity_type, id_value, title_key = content_type, data.get("ID_CONTENT"), "CONTENT_TITLE"
        elif "ID_MOVIE" in data:
            entity_type, id_value, title_key = "movie", data.get("ID_MOVIE"), "MOVIE_TITLE"
        elif "ID_SERIE" in data:
            entity_type, id_value, title_key = "serie", data.get("ID_SERIE"), "SERIE_TITLE"
        else:
            continue
        if id_value is None:
            continue
        (movie_rows if entity_type == "movie" else serie_rows).setdefault(id_value, []).append((data, title_key))
    if not movie_rows and not serie_rows:
        return
    try:
        with conn.cursor() as cursor:
            _localize_search_rows(cursor, movie_rows, ui_language, "T_WC_T2S_MOVIE", "T_WC_T2S_MOVIE_LANG", "T_WC_T2S_MOVIE_IMAGE", "ID_MOVIE", "MOVIE_TITLE_FR")
            _localize_search_rows(cursor, serie_rows, ui_language, "T_WC_T2S_SERIE", "T_WC_T2S_SERIE_LANG", "T_WC_T2S_SERIE_IMAGE", "ID_SERIE", "SERIE_TITLE_FR")
    except Exception:
        # Localization is an enhancement over the English rows already assembled; a lookup
        # failure (e.g. a _LANG table missing on a fresh environment) must never break
        # /search. Degrade silently to the English result.
        return


def apply_localized_related_images(conn, grouped_rows: dict, ui_language: str) -> None:
    """Localize the main picture path of nested related rows for non-default languages.

    ``grouped_rows`` maps an entity kind in :data:`_RELATED_IMAGE_SOURCES`
    ("movie" / "serie" / "person" / "season") to a list of row collections; each
    collection is either a list of related-entity dicts (e.g. a ``cast`` array) or a
    single dict (a navigation stub such as the parent ``series``). For each kind, all
    ids are gathered and a single batched query fetches the main image in
    ``ui_language`` per id; every row's canonical path field is overwritten when a
    localized image exists, keeping the canonical (default-language) path as a
    fallback otherwise. Mutates the rows in place. No-op for the default language.
    """
    if ui_language == DEFAULT_UI_LANGUAGE:
        return
    with conn.cursor() as cursor:
        for kind, collections in grouped_rows.items():
            image_table, id_column, type_image, path_key = _RELATED_IMAGE_SOURCES[kind]
            rows = []
            for collection in collections:
                if isinstance(collection, dict):
                    rows.append(collection)
                elif collection:
                    rows.extend(row for row in collection if isinstance(row, dict))
            if not rows:
                continue
            id_to_path = _fetch_localized_main_image_paths(
                cursor, image_table, id_column, type_image,
                [row.get(id_column) for row in rows], ui_language,
            )
            if not id_to_path:
                continue
            for row in rows:
                image_path = id_to_path.get(row.get(id_column))
                if image_path is not None:
                    row[path_key] = image_path


def localize_response(obj, ui_language: str):
    """Recursively localize an entity response, collapsing ``_FR`` columns everywhere.

    Walks the response tree applying :func:`localize_row` to every dict, so both the
    top-level entity and all nested related-entity rows (lists of dicts, navigation
    stubs) are localized in a single pass. Lists of scalars and language-tagged
    sub-resources (videos, images, Wikipedia rows) carry no ``_FR`` keys and are
    left untouched. Mutates in place and returns the same object.
    """
    if isinstance(obj, dict):
        localize_row(obj, ui_language)
        for value in obj.values():
            localize_response(value, ui_language)
    elif isinstance(obj, list):
        for item in obj:
            localize_response(item, ui_language)
    return obj


# ---------------------------------------------------------------------------
# Embedded-collection pagination
# ---------------------------------------------------------------------------
# Entity detail endpoints embed related-entity lists (cast, crew, movies, ...)
# that can grow very large (a prolific person has thousands of credits). Each such
# list is paginated: a bare GET returns every collection capped to its first page
# plus a top-level ``pagination`` block carrying per-collection totals; passing
# ``?collection=<name>&page=N&rows_per_page=M`` returns a lean payload with just
# that collection's requested page (other collections and the base entity fields
# are omitted to save bandwidth). Image arrays, videos, Wikipedia arrays, and
# scalar lists (genres, production countries, spoken languages) are NOT paginated.
COLLECTION_ROWS_PER_PAGE_DEFAULT = 50
COLLECTION_ROWS_PER_PAGE_MAX = 200


def _collection_page_params(page, rows_per_page):
    """Clamp paging inputs and return ``(page, rows_per_page, limit, offset)``."""
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1
    try:
        rpp = int(rows_per_page)
    except (TypeError, ValueError):
        rpp = COLLECTION_ROWS_PER_PAGE_DEFAULT
    if rpp < 1:
        rpp = COLLECTION_ROWS_PER_PAGE_DEFAULT
    if rpp > COLLECTION_ROWS_PER_PAGE_MAX:
        rpp = COLLECTION_ROWS_PER_PAGE_MAX
    return page, rpp, rpp, (page - 1) * rpp


def _paginate_collection(cursor, sql, params, page, rows_per_page):
    """Execute a collection query with LIMIT/OFFSET and return ``(rows, meta)``.

    ``sql`` must already select ``COUNT(*) OVER() AS _TOTAL_COUNT`` alongside its row
    columns and must carry a deterministic ORDER BY (with a unique tiebreaker) so
    paging is stable; it must NOT contain its own LIMIT/OFFSET or a trailing
    semicolon. The window total is popped out of every row into the returned
    metadata ``{total, page, rows_per_page, returned}``.
    """
    page, rpp, limit, offset = _collection_page_params(page, rows_per_page)
    cursor.execute(sql + "\nLIMIT %s OFFSET %s", (*params, limit, offset))
    rows = list(cursor.fetchall())
    total = int(rows[0]["_TOTAL_COUNT"]) if rows else 0
    for row in rows:
        row.pop("_TOTAL_COUNT", None)
    return rows, {"total": total, "page": page, "rows_per_page": rpp, "returned": len(rows)}


def _run_collections(cursor, pcollections, collection, page, rows_per_page):
    """Drive an entity endpoint's registry of paginated collections.

    ``pcollections`` maps a collection name to ``(sql, params, image_kind)``. When
    ``collection`` is None (untargeted) every collection is fetched at page 1 using
    the requested ``rows_per_page``; otherwise only the named collection is fetched
    at the requested ``page``. Returns ``(data, pagination, kinds)`` mapping name ->
    rows, name -> meta, and name -> image_kind respectively. Raises HTTP 400 on an
    unknown target name.
    """
    if collection is not None:
        if collection not in pcollections:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown collection '{collection}'. Valid collections: {sorted(pcollections)}",
            )
        sql, params, kind = pcollections[collection]
        rows, meta = _paginate_collection(cursor, sql, params, page, rows_per_page)
        return {collection: rows}, {collection: meta}, {collection: kind}
    data, pagination, kinds = {}, {}, {}
    for name, (sql, params, kind) in pcollections.items():
        rows, meta = _paginate_collection(cursor, sql, params, 1, rows_per_page)
        data[name] = rows
        pagination[name] = meta
        kinds[name] = kind
    return data, pagination, kinds


def _localized_image_groups(data, kinds):
    """Group fetched collection rows by image kind for apply_localized_related_images."""
    groups = {}
    for name, kind in kinds.items():
        if kind and data.get(name):
            groups.setdefault(kind, []).append(data[name])
    return groups


def _targeted_collection_response(conn, ident, collection, data, pagination, kinds, ui_language):
    """Assemble and localize the lean payload for a targeted single-collection request."""
    result = {**ident, "collection": collection, collection: data[collection], "pagination": pagination}
    apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
    localize_response(result, ui_language)
    return result


class TextExpr(BaseModel):
    text: str
    sql_query: str = ""

class Text2SQLRequest(BaseModel):
    question: Optional[str] = None
    question_hashed: Optional[str] = None  # For pagination/disambiguation
    page: Optional[int] = 1
    rows_per_page: Optional[int] = 50
    retrieve_from_cache: bool = True
    store_to_cache: bool = True
    llm_model_entity_extraction: Optional[str] = "default"
    llm_model_text2sql: Optional[str] = "default"
    llm_model_complex: Optional[str] = "default"
    complex_question_processing: bool = False
    complex_question_already_resolved: bool = False
    ui_language: Optional[str] = "en"

    @field_validator("ui_language", mode="before")
    @classmethod
    def _normalize_ui_language(cls, v):
        """Normalize ui_language to a supported code, falling back to "en".

        Runs for any explicitly provided value (including null); when the field
        is omitted the default "en" is used as-is. After validation
        ``ui_language`` is always a supported, non-null code, so downstream code
        can use it directly without an ``or "en"`` guard.
        """
        return normalize_ui_language(v)

    @model_validator(mode='after')
    def validate_question_or_hashed(self):
        """Ensure that each request provides either the original question or its hash."""
        if not self.question and not self.question_hashed:
            raise ValueError('Either question or question_hashed must be provided')
        return self

class TextMessage(BaseModel):
    position: int
    text: str

class Text2SQLResponse(BaseModel):
    question: str
    question_hashed: Optional[str] = None
    sql_query: str
    sql_query_anonymized: str = ""
    justification: str
    justification_anonymized: str = ""
    answer: str = ""
    answer_anonymized: str = ""
    result_entity: str = ""
    # Neutral same-name-cluster flag (FASTAPI-TEXT2SQL-157); None unless the SQL is a
    # pure name/title equality on one literal returning >=2 distinct rows. Clients
    # decide what to do with it (voice-agent disambiguates; tmdb-front ignores it).
    name_ambiguity: Optional[dict] = None
    error: str
    error_code: Optional[str] = None
    is_retryable: bool = False
    retry_after_seconds: Optional[float] = None
    provider: Optional[str] = None
    entity_extraction: Optional[dict] = None
    question_anonymized: Optional[str] = None
    entity_extraction_processing_time: float
    text2sql_processing_time: float
    embeddings_processing_time: float
    embeddings_cache_search_time: float = 0.0
    query_execution_time: float
    total_processing_time: float
    page: Optional[int] = None
    llm_defined_limit: Optional[int] = None
    llm_defined_offset: Optional[int] = None
    limit: Optional[int] = None
    offset: Optional[int] = None
    rows_per_page: Optional[int] = None
    cached_exact_question: bool = False
    cached_anonymized_question: bool = False
    cached_anonymized_question_embedding: bool = False
    ambiguous_question_for_text2sql: bool = False
    llm_model_entity_extraction: str
    llm_model_text2sql: str
    llm_model_complex: str
    complex_model_used: bool = False
    ui_language: str = "en"
    api_version: str
    messages: List[TextMessage] = []
    result: List[dict] = []  # Array of records with index and data

class ResultItem(BaseModel):
    sql_query: str

@app.get("/")
async def f_hello_world(api_key: str = Depends(get_api_key)):
    """Hello world endpoint for API health check.
    
    Returns a simple greeting message with the universal answer (42).
    Requires valid API key authentication.
    
    Args:
        api_key (str): Valid API key for authentication (injected by dependency)
        
    Returns:
        dict: JSON response containing greeting message
        
    Example:
        GET / with X-API-Key header
        Returns: {"message": "hello world! The universal answer is 42"}
    """
    global answer
    result = {"message": "hello world! The universal answer is " + str(answer), "bktrees_ready": entity.BKTREES_READY}
    logs.log_usage("hello", result, strapiversion)
    return result

@app.post("/search/text2sql", response_model=Text2SQLResponse)
async def search_text2sql(request: Text2SQLRequest, api_key: str = Depends(get_api_key)):
    """Convert a natural language question about cinema or TV into SQL, execute it, and return the result set.

    Covers the full entertainment database: movies, TV series, persons (actors, directors,
    writers, crew), production companies, TV networks, topics (themes, recurring-character
    collections), curated lists (rankings, canons), collections (trilogies, sagas, universes,
    franchises), film movements, person groups, causes of death, awards, nominations, and
    locations (narrative or filming, via Wikidata).

    Processing pipeline:
    1. Normalize and sanitize the input question.
    2. Extract and anonymize named entities using an LLM, replacing them with typed
       placeholders such as {{Person_name1}}, {{Movie_title1}}, {{Topic_name1}} etc.
    3. Look up the SQL cache for the exact question, then for the anonymized pattern.
    4. Optionally search the ChromaDB vector embeddings cache for a semantically
       similar anonymized question (disabled by default).
    5. If no cache hit, generate SQL via an LLM using the anonymized question and the
       full MariaDB schema prompt.
    6. Resolve entity placeholders to actual database IDs or names via ChromaDB
       embeddings or RapidFuzz lexical matching (strategy driven by entity_resolution.json).
    7. Execute the resolved SQL query against MariaDB with LIMIT/OFFSET pagination.
    8. If SQL generation fails or execution returns 0 rows on page 1, optionally retry
       once by simplifying the original question through a stronger LLM model.
    9. Cache the question-SQL pair (SQL cache + embeddings cache) for future requests.

    Args:
        request (Text2SQLRequest): Request body:
            - question (str, optional): Natural language question. Either question or
              question_hashed must be provided.
            - question_hashed (str, optional): SHA-256 hash of a cached question; used
              for paginating a previously executed result without re-running the LLM.
            - page (int, default 1): Page number for paginated results.
            - rows_per_page (int, default 50): Number of rows per page.
            - retrieve_from_cache (bool, default True): Whether to consult the SQL cache.
            - store_to_cache (bool, default True): Whether to write results to the SQL cache.
            - llm_model_entity_extraction (str, default "default"): LLM for entity
              extraction. "default" resolves to gpt-4o.
            - llm_model_text2sql (str, default "default"): LLM for SQL generation.
              "default" resolves to gpt-4o.
            - llm_model_complex (str, default "default"): Stronger LLM used for
              complex-question escalation and one-time retry. "default" resolves to gpt-4o.
        api_key (str): Valid API key injected via X-API-Key header.

    Returns:
        Text2SQLResponse:
            - question: Normalised input question.
            - question_hashed: SHA-256 hash of the question.
            - sql_query: Final executable SQL (entity placeholders resolved to real values).
            - sql_query_anonymized: SQL with entity placeholders before resolution.
            - justification: LLM explanation of the generated query.
            - error: Non-empty if the question could not produce a valid SQL query.
            - name_ambiguity (dict, optional): Neutral same-name-cluster flag — present
              only when the SQL is a pure name/title equality on one literal returning
              >=2 distinct rows (homonym person / duplicate title). Descriptive, not an
              instruction; clients decide (voice-agent disambiguates, tmdb-front ignores).
              See README "Response Fields" for the shape. FASTAPI-TEXT2SQL-157.
            - entity_extraction (dict): Extracted entity names keyed by placeholder.
            - question_anonymized: Question with entity values replaced by placeholders.
            - result (list): Paginated rows, each as {"index": int, "data": dict}.
              Result columns depend on entity type — see data/text_to_sql.md Result Columns.
            - page, limit, offset, rows_per_page: Pagination metadata.
            - llm_defined_limit, llm_defined_offset: LIMIT/OFFSET originally in LLM output.
            - cached_exact_question, cached_anonymized_question,
              cached_anonymized_question_embedding: Cache hit indicators.
            - entity_extraction_processing_time, text2sql_processing_time,
              embeddings_processing_time, query_execution_time,
              total_processing_time: Latency breakdown in seconds.
            - ambiguous_question_for_text2sql: True when the question was too vague to
              produce a SQL query.
            - messages (list): Ordered processing-step messages for debugging.
            - llm_model_entity_extraction, llm_model_text2sql, llm_model_complex.
            - api_version: Running API version string.

    Raises:
        ValueError: If neither question nor question_hashed is provided.
        HTTPException 401: If the API key is invalid.
    """
    total_start_time = time.time()
    
    # Initialize messages list and position counter
    messages = []
    position_counter = 1

    # Start a fresh prompt-cache observation buffer for this request. Only the
    # outer call resets it; the complex-question retry re-enters this endpoint in
    # the same context and must share the buffer so its LLM calls are captured too.
    if not getattr(request, "complex_question_already_resolved", False):
        t2s.reset_prompt_cache_events()

    # Strip whitespace and carriage return characters from question if provided
    if request.question:
        original_question = request.question
        # Strip all leading/trailing whitespace (including \n, \r, spaces, tabs)
        request.question = request.question.strip()
        # Remove any remaining internal carriage returns and normalize newlines to spaces
        #request.question = request.question.replace('\t', ' ')  # Normalize tabs
        #request.question = request.question.replace('\r', '').replace('\n', ' ').strip()
        #request.question = request.question.replace('\\r', '').replace('\\n', ' ').strip()
        request.question = request.question.replace('  ', ' ')  # Normalize multiple spaces
        request.question = request.question.replace('&#039;', "'").replace('’', "'")
        if original_question != request.question:
            messages.append(TextMessage(
                position=position_counter, 
                text="Normalized characters in input question."
            ))
            position_counter += 1
    
    lngpage = request.page or 1
    lngrowsperpage = request.rows_per_page or lngrowsperpagedefault

    # Open database connection once at the start
    connection = get_db_connection()
    print("Database connection established")
    
    # Initialize variables
    cached_exact_question = False
    cached_anonymized_question = False
    cached_anonymized_question_embedding = False
    cached_anonymized_question_embedding = False
    sql_query = None
    sql_query_anonymized = None
    justification = None
    justification_anonymized = None
    answer = None
    answer_anonymized = None
    result_entity = ""
    error_text2sql = None
    llm_defined_limit = None
    llm_defined_offset = None
    limit = None
    offset = None
    input_text = None
    input_text_anonymized = None
    entity_extraction = None
    entity_extraction_processing_time = 0.0
    text2sql_processing_time = 0.0
    embeddings_processing_time = 0.0
    embeddings_cache_search_time = 0.0
    query_execution_time = 0.0
    total_processing_time = 0.0
    sql_execution_failed = False
    ambiguous_question_for_text2sql = 0
    complex_model_used = False
    strentityextractionmodel = entity.strentityextractionmodeldefault
    if request.llm_model_entity_extraction and request.llm_model_entity_extraction != "default":
        strentityextractionmodel = request.llm_model_entity_extraction
    strtext2sqlmodel = t2s.strtext2sqlmodeldefault
    if request.llm_model_text2sql and request.llm_model_text2sql != "default":
        strtext2sqlmodel = request.llm_model_text2sql
    strcomplexquestionmodel = t2s.strcomplexquestionmodeldefault
    if request.llm_model_complex and request.llm_model_complex != "default":
        strcomplexquestionmodel = request.llm_model_complex

    print("/search/text2sql LLM selection:")
    print("- Entity extraction model:", strentityextractionmodel)
    print("- Text2SQL model:", strtext2sqlmodel)
    print("- Complex question model:", strcomplexquestionmodel)

    # --- Bare-identifier fast path (FASTAPI-TEXT2SQL-137) ----------------------
    # When the whole question is just a self-identifying id (tt…/nm…/Q…), answer it
    # with a direct indexed SQL lookup and skip the entire LLM pipeline (entity
    # extraction + text-to-SQL + resolution). Same response shape as text2sql:
    # result_entity is set, the entity's Result Columns are projected, and sql_query
    # + messages show the direct lookup. Skipped on the complex-question retry
    # re-entry (its resolved question is never a bare id).
    _bare_id = _detect_bare_id(request.question) if request.question else None
    if _bare_id is not None and not getattr(request, "complex_question_already_resolved", False):
        _kind, _id_value = _bare_id
        _kind_label = {"imdb_title": "IMDb title", "imdb_person": "IMDb person", "wikidata": "Wikidata"}[_kind]
        input_text = request.question
        messages.append(TextMessage(
            position=position_counter,
            text=f"Bare-identifier fast path: detected {_kind_label} id '{_id_value}'; resolving with a direct indexed SQL lookup (no LLM)."
        ))
        position_counter += 1

        _fp_start = time.time()
        _fp = _run_bare_id_fast_path(connection, _kind, _id_value, lngpage, lngrowsperpage)
        query_execution_time = time.time() - _fp_start
        result_entity_fp = _fp["result_entity"]
        resolved_via = _fp.get("resolved_via")
        sql_query = _fp["sql_query"]
        sql_query_anonymized = _fp["sql_query"]

        fast_path_results = []
        for index, record in enumerate(_fp["rows"]):
            fast_path_results.append({
                "index": index,
                "data": {k: html.unescape(v) if isinstance(v, str) else v for k, v in record.items()}
            })

        if result_entity_fp:
            if resolved_via:
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Identifier '{_id_value}' matched a {resolved_via}; returning its parent series."
                ))
                position_counter += 1
            if sql_query:
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing SQL query: {sql_query}"
                ))
                position_counter += 1
            messages.append(TextMessage(
                position=position_counter,
                text=f"Direct lookup matched result_entity '{result_entity_fp}' ({len(fast_path_results)} row(s))."
            ))
            position_counter += 1
            if resolved_via:
                justification = f"Direct indexed lookup: identifier '{_id_value}' is a {resolved_via} IMDb id; returning its parent serie; no LLM call."
            else:
                justification = f"Direct indexed lookup by {_fp['id_column']} = '{_id_value}' on the {result_entity_fp} table; no LLM call."
            if request.ui_language == "fr":
                answer = f"Voici l'entité ({result_entity_fp}) correspondant à l'identifiant {_id_value}."
            else:
                answer = f"Here is the {result_entity_fp} matching identifier {_id_value}."
        else:
            messages.append(TextMessage(
                position=position_counter,
                text=f"No entity found for identifier '{_id_value}' in the candidate tables: {', '.join(_fp['candidates_checked'])}."
            ))
            position_counter += 1
            justification = f"Direct indexed lookup by {_fp['id_column']} = '{_id_value}' found no matching entity."
            if request.ui_language == "fr":
                answer = f"Aucune entité ne correspond à l'identifiant {_id_value}."
            else:
                answer = f"No entity matches identifier {_id_value}."

        justification_anonymized = justification
        answer_anonymized = answer

        # FASTAPI-TEXT2SQL-162 (post-process variant): localize movie/serie rows by
        # ui_language before closing the connection. No-op for English.
        localize_search_results(fast_path_results, normalize_ui_language(request.ui_language), connection)
        try:
            connection.close()
        except Exception:
            pass

        fast_path_question_hash = hashlib.sha256(request.question.encode('utf-8')).hexdigest()
        total_processing_time = time.time() - total_start_time

        fast_path_response = Text2SQLResponse(
            question=input_text,
            question_hashed=fast_path_question_hash,
            sql_query=sql_query or "",
            sql_query_anonymized=sql_query_anonymized or "",
            justification=justification,
            justification_anonymized=justification_anonymized,
            answer=answer,
            answer_anonymized=answer_anonymized,
            result_entity=result_entity_fp or "",
            error="",
            entity_extraction=None,
            question_anonymized=None,
            entity_extraction_processing_time=0.0,
            text2sql_processing_time=0.0,
            embeddings_processing_time=0.0,
            embeddings_cache_search_time=0.0,
            query_execution_time=query_execution_time,
            total_processing_time=total_processing_time,
            page=lngpage,
            llm_defined_limit=None,
            llm_defined_offset=None,
            limit=lngrowsperpage,
            offset=(lngpage - 1) * lngrowsperpage,
            rows_per_page=lngrowsperpage,
            cached_exact_question=False,
            cached_anonymized_question=False,
            cached_anonymized_question_embedding=False,
            ambiguous_question_for_text2sql=False,
            llm_model_entity_extraction=strentityextractionmodel,
            llm_model_text2sql=strtext2sqlmodel,
            llm_model_complex=strcomplexquestionmodel,
            complex_model_used=False,
            ui_language=request.ui_language,
            api_version=strapiversion,
            result=fast_path_results,
            messages=messages,
        )
        logs.log_usage(
            "text2sql_post",
            {"request": request.model_dump(), "response": fast_path_response.model_dump()},
            strapiversion,
        )
        return fast_path_response
    # --- end bare-identifier fast path -----------------------------------------

    # Try to retrieve user question from cache if requested
    if request.retrieve_from_cache:
        messages.append(TextMessage(
            position=position_counter, 
            text="Attempting to retrieve exact question from cache."
        ))
        position_counter += 1
        cache_result_exact = None

        if request.question_hashed:
            messages.append(TextMessage(
                position=position_counter, 
                text="Searching cache by question hash."
            ))
            position_counter += 1
            cache_result_exact = sql_cache.search_sql_cache_by_question_hash(
                connection,
                request.question_hashed,
                strapiversionformatted,
                ui_language=request.ui_language,
            )
            if not cache_result_exact.get("found"):
                print("Exact question hash not found in the SQL cache")
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Exact question hash not found in cache."
                ))
                position_counter += 1

        if (not cache_result_exact or not cache_result_exact.get("found")) and request.question:
            messages.append(TextMessage(
                position=position_counter, 
                text="Searching cache by question text."
            ))
            position_counter += 1
            cache_result_exact = sql_cache.search_sql_cache_by_question_text(
                connection,
                request.question,
                strapiversionformatted,
                ui_language=request.ui_language,
            )
            if not cache_result_exact.get("found"):
                print("Exact question not found in the SQL cache")
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Exact question not found in cache."
                ))
                position_counter += 1

        if cache_result_exact and cache_result_exact.get("found"):
            print("Found exact question in the SQL cache")
            cached_exact_question = True
            messages.append(TextMessage(
                position=position_counter, 
                text="Exact question cache hit used for SQL query."
            ))
            position_counter += 1
            input_text = cache_result_exact["question"]
            input_text = cache_result_exact["question"]
            sql_query = cache_result_exact["sql_query"]
            sql_query_anonymized = cache_result_exact["sql_query_raw"]
            justification = cache_result_exact.get("justification", "")
            answer = cache_result_exact.get("answer", "")
            result_entity = cache_result_exact.get("result_entity", "")
    else:
        messages.append(TextMessage(
            position=position_counter, 
            text="Cache retrieval disabled; proceeding with full processing."
        ))
        position_counter += 1
    
    # If the exact question was not found in the exact cache, proceed to entity extraction and anonymization
    if not cached_exact_question:
        if request.question:
            messages.append(TextMessage(
                position=position_counter, 
                text="Using provided question text for processing."
            ))
            position_counter += 1
            input_text = request.question
        elif request.question_hashed:
            # A hash that misses the cache is an EXPECTED outcome, not a server error.
            # Ambiguous/empty questions return a question_hashed but never store SQL,
            # and the cache is version-scoped + Blue/Green, so a hash a client still
            # holds can legitimately vanish across a version bump or colour switch.
            # Degrade gracefully (handled HTTP 200 with error_code "cache_miss")
            # instead of raising an uncaught ValueError that FastAPI turns into a
            # generic HTTP 500. Clients should resend the original `question` text so
            # the text-fallback branch above fires. See FASTAPI-TEXT2SQL-135.
            print("question_hashed provided but not found in the SQL cache and no original question provided; returning handled cache-miss response")
            messages.append(TextMessage(
                position=position_counter,
                text="Provided question_hashed was not found in the cache and no original question was supplied; returning a handled cache-miss response."
            ))
            position_counter += 1
            connection.close()
            total_processing_time = time.time() - total_start_time
            cache_miss_response = Text2SQLResponse(
                question="",
                question_hashed=request.question_hashed,
                sql_query="",
                justification="",
                answer="",
                error="No cached entry was found for the provided question_hashed and no original question text was supplied. Resend the request including the original question.",
                error_code="cache_miss",
                is_retryable=False,
                entity_extraction_processing_time=0.0,
                text2sql_processing_time=0.0,
                embeddings_processing_time=0.0,
                embeddings_cache_search_time=0.0,
                query_execution_time=0.0,
                total_processing_time=total_processing_time,
                page=lngpage,
                rows_per_page=lngrowsperpage,
                llm_model_entity_extraction=strentityextractionmodel,
                llm_model_text2sql=strtext2sqlmodel,
                llm_model_complex=strcomplexquestionmodel,
                ui_language=request.ui_language,
                api_version=strapiversion,
                messages=messages,
                result=[],
            )
            logs.log_usage(
                "text2sql_post",
                {
                    "request": request.model_dump(),
                    "response": cache_miss_response.model_dump(),
                },
                strapiversion,
            )
            return cache_miss_response
        else:
            raise ValueError("Either question or question_hashed must be provided")
        """
        # Anonymize question by entity extraction
        entity_extraction_start_time = time.time()
        entity_extraction = t2s.f_entity_extraction(input_text)
        print("Entity extraction:", entity_extraction)
        entity_extraction_end_time = time.time()
        entity_extraction_processing_time = entity_extraction_end_time - entity_extraction_start_time
        messages.append(TextMessage(
            position=position_counter, 
            text="Processed question with entity extraction and anonymization."
        ))
        position_counter += 1
        """
        # Anonymize question by entity extraction
        entity_extraction_start_time = time.time()
        entity_extraction = entity.f_entity_extraction(input_text, strentityextractionmodel)
        print("Entity extraction:", entity_extraction)
        entity_extraction_end_time = time.time()
        entity_extraction_processing_time = entity_extraction_end_time - entity_extraction_start_time

        # High-level info
        messages.append(TextMessage(
            position=position_counter,
            text=f"Processed question with entity extraction and anonymization using LLM model '{strentityextractionmodel}'."
        ))
        position_counter += 1

        # Detailed JSON structure from f_entity_extraction()
        try:
            entity_extraction_json = json.dumps(entity_extraction, ensure_ascii=False)
        except TypeError:
            # Fallback if the result is not fully JSON-serializable
            entity_extraction_json = str(entity_extraction)

        messages.append(TextMessage(
            position=position_counter,
            text=f"Entity extraction result: {entity_extraction_json.replace('\"', '\\\"')}"
        ))
        position_counter += 1
        
        # Check if entity extraction was successful
        if isinstance(entity_extraction, dict) and 'error' in entity_extraction:
            print(f"Entity extraction failed: {entity_extraction['error']}")
            print("Falling back to original question without entity extraction")
            messages.append(TextMessage(
                position=position_counter, 
                text=f"Entity extraction failed using LLM model '{strentityextractionmodel}'; using original question without anonymization."
            ))
            position_counter += 1
            input_text_anonymized = input_text  # Use original question as fallback
        else:
            print("Entity extraction successful and returned a dictionary:", entity_extraction)
            messages.append(TextMessage(
                position=position_counter, 
                text=f"Entity extraction successful using LLM model '{strentityextractionmodel}'; question anonymized."
            ))
            position_counter += 1
            input_text_anonymized = entity_extraction['question']
        cache_result_anonymized = None

        if request.retrieve_from_cache:
            messages.append(TextMessage(
                position=position_counter, 
                text="Searching cache for anonymized question."
            ))
            position_counter += 1
            cache_result_anonymized = sql_cache.search_sql_cache_by_question_text(
                connection,
                input_text_anonymized,
                strapiversionformatted,
                ui_language=request.ui_language,
            )
            
            if cache_result_anonymized.get("found"):
                print("Found anonymized question in the SQL cache")
                cached_anonymized_question = True
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Anonymized question cache hit used for SQL query."
                ))
                position_counter += 1
                input_text_anonymized = cache_result_anonymized["question"]
                sql_query = cache_result_anonymized["sql_query"]
                if cache_result_anonymized.get("used_raw_query_to_preserve_limit"):
                    messages.append(TextMessage(
                        position=position_counter,
                        text="Cache hit: using SQL_QUERY instead of SQL_PROCESSED to preserve smaller LIMIT."
                    ))
                    position_counter += 1

                justification = cache_result_anonymized.get("justification", "")
                answer = cache_result_anonymized.get("answer", "")
                result_entity = cache_result_anonymized.get("result_entity", "")
                sql_query_anonymized = sql_query
                justification_anonymized = justification
                answer_anonymized = answer
            else:
                print("Anonymized question not found in the SQL cache")
                print("So we will look for the anonymized question in the questions embeddings cache")
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Anonymized question not found in SQL cache; searching questions embeddings cache."
                ))
                position_counter += 1

                # Search for similar anonymized questions in the questions embeddings cache
                if not USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE:
                    print("Questions embeddings cache is disabled; skipping embeddings lookup")
                    messages.append(TextMessage(
                        position=position_counter,
                        text="Questions embeddings cache is disabled; skipping embeddings lookup."
                    ))
                    position_counter += 1
                else:
                    embeddings_cache_start_time = time.time()
                    try:
                        # Extract entity variable names from the entity_extraction dictionary
                        entity_variables = []
                        if isinstance(entity_extraction, dict) and 'error' not in entity_extraction:
                            # Extract all entity variable names (e.g., Person_name1, Person_name2)
                            entity_variables = [key for key in entity_extraction.keys() if key != 'question']
                            print(f"Entity variables to match: {entity_variables}")

                        print(f"Searching questions embeddings cache for: {input_text_anonymized}")

                        # First, get more results to filter through
                        n_results_to_fetch = 10  # Get more results initially
                        embedding_results = anonymizedqueries.query(
                            query_texts=[input_text_anonymized],
                            n_results=n_results_to_fetch,
                            include=['documents', 'metadatas', 'distances']
                        )
                        embeddings_cache_end_time = time.time()
                        embeddings_cache_search_time = embeddings_cache_end_time - embeddings_cache_start_time

                        print(f"Questions embeddings cache search completed in {embeddings_cache_search_time:.4f} seconds")

                        if embedding_results['documents'][0] and len(embedding_results['documents'][0]) > 0:
                            messages.append(TextMessage(
                                position=position_counter,
                                text="Found potential matches in questions embeddings cache; filtering by entity variables."
                            ))
                            position_counter += 1
                            # Filter results to find ones that contain all required entity variables
                            valid_result_found = False
                            valid_result_index = -1

                            for i in range(len(embedding_results['documents'][0])):
                                document = embedding_results['documents'][0][i]
                                distance = embedding_results['distances'][0][i]

                                # Extract entity variables from the document using regex
                                doc_entity_vars = re.findall(r'{{(\w+\d*)}}', document)
                                print(f"Result {i}: document='{document}', distance={distance}, vars={doc_entity_vars}")

                                # Check if all required entity variables are present in this document
                                if all(var in doc_entity_vars for var in entity_variables):
                                    # Also check if distance is below threshold
                                    if distance < similarity_threshold:
                                        print(f"Found valid result at index {i} with all required variables and acceptable distance")
                                        valid_result_found = True
                                        valid_result_index = i
                                        break
                                    else:
                                        print(f"Result {i} has all variables but distance {distance} exceeds threshold {similarity_threshold}")
                                else:
                                    missing_vars = [var for var in entity_variables if var not in doc_entity_vars]
                                    print(f"Result {i} missing variables: {missing_vars}")

                            if valid_result_found:
                                # Use the valid result
                                distance = embedding_results['distances'][0][valid_result_index]
                                print(f"Using valid anonymized question from embeddings cache with distance: {distance}")
                                cached_anonymized_question_embedding = True
                                messages.append(TextMessage(
                                    position=position_counter,
                                    text="Embeddings cache hit used for SQL query based on anonymized question."
                                ))
                                position_counter += 1

                                # Extract SQL query from metadata
                                metadata = embedding_results['metadatas'][0][valid_result_index]
                                if 'sql_query_anonymized' in metadata:
                                    sql_query = metadata['sql_query_anonymized']
                                    sql_query_anonymized = sql_query
                                    justification = metadata.get('justification', '')
                                    justification_anonymized = justification
                                    answer = metadata.get('answer', '')
                                    answer_anonymized = answer
                                    result_entity = metadata.get('result_entity', '')
                                    print(f"Retrieved SQL query from questions embeddings cache: {sql_query}")
                                    messages.append(TextMessage(
                                        position=position_counter,
                                        text="SQL query retrieved from questions embeddings cache metadata: " + sql_query_anonymized
                                    ))
                                    position_counter += 1
                                else:
                                    print("Warning: No sql_query_anonymized found in metadata")
                                    messages.append(TextMessage(
                                        position=position_counter,
                                        text="Warning: No SQL query found in questions embeddings cache metadata; invalidating cache hit."
                                    ))
                                    position_counter += 1
                                    cached_anonymized_question_embedding = False
                            else:
                                print("No results found with all required entity variables and acceptable distance")
                                messages.append(TextMessage(
                                    position=position_counter,
                                    text="No valid matches found in questions embeddings cache with required entity variables and acceptable similarity."
                                ))
                                position_counter += 1
                        else:
                            print("No similar questions found in questions embeddings cache")
                            messages.append(TextMessage(
                                position=position_counter,
                                text="No similar questions found in questions embeddings cache."
                            ))
                            position_counter += 1

                    except Exception as e:
                        print(f"Error searching questions embeddings cache: {e}")
                        messages.append(TextMessage(
                            position=position_counter,
                            text=f"Error occurred while searching questions embeddings cache: {str(e)}"
                        ))
                        position_counter += 1
                        embeddings_cache_search_time = time.time() - embeddings_cache_start_time

        # If no SQL/embeddings cache hit produced a sql_query, call Text2SQL on the anonymized question.
        # Runs regardless of request.retrieve_from_cache: when caching is disabled, both flags stay False
        # so Text2SQL is always invoked; when caching is enabled and a hit occurred, this is skipped.
        if not cached_anonymized_question and not cached_anonymized_question_embedding:
            text2sql_start_time = time.time()
            messages.append(TextMessage(
                position=position_counter,
                text=f"Generating SQL using LLM model '{strtext2sqlmodel}'."
            ))
            position_counter += 1
            json_content = t2s.f_text2sql(input_text_anonymized, strtext2sqlmodel, ui_language=request.ui_language)
            if not isinstance(json_content, dict):
                json_content = {"error": str(json_content)}

            print("JSON content:", json_content)
            if 'sql_query' not in json_content:
                ambiguous_question_for_text2sql = 1
                sql_query = ""
                sql_query_anonymized = ""
                result_entity = ""
                justification = json_content.get('justification') or ""
                justification_anonymized = justification
                answer = json_content.get('answer') or ""
                answer_anonymized = answer
                error_text2sql = json_content.get('error') or 'Text2SQL failed to return sql_query'
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Text2SQL failed using LLM model '{strtext2sqlmodel}': {error_text2sql}"
                ))
                position_counter += 1
            else:
                sql_query = json_content.get('sql_query') or ""
                if sql_query.endswith(';'):
                    sql_query = sql_query[:-1]
                sql_query_anonymized = sql_query
                result_entity = (json_content.get('result_entity') or "").strip().lower()
                justification = json_content.get('justification') or ""
                justification_anonymized = justification
                answer = json_content.get('answer') or ""
                answer_anonymized = answer
                error_text2sql = json_content.get('error') or ''

            text2sql_end_time = time.time()
            text2sql_processing_time = text2sql_end_time - text2sql_start_time
            messages.append(TextMessage(
                position=position_counter,
                text=f"Generated SQL query: {sql_query_anonymized.replace('"', '\\"')}"
            ))
            position_counter += 1
            messages.append(TextMessage(
                position=position_counter,
                text="Justification: " + justification
            ))
            position_counter += 1
            if error_text2sql != "":
                messages.append(TextMessage(
                    position=position_counter,
                    text="Error: " + error_text2sql
                ))
                position_counter += 1

            # --- Answer-entity expectation from the ORIGINAL question --------------
            # result_entity above is decided by the LLM on the ANONYMIZED question.
            # Anonymizing a head-noun entity word flips the apparent answer type:
            # "Which movie directors died in 2025?" -> "Which movie {{Department_name1}}
            # died in {{Death_year1}}?" reads as a movie query, so the model returns
            # movies instead of the directors. Re-derive the expected answer type from
            # the original question (still says "directors") and let the guard enforce
            # it. Empty -> fall back to the LLM's own result_entity (legacy behavior).
            expected_result_entity = ""
            if sql_query and not error_text2sql:
                expected_result_entity = t2s.f_classify_result_entity(
                    input_text, list(_RESULT_ENTITY_SOURCES.keys())
                )
                if expected_result_entity and expected_result_entity != result_entity:
                    messages.append(TextMessage(
                        position=position_counter,
                        text=f"Answer-entity expectation from original question: '{expected_result_entity}' (LLM proposed '{result_entity or 'none'}')."
                    ))
                    position_counter += 1

            # --- Answer-entity guard (FASTAPI-TEXT2SQL-117, extended by -136) -----
            # The SELECT must return the entity the user asked for. The expectation is
            # the original-question classification when it maps to a known result
            # entity, otherwise the LLM's own result_entity (legacy). When the SELECT
            # returns the wrong result table (e.g. "actors of <movie>" projecting the
            # movie instead of the persons, or an anonymization-flipped answer type),
            # do ONE targeted regeneration. Driven by _RESULT_ENTITY_SOURCES so EVERY
            # result entity (collection, group, company, network, award, …) is checked,
            # not just movie/serie/person; UNION / multi-entity (movie_serie /
            # CONTENT_TYPE) queries are left untouched, and the regenerated query is
            # only adopted if it actually fixes the projection (no regression).
            _guard_entity = expected_result_entity if expected_result_entity in _RESULT_ENTITY_SOURCES else result_entity
            if sql_query and not error_text2sql and _guard_entity in _RESULT_ENTITY_SOURCES:
                _expected_id, _entity_table = _RESULT_ENTITY_SOURCES[_guard_entity]
                _select_clause = re.split(r"\bfrom\b", sql_query, maxsplit=1, flags=re.IGNORECASE)[0].upper()
                _is_union = bool(re.search(r"\bunion\b", sql_query, re.IGNORECASE)) or ("CONTENT_TYPE" in sql_query)
                if not _is_union and _expected_id not in _select_clause:
                    messages.append(TextMessage(
                        position=position_counter,
                        text=f"Answer-entity guard: query did not return the expected entity '{_guard_entity}' ({_expected_id}); regenerating once."
                    ))
                    position_counter += 1
                    _correction_hint = (
                        f"CORRECTION: The user wants {_guard_entity} rows returned (result_entity = \"{_guard_entity}\"). "
                        f"The previous SQL returned the wrong entity. Regenerate so the primary result table is "
                        f"{_entity_table} and the SELECT projects {_expected_id} with the {_guard_entity} 'Result Columns'. "
                        f"Any other named movie, person or serie is only a filter reached via joins, never the SELECT target."
                    )
                    json_content_retry = t2s.f_text2sql(
                        input_text_anonymized, strtext2sqlmodel,
                        ui_language=request.ui_language, correction_hint=_correction_hint,
                    )
                    if isinstance(json_content_retry, dict) and json_content_retry.get('sql_query'):
                        _retry_sql = json_content_retry.get('sql_query') or ""
                        if _retry_sql.endswith(';'):
                            _retry_sql = _retry_sql[:-1]
                        _retry_select = re.split(r"\bfrom\b", _retry_sql, maxsplit=1, flags=re.IGNORECASE)[0].upper()
                        if _expected_id in _retry_select:
                            sql_query = _retry_sql
                            sql_query_anonymized = _retry_sql
                            justification = json_content_retry.get('justification') or justification
                            justification_anonymized = justification
                            answer = json_content_retry.get('answer') or answer
                            answer_anonymized = answer
                            result_entity = (json_content_retry.get('result_entity') or _guard_entity).strip().lower()
                            messages.append(TextMessage(
                                position=position_counter,
                                text=f"Answer-entity guard: regenerated query now returns '{result_entity}' ({_expected_id})."
                            ))
                            position_counter += 1
                        else:
                            messages.append(TextMessage(
                                position=position_counter,
                                text="Answer-entity guard: regeneration still did not return the expected entity; keeping the original query."
                            ))
                            position_counter += 1
            # --- end answer-entity guard ----------------------------------------
    async def _retry_with_resolved_complex_question(*, start_message: str, success_message: str, empty_question_message: str, error_message: str):
        """Retry the full pipeline using a stronger-model simplification of the original question."""
        nonlocal position_counter, complex_model_used
        complex_model_used = True
        messages.append(TextMessage(
            position=position_counter,
            text=start_message
        ))
        position_counter += 1

        retry_payload = t2s.f_resolve_complex_question_retry_payload(original_question, strcomplexquestionmodel)
        resolved_complex = retry_payload.get("resolved")
        try:
            resolved_complex_json = json.dumps(resolved_complex, ensure_ascii=False)
        except Exception:
            resolved_complex_json = str(resolved_complex)
        messages.append(TextMessage(
            position=position_counter,
            text=f"Complex question resolution output: {resolved_complex_json.replace('"', '\\"')}"
        ))
        position_counter += 1

        if not retry_payload.get("has_error"):
            retry_question = retry_payload.get("retry_question") or ""
            if retry_question != "":
                messages.append(TextMessage(
                    position=position_counter,
                    text=success_message
                ))
                position_counter += 1

                try:
                    connection.close()
                except Exception:
                    pass

                retry_request = request.model_copy(deep=True)
                retry_request.question = retry_question
                retry_request.question_hashed = None
                retry_request.complex_question_already_resolved = True

                retry_response = await search_text2sql(retry_request, api_key)

                reasoning_justification = str(retry_payload.get("justification") or "").strip()
                if reasoning_justification != "":
                    try:
                        retry_response.justification = reasoning_justification
                    except Exception:
                        pass

                if request.store_to_cache:
                    try:
                        retry_connection = get_db_connection()
                        original_question_hash = hashlib.sha256(original_question.encode('utf-8')).hexdigest()
                        sql_cache.write_sql_cache_entry(
                            retry_connection,
                            question=original_question,
                            question_hashed=original_question_hash,
                            sql_query=getattr(retry_response, "sql_query", "") or "",
                            sql_processed=getattr(retry_response, "sql_query", "") or "",
                            justification=getattr(retry_response, "justification", "") or "",
                            answer=getattr(retry_response, "answer", "") or "",
                            api_version=strapiversionformatted,
                            entity_extraction_processing_time=getattr(retry_response, "entity_extraction_processing_time", 0.0) or 0.0,
                            text2sql_processing_time=getattr(retry_response, "text2sql_processing_time", 0.0) or 0.0,
                            embeddings_time=getattr(retry_response, "embeddings_processing_time", 0.0) or 0.0,
                            query_time=getattr(retry_response, "query_execution_time", 0.0) or 0.0,
                            total_processing_time=getattr(retry_response, "total_processing_time", 0.0) or 0.0,
                            is_anonymized=False,
                            ui_language=request.ui_language,
                            result_entity=getattr(retry_response, "result_entity", "") or "",
                        )
                        messages.append(TextMessage(
                            position=position_counter,
                            text="Stored original complex question and final SQL query to cache after stronger-model retry."
                        ))
                        position_counter += 1
                        retry_connection.close()
                    except Exception as cache_retry_error:
                        try:
                            retry_connection.close()
                        except Exception:
                            pass
                        messages.append(TextMessage(
                            position=position_counter,
                            text=f"Failed to store original complex question to cache after stronger-model retry: {str(cache_retry_error)}"
                        ))
                        position_counter += 1

                merged_messages = []
                pos = 1
                for m in (messages or []):
                    merged_messages.append(TextMessage(position=pos, text=m.text))
                    pos += 1
                for m in (getattr(retry_response, "messages", None) or []):
                    merged_messages.append(TextMessage(position=pos, text=m.text))
                    pos += 1

                try:
                    retry_response.messages = merged_messages
                except Exception:
                    pass

                try:
                    retry_response.complex_model_used = True
                except Exception:
                    pass

                return retry_response

            messages.append(TextMessage(
                position=position_counter,
                text=empty_question_message
            ))
            position_counter += 1
            return None

        messages.append(TextMessage(
            position=position_counter,
            text=error_message
        ))
        position_counter += 1
        return None

    sql_query_llm = sql_query
    # if the error element is found in json content
    if error_text2sql!="" and error_text2sql!=None:
        print("Problem detected so the Text-to-SQL cannot produce a SQL query")
        print("Error: ", error_text2sql)

        retryable_quota_error_text2sql = _is_retryable_quota_error_text(error_text2sql)

        # One-time retry: try resolving the original (non-anonymized) question into a simpler one
        # using a stronger model, then rerun the whole pipeline from the beginning.
        try:
            can_retry = (
                request.complex_question_processing
                and bool(request.question)
                and not getattr(request, "complex_question_already_resolved", False)
                and not retryable_quota_error_text2sql
                and "original_question" in locals()
                and isinstance(original_question, str)
                and original_question.strip() != ""
            )
        except Exception:
            can_retry = False

        if retryable_quota_error_text2sql:
            messages.append(TextMessage(
                position=position_counter,
                text="Retryable provider quota/rate-limit error detected; skipping stronger-model retry so the caller can apply wait-and-retry behavior."
            ))
            position_counter += 1

        if can_retry:
            retry_response = await _retry_with_resolved_complex_question(
                start_message=f"Attempting to simplify the original question using the stronger model '{strcomplexquestionmodel}' (one-time retry).",
                success_message=f"Text2SQL error detected; attempting one-time retry with simplified question from stronger model '{strcomplexquestionmodel}'.",
                empty_question_message="Complex question resolution did not return a simplified question; skipping retry.",
                error_message="Complex question resolution returned an error; skipping retry."
            )
            if retry_response is not None:
                return retry_response
        elif not retryable_quota_error_text2sql:
            messages.append(TextMessage(
                position=position_counter,
                text="Complex question retry conditions not met (already resolved, missing original question, or no question provided); skipping retry."
            ))
            position_counter += 1

        ambiguous_question_for_text2sql = 1
        messages.append(TextMessage(
            position=position_counter, 
            text="Problem detected so the Text-to-SQL cannot produce a SQL query."
        ))
        position_counter += 1

    if not cached_exact_question:
        if isinstance(entity_extraction, dict):
            messages.append(TextMessage(
                position=position_counter, 
                text="Processing entity resolution using embeddings and language-specific columns."
            ))
            position_counter += 1
    
    embeddings_start_time = time.time()
    if not cached_exact_question and (not ambiguous_question_for_text2sql or justification):
        print("Computing embeddings for entity resolution")
        messages.append(TextMessage(
            position=position_counter, 
            text="Processing entity values using embeddings for entity matching."
        ))
        position_counter += 1
        entity_resolution_result = entity.resolve_entities(
            connection=connection,
            entity_extraction=entity_extraction,
            sql_query=sql_query,
            justification=justification,
            answer=answer or "",
            position_counter=position_counter,
            text_message_cls=TextMessage,
            messages=messages,
            chromadb_collections_by_name=CHROMADB_COLLECTIONS_BY_NAME,
        )
        sql_query = entity_resolution_result["sql_query"]
        justification = entity_resolution_result["justification"]
        answer = entity_resolution_result["answer"]
        position_counter = entity_resolution_result["position_counter"]
        ambiguous_question_for_text2sql = max(
            ambiguous_question_for_text2sql,
            entity_resolution_result.get("ambiguous_question_for_text2sql", 0),
        )
    embeddings_end_time = time.time()
    embeddings_processing_time = embeddings_end_time - embeddings_start_time
    
    # Execute the SQL query and get results
    query_results = []
    query_execution_time = 0.0
    if not ambiguous_question_for_text2sql:
        # Keep a copy of the SQL query before pagination is appended.
        # This is what we want to store in cache so that per-request pagination
        # (and any LLM-provided smaller LIMIT) can be applied dynamically.
        sql_query_processed_base = sql_query
        sql_query_anonymized_base = sql_query_anonymized
        messages.append(TextMessage(
            position=position_counter, 
            text="Preparing to execute SQL query."
        ))
        position_counter += 1
        with connection.cursor() as cursor:
            # Measure SQL query execution time
            query_start_time = time.time()
            # Calculate pagination parameters
            limit = lngrowsperpage
            calculated_offset = (lngpage - 1) * lngrowsperpage
            
            # Check if SQL query already has LIMIT/OFFSET
            match_limit_offset = re.search(r"\blimit\b\s+(\d+)\s+\boffset\b\s+(\d+)", sql_query, re.IGNORECASE)
            match_limit_comma = re.search(r"\blimit\b\s+(\d+)\s*,\s*(\d+)", sql_query, re.IGNORECASE)
            match_limit_only = re.search(r"\blimit\b\s+(\d+)", sql_query, re.IGNORECASE)

            if match_limit_offset or match_limit_comma or match_limit_only:
                messages.append(TextMessage(
                    position=position_counter, 
                    text="SQL query contains existing LIMIT/OFFSET clause; removing for pagination if greater than page size."
                ))
                position_counter += 1

                # SQL query already has LIMIT, extract existing values
                if match_limit_offset:
                    llm_defined_limit = int(match_limit_offset.group(1))
                    llm_defined_offset = int(match_limit_offset.group(2))
                elif match_limit_comma:
                    # MariaDB syntax: LIMIT offset, count
                    llm_defined_offset = int(match_limit_comma.group(1))
                    llm_defined_limit = int(match_limit_comma.group(2))
                else:
                    llm_defined_limit = int(match_limit_only.group(1))
                    llm_defined_offset = 0

                print("FOUND EXISTING LIMIT:", llm_defined_limit, "OFFSET:", llm_defined_offset)

                # Remove any existing LIMIT/OFFSET clause to replace with paginated version
                sql_query = re.sub(r"\blimit\b\s+\d+\s+\boffset\b\s+\d+", "", sql_query, flags=re.IGNORECASE)
                sql_query = re.sub(r"\blimit\b\s+\d+\s*,\s*\d+", "", sql_query, flags=re.IGNORECASE)
                sql_query = re.sub(r"\blimit\b\s+\d+", "", sql_query, flags=re.IGNORECASE).strip()

                # Respect a smaller LLM-defined limit if present
                if llm_defined_limit < limit:
                    limit = llm_defined_limit

                base_offset = llm_defined_offset or 0
                offset = base_offset + calculated_offset
                sql_query = sql_query + f" LIMIT {limit} OFFSET {offset}"
            else:
                # Add pagination: LIMIT and OFFSET based on page number
                offset = calculated_offset
                if lngpage > 1:
                    messages.append(TextMessage(
                        position=position_counter, 
                        text=f"Adding pagination: LIMIT {limit} OFFSET {offset} for page {lngpage}."
                    ))
                    position_counter += 1
                    sql_query = sql_query + f" LIMIT {limit} OFFSET {offset}"
                else:
                    messages.append(TextMessage(
                        position=position_counter, 
                        text=f"Adding pagination: LIMIT {limit} for first page."
                    ))
                    position_counter += 1
                    sql_query = sql_query + f" LIMIT {limit}"
                    offset = 0
                
            print(f"PAGINATION: Page={lngpage}, LIMIT={limit}, OFFSET={offset}")
            print("LIMIT:", limit, "OFFSET:", offset)
            print("SQL query execution:", sql_query)
            sql_execution_failed = False
            try: 
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing SQL query: {sql_query}"
                ))
                position_counter += 1
                print("cursor.execute(sql_query)")
                cursor.execute(sql_query)
                raw_results = cursor.fetchall()
                # Format results with integer index and record data
                for index, record in enumerate(raw_results):
                    query_results.append({
                        "index": index,
                        "data": {k: html.unescape(v) if isinstance(v, str) else v for k, v in record.items()}
                    })
            except Exception as e:
                print(f"Database operation failed: {e}")
                sql_execution_failed = True
                messages.append(TextMessage(
                    position=position_counter, 
                    text=f"Database query execution failed: {str(e)}"
                ))
                position_counter += 1
                # Database errors not returned directly to clients
                # query_results = [{"error": str(e)}]
        query_end_time = time.time()
        query_execution_time = query_end_time - query_start_time
        messages.append(TextMessage(
            position=position_counter, 
            text=f"Executed SQL query with pagination: page={lngpage}, limit={limit}, offset={offset}."
        ))
        position_counter += 1

        # One-time retry: if SQL execution failed (e.g., MariaDB error), try simplifying the
        # initial/original question using the stronger model and rerun the whole pipeline.
        try:
            can_retry_sql_execution_error = (
                request.complex_question_processing
                and sql_execution_failed
                and lngpage == 1
                and bool(request.question)
                and not getattr(request, "complex_question_already_resolved", False)
                and "original_question" in locals()
                and isinstance(original_question, str)
                and original_question.strip() != ""
            )
        except Exception:
            can_retry_sql_execution_error = False

        if can_retry_sql_execution_error:
            retry_response = await _retry_with_resolved_complex_question(
                start_message=f"SQL query execution failed; attempting to simplify the original question using the stronger model '{strcomplexquestionmodel}' (one-time retry).",
                success_message=f"SQL execution error detected; attempting one-time retry with simplified question from stronger model '{strcomplexquestionmodel}'.",
                empty_question_message="Complex question resolution did not return a simplified question; skipping SQL-execution-error retry.",
                error_message="Complex question resolution returned an error; skipping SQL-execution-error retry."
            )
            if retry_response is not None:
                return retry_response

        # One-time retry: if the SQL ran successfully but returned 0 rows, try simplifying the
        # original question using the stronger model and rerun the whole pipeline.
        try:
            can_retry_no_results = (
                request.complex_question_processing
                and not sql_execution_failed
                and lngpage == 1
                and isinstance(query_results, list)
                and len(query_results) == 0
                and bool(request.question)
                and not getattr(request, "complex_question_already_resolved", False)
                and "original_question" in locals()
                and isinstance(original_question, str)
                and original_question.strip() != ""
                # Deterministic guard: only retry when the primary query had a resolution
                # problem -- a vague question or unresolved entity placeholders leave
                # ambiguous_question_for_text2sql = 1. When every placeholder resolved to a
                # real entity and a well-formed query simply returned 0 rows, the empty
                # result is AUTHORITATIVE (e.g. "series directed by Chris Carter" -- he has
                # no series-level Directing credit) and must NOT be masked by a
                # memory-fabricated retry. Complements the complex_question.md prompt rule.
                and bool(ambiguous_question_for_text2sql)
            )
        except Exception:
            can_retry_no_results = False

        if can_retry_no_results:
            retry_response = await _retry_with_resolved_complex_question(
                start_message=f"SQL query returned 0 rows; attempting to simplify the original question using the stronger model '{strcomplexquestionmodel}' (one-time retry).",
                success_message=f"No-results detected; attempting one-time retry with simplified question from stronger model '{strcomplexquestionmodel}'.",
                empty_question_message="Complex question resolution did not return a simplified question; skipping no-results retry.",
                error_message="Complex question resolution returned an error; skipping no-results retry."
            )
            if retry_response is not None:
                return retry_response
        elif (
            request.complex_question_processing
            and not sql_execution_failed
            and lngpage == 1
            and isinstance(query_results, list)
            and len(query_results) == 0
            and not ambiguous_question_for_text2sql
            and not getattr(request, "complex_question_already_resolved", False)
        ):
            messages.append(TextMessage(
                position=position_counter,
                text="0 rows but all entity placeholders resolved; treating the empty result as authoritative (no complex-question retry)."
            ))
            position_counter += 1

        # Single-cell zero result: if the SQL returned a single row with a single column
        # whose value is 0, the SQL approach likely failed (e.g. COUNT returning 0).
        # Ask the stronger model to directly answer with the correct scalar value.
        try:
            single_zero_result = False
            if (
                not sql_execution_failed
                and lngpage == 1
                and isinstance(query_results, list)
                and len(query_results) == 1
            ):
                row_data = query_results[0].get("data")
                if isinstance(row_data, dict) and len(row_data) == 1:
                    single_value = next(iter(row_data.values()))
                    if single_value == 0:
                        single_zero_result = True

            can_answer_zero_count = (
                request.complex_question_processing
                and single_zero_result
                and bool(request.question)
                and not getattr(request, "complex_question_already_resolved", False)
                and "original_question" in locals()
                and isinstance(original_question, str)
                and original_question.strip() != ""
            )
        except Exception:
            can_answer_zero_count = False

        if can_answer_zero_count:
            complex_model_used = True
            messages.append(TextMessage(
                position=position_counter,
                text=f"SQL query returned a single-cell result with value 0; asking the stronger model '{strcomplexquestionmodel}' for a direct answer."
            ))
            position_counter += 1

            answer_result = t2s.f_answer_single_value(original_question, strcomplexquestionmodel)

            if answer_result.get("error"):
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Stronger model '{strcomplexquestionmodel}' could not provide a direct answer: {answer_result['error']}"
                ))
                position_counter += 1
            else:
                answer_value = answer_result["value"]
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Stronger model '{strcomplexquestionmodel}' provided direct answer: {answer_value}"
                ))
                position_counter += 1

                # Build a synthetic SQL embedding the answer, execute it, then cache it.
                # Executing before caching ensures consistency (result comes from SQL like
                # every other query) and validation (confirms the SQL is well-formed).
                escaped_question = original_question.replace("'", "''")
                if isinstance(answer_value, (int, float)):
                    synthetic_sql = f"SELECT {answer_value} AS '{escaped_question}' FROM DUAL"
                else:
                    escaped_value = str(answer_value).replace("'", "''")
                    synthetic_sql = f"SELECT '{escaped_value}' AS '{escaped_question}' FROM DUAL"

                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing synthetic SQL for direct answer: {synthetic_sql}"
                ))
                position_counter += 1

                try:
                    with connection.cursor() as synth_cursor:
                        synth_cursor.execute(synthetic_sql)
                        synth_results = synth_cursor.fetchall()
                        query_results = [
                            {"index": idx, "data": {k: html.unescape(v) if isinstance(v, str) else v for k, v in row.items()}}
                            for idx, row in enumerate(synth_results)
                        ]
                    messages.append(TextMessage(
                        position=position_counter,
                        text=f"Synthetic SQL executed successfully; result returned from SQL execution."
                    ))
                    position_counter += 1
                except Exception as synth_err:
                    messages.append(TextMessage(
                        position=position_counter,
                        text=f"Synthetic SQL execution failed: {str(synth_err)}; falling back to original zero result."
                    ))
                    position_counter += 1
                    synthetic_sql = None

                # Cache the validated synthetic SQL so subsequent calls skip the stronger model
                if synthetic_sql and request.store_to_cache and request.question:
                    synthetic_hash = hashlib.sha256(original_question.encode('utf-8')).hexdigest()
                    try:
                        sql_cache.write_sql_cache_entry(
                            connection,
                            question=original_question,
                            question_hashed=synthetic_hash,
                            sql_query=synthetic_sql,
                            sql_processed=synthetic_sql,
                            justification=justification or "",
                            answer=answer or "",
                            api_version=strapiversionformatted,
                            entity_extraction_processing_time=entity_extraction_processing_time,
                            text2sql_processing_time=text2sql_processing_time,
                            embeddings_time=embeddings_processing_time,
                            query_time=query_execution_time,
                            total_processing_time=0.0,
                            is_anonymized=False,
                            ui_language=request.ui_language,
                            result_entity="",
                        )
                        messages.append(TextMessage(
                            position=position_counter,
                            text=f"Cached synthetic SQL for direct answer: {synthetic_sql}"
                        ))
                        position_counter += 1
                    except Exception as cache_err:
                        messages.append(TextMessage(
                            position=position_counter,
                            text=f"Failed to cache synthetic SQL for direct answer: {str(cache_err)}"
                        ))
                        position_counter += 1
    else:
        messages.append(TextMessage(
            position=position_counter, 
            text="Skipping SQL query execution due to ambiguous question."
        ))
        position_counter += 1
    
    # Generate hash for the question if not provided
    if not ambiguous_question_for_text2sql:
        question_hash = request.question_hashed
        if not question_hash:
            messages.append(TextMessage(
                position=position_counter, 
                text="Generating question hash for caching."
            ))
            position_counter += 1
            question_hash = hashlib.sha256(request.question.encode('utf-8')).hexdigest()
        
        # Compute the temporary global processing time before the write cache operations (SQL and embeddings)
        total_end_time = time.time()
        total_processing_time = total_end_time - total_start_time
        # Store to SQL cache if requested and not already stored as exact question or anonymized question
        if request.store_to_cache and not cached_exact_question and not sql_execution_failed and request.question:
            messages.append(TextMessage(position=position_counter, text="Storing exact question and SQL query to cache."))
            position_counter += 1
            sql_cache.write_sql_cache_entry(
                connection,
                question=request.question,
                question_hashed=question_hash,
                sql_query=sql_query_llm,
                sql_processed=sql_query_processed_base,
                justification=justification or "",
                answer=answer or "",
                api_version=strapiversionformatted,
                entity_extraction_processing_time=entity_extraction_processing_time,
                text2sql_processing_time=text2sql_processing_time,
                embeddings_time=embeddings_processing_time,
                query_time=query_execution_time,
                total_processing_time=total_processing_time,
                is_anonymized=False,
                ui_language=request.ui_language,
                result_entity=result_entity or "",
            )

        # Store to SQL cache if requested and not already stored as exact question or anonymized question
        if request.store_to_cache and not cached_exact_question and not cached_anonymized_question and not sql_execution_failed and request.question:
            messages.append(TextMessage(
                position=position_counter, 
                text="Storing anonymized question and SQL query to cache."
            ))
            position_counter += 1
            sql_cache.write_sql_cache_entry(
                connection,
                question=input_text_anonymized,
                question_hashed=question_hash,
                sql_query=sql_query_llm,
                sql_processed=sql_query_anonymized_base,
                justification=justification_anonymized or "",
                answer=answer_anonymized or "",
                api_version=strapiversionformatted,
                entity_extraction_processing_time=entity_extraction_processing_time,
                text2sql_processing_time=text2sql_processing_time,
                embeddings_time=embeddings_processing_time,
                query_time=query_execution_time,
                total_processing_time=total_processing_time,
                is_anonymized=True,
                ui_language=request.ui_language,
                result_entity=result_entity or "",
            )
        
        if USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE and request.store_to_cache and not cached_anonymized_question_embedding and not sql_execution_failed and input_text_anonymized:
            messages.append(TextMessage(
                position=position_counter, 
                text="Checking if anonymized question exists in embeddings cache before storing."
            ))
            position_counter += 1
            strdocid = hashlib.sha256(input_text_anonymized.encode('utf-8')).hexdigest()
            print("Anonymized query ID:", strdocid)
            existing_doc = anonymizedqueries.get(ids=[strdocid])
            if existing_doc and existing_doc['ids']:
                print("Anonymized question already exists in the embeddings cache")
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Anonymized question already exists in embeddings cache; skipping storage."
                ))
                position_counter += 1
            else:
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Storing anonymized question and SQL query to embeddings cache."
                ))
                position_counter += 1
                # Extract entity variables for metadata
                entity_vars_for_metadata = []
                if isinstance(entity_extraction, dict) and 'error' not in entity_extraction:
                    entity_vars_for_metadata = [key for key in entity_extraction.keys() if key != 'question']
                
                anonymizedqueries.add(
                    ids=[strdocid],
                    documents=[input_text_anonymized],
                    metadatas=[{
                            "sql_query_anonymized": sql_query_anonymized,
                            "justification": justification_anonymized or "",
                            "answer": answer_anonymized or "",
                            "result_entity": result_entity or "",
                            "api_version": strapiversionformatted,
                            "entity_variables": ",".join(entity_vars_for_metadata),  # Store as comma-separated string
                            "entity_extraction_processing_time": entity_extraction_processing_time,
                            "text2sql_processing_time": text2sql_processing_time,
                            "dat_creat": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }]
                )
                print(f"Anonymized question added to embeddings cache with entity variables: {entity_vars_for_metadata}")
    
    # FASTAPI-TEXT2SQL-162 (post-process variant): localize movie/serie result rows by
    # ui_language WITHOUT touching the prompt or the generated SQL. No-op for English.
    localize_search_results(query_results, normalize_ui_language(request.ui_language), connection)
    connection.close()

    # Generate question hash if we have a question and no hash was provided
    response_question_hash = request.question_hashed
    if not response_question_hash and request.question:
        response_question_hash = hashlib.sha256(request.question.encode('utf-8')).hexdigest()
    
    # Compute the final global processing time with also the write cache operations (SQL and embeddings)
    total_end_time = time.time()
    total_processing_time = total_end_time - total_start_time
    
    # Surface prompt-cache observations (one per LLM call this request made, across
    # entity extraction, text2sql, complex-question retry, and single-value; for
    # OpenAI / Anthropic / Google) into the response messages so caching is
    # verifiable through the API itself, not only the server stdout.
    for _cache_event in t2s.drain_prompt_cache_events():
        messages.append(TextMessage(
            position=position_counter,
            text=_cache_event["text"],
        ))
        position_counter += 1

    messages.append(TextMessage(
        position=position_counter,
        text="Completed request processing and prepared response."
    ))
    position_counter += 1

    justification = html.unescape(justification or "")
    justification_anonymized = html.unescape(justification_anonymized or "")
    answer = html.unescape(answer or "")
    answer_anonymized = html.unescape(answer_anonymized or "")
    response_error_text = error_text2sql or ""
    if not response_error_text and isinstance(entity_extraction, dict) and entity_extraction.get("error"):
        response_error_text = str(entity_extraction.get("error") or "")
    retry_metadata = _extract_retry_metadata(response_error_text)

    # Collapse a repeated franchise/collection descriptor in the final answer/justification
    # ("Star Wars Collection collection" -> "Star Wars Collection"). Applied here, at
    # response assembly, so it covers EVERY path reaching this point -- including the
    # exact-question cache hit, which returns a cached answer verbatim and bypasses
    # resolve_entities. Idempotent on already-clean text.
    answer = entity._collapse_repeated_descriptor(answer)
    justification = entity._collapse_repeated_descriptor(justification)

    # Empty-result honesty: the LLM writes `answer` before execution, so a well-formed
    # query that returns no rows (and fired no retry -- see the deterministic gate above)
    # still reads affirmatively ("Here are the series ..."). Replace it with a neutral,
    # localized empty-result message so the answer matches the (empty) data. A scalar
    # zero (COUNT = 0) is one row, not zero, so it is unaffected.
    if (
        isinstance(query_results, list)
        and len(query_results) == 0
        and not sql_execution_failed
        and not response_error_text
    ):
        answer = (
            "Aucun résultat ne correspond à cette question."
            if request.ui_language == "fr"
            else "No matching results were found for this question."
        )

    # Same-name-cluster detection (FASTAPI-TEXT2SQL-157): page 1 only, on a clean
    # result. Never let a detection glitch break the response.
    name_ambiguity = None
    if lngpage == 1 and not sql_execution_failed and not response_error_text:
        try:
            name_ambiguity = compute_name_ambiguity(sql_query, result_entity, query_results)
        except Exception as _name_ambiguity_exc:
            print(f"name_ambiguity computation skipped: {_name_ambiguity_exc}")
            name_ambiguity = None

    response = Text2SQLResponse(
        question=input_text,
        question_hashed=response_question_hash,
        sql_query=sql_query or "",
        sql_query_anonymized=sql_query_anonymized or "",
        justification=justification,
        justification_anonymized=justification_anonymized,
        answer=answer,
        answer_anonymized=answer_anonymized,
        result_entity=result_entity or "",
        name_ambiguity=name_ambiguity,
        error=response_error_text,
        error_code=retry_metadata.get("error_code"),
        is_retryable=bool(retry_metadata.get("is_retryable")),
        retry_after_seconds=retry_metadata.get("retry_after_seconds"),
        provider=retry_metadata.get("provider"),
        entity_extraction=entity_extraction,
        question_anonymized=input_text_anonymized,
        entity_extraction_processing_time=entity_extraction_processing_time,
        text2sql_processing_time=text2sql_processing_time,
        embeddings_processing_time=embeddings_processing_time,
        embeddings_cache_search_time=embeddings_cache_search_time,
        query_execution_time=query_execution_time,
        total_processing_time=total_processing_time,
        page=lngpage,
        llm_defined_limit=llm_defined_limit,
        llm_defined_offset=llm_defined_offset,
        limit=limit,
        offset=offset,
        rows_per_page=lngrowsperpage,
        cached_exact_question=cached_exact_question,
        cached_anonymized_question=cached_anonymized_question,
        cached_anonymized_question_embedding=cached_anonymized_question_embedding,
        ambiguous_question_for_text2sql=ambiguous_question_for_text2sql,
        llm_model_entity_extraction=strentityextractionmodel,
        llm_model_text2sql=strtext2sqlmodel,
        llm_model_complex=strcomplexquestionmodel,
        complex_model_used=complex_model_used,
        ui_language=request.ui_language,
        api_version=strapiversion,
        result=query_results,
        messages=messages
    )
    
    # Log the request and response
    log_data = {
        "request": request.model_dump(),
        "response": response.model_dump()
    }
    print("LOG DATA:", log_data)
    logs.log_usage("text2sql_post", log_data, strapiversion)
    
    return response

# ---------------------------------------------------------------------------
# Entity detail endpoints
# ---------------------------------------------------------------------------

def _fetch_wikipedia_images(cursor, id_wikidata, ui_language="en"):
    """Return Wikipedia images linked to an entity's Wikidata ID in the requested language.

    Returns the images for ``ui_language`` ("en" or "fr"); when the requested language
    has no images it falls back to English so a localized client still gets media.
    Returns [] when id_wikidata is missing. Excludes soft-deleted rows and dead images
    (non-200 HTTP status); NULL HTTP_STATUS is kept as a grace state for unverified rows.
    """
    if not id_wikidata:
        return []
    lang = normalize_ui_language(ui_language)

    def _query(target_lang):
        cursor.execute("""
            SELECT ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL,
                   MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER
            FROM T_WC_WIKIPEDIA_PAGE_LANG_IMAGE
            WHERE ID_WIKIDATA = %s
              AND LANG = %s
              AND DELETED = 0
              AND (HTTP_STATUS = 200 OR HTTP_STATUS IS NULL)
            ORDER BY IS_MAIN_IMAGE DESC, DISPLAY_ORDER ASC
        """, (id_wikidata, target_lang))
        return list(cursor.fetchall())

    rows = _query(lang)
    if not rows and lang != DEFAULT_UI_LANGUAGE:
        rows = _query(DEFAULT_UI_LANGUAGE)
    return rows


def _fetch_wikipedia_content(cursor, id_wikidata, ui_language="en"):
    """Return Wikipedia section content linked to an entity's Wikidata ID in the requested language.

    Each element exposes the section TITLE and CONTENT from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION for ``ui_language`` ("en" or "fr"); when the
    requested language has no sections it falls back to English. Returns [] when
    id_wikidata is missing. Excludes soft-deleted rows and orders by DISPLAY_ORDER to
    preserve natural reading order.
    """
    if not id_wikidata:
        return []
    lang = normalize_ui_language(ui_language)

    def _query(target_lang):
        cursor.execute("""
            SELECT TITLE AS title, CONTENT AS content
            FROM T_WC_WIKIPEDIA_PAGE_LANG_SECTION
            WHERE ID_WIKIDATA = %s
              AND LANG = %s
              AND DELETED = 0
            ORDER BY DISPLAY_ORDER ASC
        """, (id_wikidata, target_lang))
        return list(cursor.fetchall())

    rows = _query(lang)
    if not rows and lang != DEFAULT_UI_LANGUAGE:
        rows = _query(DEFAULT_UI_LANGUAGE)
    return rows


_TMDB_VIDEO_SOURCE_TABLES = {
    "movie": ("T_WC_TMDB_MOVIE_VIDEO", "ID_MOVIE"),
    "serie": ("T_WC_TMDB_SERIE_VIDEO", "ID_SERIE"),
    "season": ("T_WC_TMDB_SEASON_VIDEO", "ID_SEASON"),
    "episode": ("T_WC_TMDB_EPISODE_VIDEO", "ID_EPISODE"),
}


def _synthesize_tmdb_video_urls(video_site, video_key):
    """Build (WATCH_URL, EMBED_URL, THUMBNAIL_URL) from VIDEO_SITE + VIDEO_KEY.

    Supports YouTube and Vimeo, the only sites TMDb populates in practice. Returns
    (None, None, None) when site or key is missing or unrecognized.
    """
    if not video_key:
        return None, None, None
    site = (video_site or "").strip().lower()
    if site == "youtube":
        return (
            f"https://www.youtube.com/watch?v={video_key}",
            f"https://www.youtube.com/embed/{video_key}",
            f"https://img.youtube.com/vi/{video_key}/hqdefault.jpg",
        )
    if site == "vimeo":
        return (
            f"https://vimeo.com/{video_key}",
            f"https://player.vimeo.com/video/{video_key}",
            None,
        )
    return None, None, None


def _fetch_tmdb_videos(cursor, entity_kind, fk_value):
    """Return TMDb videos for an entity in the unified video schema.

    `entity_kind` is one of 'movie', 'serie', 'season', 'episode'. `fk_value` is the
    matching TMDb numeric ID (ID_MOVIE / ID_SERIE / ID_SEASON / ID_EPISODE). Skips
    soft-deleted rows. URLs are synthesized from VIDEO_SITE + VIDEO_KEY. Sorted
    OFFICIAL DESC then DISPLAY_ORDER ASC so curated trailers surface first.
    """
    if entity_kind not in _TMDB_VIDEO_SOURCE_TABLES or fk_value is None:
        return []
    table, fk_col = _TMDB_VIDEO_SOURCE_TABLES[entity_kind]
    cursor.execute(
        f"""
        SELECT ID_ROW, VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE,
               LANG, OFFICIAL, DAT_PUBLISHED, DISPLAY_ORDER
        FROM {table}
        WHERE {fk_col} = %s
          AND (DELETED IS NULL OR DELETED = 0)
        ORDER BY (OFFICIAL = 1) DESC, DISPLAY_ORDER ASC, ID_ROW ASC
        """,
        (fk_value,),
    )
    rows = cursor.fetchall()
    videos = []
    for r in rows:
        watch_url, embed_url, thumbnail_url = _synthesize_tmdb_video_urls(
            r.get("VIDEO_SITE"), r.get("VIDEO_KEY")
        )
        videos.append({
            "SOURCE": "tmdb",
            "VIDEO_KEY": r.get("VIDEO_KEY"),
            "VIDEO_NAME": r.get("VIDEO_NAME"),
            "VIDEO_SITE": r.get("VIDEO_SITE"),
            "VIDEO_TYPE": r.get("VIDEO_TYPE"),
            "LANG": r.get("LANG"),
            "OFFICIAL": r.get("OFFICIAL"),
            "DAT_PUBLISHED": r.get("DAT_PUBLISHED"),
            "DURATION_SECONDS": None,
            "WATCH_URL": watch_url,
            "EMBED_URL": embed_url,
            "FILE_URL": None,
            "THUMBNAIL_URL": thumbnail_url,
            "DISPLAY_ORDER": r.get("DISPLAY_ORDER"),
        })
    return videos


def _fetch_wikidata_videos(cursor, id_wikidata):
    """Return Wikidata media-resource videos for an entity in the unified video schema.

    Filtered to RESOURCE_KIND='video', IS_ACTIVE=1, DELETED=0. Per-resource URL
    variants are pivoted from T_WC_WIKIDATA_MEDIA_RESOURCE_URL by URL_TYPE (preferring
    IS_PREFERRED then IS_CANONICAL). Sorted preferred-then-priority so the most
    representative video surfaces first.
    """
    if not id_wikidata:
        return []
    cursor.execute("""
        SELECT
          mr.ID_MEDIA_RESOURCE,
          mr.SOURCE_PLATFORM,
          mr.SOURCE_IDENTIFIER,
          mr.CONTENT_ROLE,
          mr.RESOURCE_TITLE,
          mr.LANG_CODE,
          mr.DURATION_SECONDS,
          mr.IS_PREFERRED_RESOURCE,
          mr.SOURCE_PRIORITY,
          mr.THUMBNAIL_URL_PRIMARY,
          MAX(CASE WHEN mru.URL_TYPE = 'watch' THEN mru.URL END) AS WATCH_URL,
          MAX(CASE WHEN mru.URL_TYPE = 'embed' THEN mru.URL END) AS EMBED_URL,
          MAX(CASE WHEN mru.URL_TYPE = 'file' THEN mru.URL END) AS FILE_URL,
          MAX(CASE WHEN mru.URL_TYPE = 'thumbnail' THEN mru.URL END) AS THUMBNAIL_URL_PIVOTED,
          MAX(CASE WHEN mru.URL_TYPE = 'page' THEN mru.URL END) AS PAGE_URL
        FROM T_WC_WIKIDATA_MEDIA_RESOURCE mr
        LEFT JOIN T_WC_WIKIDATA_MEDIA_RESOURCE_URL mru
          ON mru.ID_MEDIA_RESOURCE = mr.ID_MEDIA_RESOURCE
          AND mru.IS_ACTIVE = 1
        WHERE mr.ID_WIKIDATA = %s
          AND mr.RESOURCE_KIND = 'video'
          AND mr.DELETED = 0
          AND mr.IS_ACTIVE = 1
        GROUP BY mr.ID_MEDIA_RESOURCE
        ORDER BY mr.IS_PREFERRED_RESOURCE DESC,
                 (mr.SOURCE_PRIORITY IS NULL), mr.SOURCE_PRIORITY ASC,
                 mr.ID_MEDIA_RESOURCE ASC
    """, (id_wikidata,))
    rows = cursor.fetchall()
    videos = []
    for r in rows:
        watch_url = r.get("WATCH_URL") or r.get("PAGE_URL")
        thumbnail_url = r.get("THUMBNAIL_URL_PIVOTED") or r.get("THUMBNAIL_URL_PRIMARY")
        videos.append({
            "SOURCE": "wikidata",
            "VIDEO_KEY": r.get("SOURCE_IDENTIFIER"),
            "VIDEO_NAME": r.get("RESOURCE_TITLE"),
            "VIDEO_SITE": r.get("SOURCE_PLATFORM"),
            "VIDEO_TYPE": r.get("CONTENT_ROLE"),
            "LANG": r.get("LANG_CODE"),
            "OFFICIAL": None,
            "DAT_PUBLISHED": None,
            "DURATION_SECONDS": r.get("DURATION_SECONDS"),
            "WATCH_URL": watch_url,
            "EMBED_URL": r.get("EMBED_URL"),
            "FILE_URL": r.get("FILE_URL"),
            "THUMBNAIL_URL": thumbnail_url,
            "DISPLAY_ORDER": None,
        })
    return videos


def _collection_members(cursor, cid):
    """All members of a T2S collection — movies AND series (FASTAPI-TEXT2SQL-152) — in
    release-date order. A T2S collection is cross-type (Philippe's CUSTOM_LIST extension):
    e.g. a Star Trek collection holds both the films and the TV series. Movie items carry
    ID_MOVIE / MOVIE_TITLE(+_FR); series items carry ID_SERIE / SERIE_TITLE(+_FR) with
    DAT_FIRST_AIR aliased to DAT_RELEASE; every item carries ENTITY_TYPE ('movie'/'serie'),
    DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH.
    """
    cursor.execute(
        """
        SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE,
               m.IMDB_RATING_WEIGHTED, m.POSTER_PATH
        FROM T_WC_T2S_MOVIE_COLLECTION mc
        JOIN T_WC_T2S_MOVIE m ON mc.ID_MOVIE = m.ID_MOVIE
        WHERE mc.ID_T2S_COLLECTION = %s AND mc.DELETED = 0
        """,
        (cid,),
    )
    members = [{**r, "ENTITY_TYPE": "movie"} for r in cursor.fetchall()]
    cursor.execute(
        """
        SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR AS DAT_RELEASE,
               s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH
        FROM T_WC_T2S_SERIE_COLLECTION sc
        JOIN T_WC_T2S_SERIE s ON sc.ID_SERIE = s.ID_SERIE
        WHERE sc.ID_T2S_COLLECTION = %s AND sc.DELETED = 0
        """,
        (cid,),
    )
    members += [{**r, "ENTITY_TYPE": "serie"} for r in cursor.fetchall()]
    # Release-date order across both types; unknown dates (NULL) sink to the end.
    members.sort(key=lambda r: (
        r.get("DAT_RELEASE") is None, r.get("DAT_RELEASE"), r["ENTITY_TYPE"],
        r.get("ID_MOVIE") if r["ENTITY_TYPE"] == "movie" else r.get("ID_SERIE"),
    ))
    return members


def _member_matches(r, entity_type, entity_id):
    """True when member row ``r`` is the (entity_type, entity_id) entity."""
    id_key = "ID_MOVIE" if entity_type == "movie" else "ID_SERIE"
    return r["ENTITY_TYPE"] == entity_type and r.get(id_key) == entity_id


def _collection_context_for(cursor, entity_type, entity_id, cid, ui_language="en"):
    """One cross-type collection context (FASTAPI-TEXT2SQL-152) for ``entity`` within the
    single collection ``cid``, or ``None`` if the entity is not a member. Returns a dict:
    ``{ID_T2S_COLLECTION, collection_name, collection_movies, collection_previous,
    collection_next}``. ``collection_movies`` is every member (film AND series) in
    release-date order, each with its native id/title keys, an ``ENTITY_TYPE`` tag and an
    ``IS_CURRENT`` flag on the requested entity; prev/next are the release-date neighbours
    (or ``None``) and MAY be of the OTHER type. Name localized to ``ui_language``.
    """
    members = _collection_members(cursor, cid)
    idx = next((i for i, r in enumerate(members) if _member_matches(r, entity_type, entity_id)), -1)
    if idx < 0:
        return None
    cursor.execute(
        "SELECT COLLECTION_NAME, COLLECTION_NAME_FR FROM T_WC_T2S_COLLECTION WHERE ID_T2S_COLLECTION = %s",
        (cid,),
    )
    row = cursor.fetchone() or {}
    collection_name = row.get("COLLECTION_NAME")
    if ui_language != "en" and (row.get("COLLECTION_NAME_FR") or "").strip():
        collection_name = row.get("COLLECTION_NAME_FR")
    collection_items = []
    for i, r in enumerate(members):
        item = dict(r)
        item["IS_CURRENT"] = (i == idx)
        collection_items.append(item)
    return {
        "ID_T2S_COLLECTION": cid,
        "collection_name": collection_name,
        "collection_movies": collection_items,
        "collection_previous": collection_items[idx - 1] if idx > 0 else None,
        "collection_next": collection_items[idx + 1] if idx < len(members) - 1 else None,
    }


def _all_collection_contexts(cursor, entity_type, entity_id, ui_language="en"):
    """Every T2S collection the (movie|serie) belongs to, one cross-type chronological
    context each (FASTAPI-TEXT2SQL-153). A movie/serie can be in SEVERAL collections
    (visible on ``movie.php``/``serie.php``); this returns them all so a consumer can render
    one rail per collection. Each item is the dict from :func:`_collection_context_for`.

    Ordered **most-specific-first** (FASTAPI-TEXT2SQL-159): the collection with the FEWEST
    members leads — a trilogy (3) before a franchise before a universe (109) — so the tight,
    useful collection is the primary the backward-compat ``collection_*`` fields expose.
    Ties break by the soonest upcoming *next* release, then by membership order. ``[]`` when
    the entity is in no collection.
    """
    membership_table = "T_WC_T2S_MOVIE_COLLECTION" if entity_type == "movie" else "T_WC_T2S_SERIE_COLLECTION"
    membership_id = "ID_MOVIE" if entity_type == "movie" else "ID_SERIE"
    cursor.execute(
        f"SELECT ID_T2S_COLLECTION FROM {membership_table} WHERE {membership_id} = %s AND DELETED = 0",
        (entity_id,),
    )
    collection_ids = [r["ID_T2S_COLLECTION"] for r in cursor.fetchall()]
    contexts = [
        ctx for cid in collection_ids
        if (ctx := _collection_context_for(cursor, entity_type, entity_id, cid, ui_language)) is not None
    ]
    if not contexts:
        return []
    # Most-specific-first (FASTAPI-TEXT2SQL-159): fewest members leads, so the primary
    # (contexts[0] = the backward-compat collection_* fields) is the tightest collection —
    # the Dark Knight trilogy (3), not the Batman universe (109). Tie-break: soonest upcoming
    # "next" (a missing/NULL next sinks within the tie), then stable membership order. The
    # bool guard on `next_date is None` keeps NULLs from being compared against date strings.
    def _specificity_key(ctx):
        member_count = len(ctx.get("collection_movies") or [])
        nxt = ctx.get("collection_next")
        next_date = nxt.get("DAT_RELEASE") if nxt else None
        return (member_count, next_date is None, next_date)
    contexts.sort(key=_specificity_key)
    return contexts


def _collection_context(cursor, entity_type, entity_id, ui_language="en"):
    """Backward-compat single-collection context: the PRIMARY of
    :func:`_all_collection_contexts` (the MOST SPECIFIC collection — fewest members —
    FASTAPI-TEXT2SQL-159). Returns
    ``(collection_name, collection_items, collection_previous, collection_next)``, all
    empty/None when the entity is in no collection.
    """
    contexts = _all_collection_contexts(cursor, entity_type, entity_id, ui_language)
    if not contexts:
        return None, [], None, None
    primary = contexts[0]
    return (
        primary["collection_name"],
        primary["collection_movies"],
        primary["collection_previous"],
        primary["collection_next"],
    )


def _hoist_collection_next_into_similar(data, pagination, collection_next, entity_type):
    """Belt-and-suspenders (FASTAPI-TEXT2SQL-150/-152): force the next member of the
    collection to the #1 entry of ``similar`` — but ONLY when it is the SAME type as the
    page entity, because ``similar`` is a same-type neighbour list. A cross-type next
    (e.g. a series next on a movie page) is left as ``collection_next`` only, flagged
    ``IS_COLLECTION_NEXT``, for the front to surface separately; it is never injected into
    the same-type list. Hoist if TMDb already lists it as similar, else prepend and bump
    the pagination total. Shapes only the response; the read-model tables are untouched.
    """
    if not collection_next or collection_next.get("ENTITY_TYPE") != entity_type:
        return
    similar = data.get("similar")
    if not isinstance(similar, list):
        return
    id_key = "ID_MOVIE" if entity_type == "movie" else "ID_SERIE"
    title_key = "MOVIE_TITLE" if entity_type == "movie" else "SERIE_TITLE"
    title_fr_key = "MOVIE_TITLE_FR" if entity_type == "movie" else "SERIE_TITLE_FR"
    date_key = "DAT_RELEASE" if entity_type == "movie" else "DAT_FIRST_AIR"
    next_id = collection_next.get(id_key)
    remaining = [r for r in similar if r.get(id_key) != next_id]
    was_present = len(remaining) != len(similar)
    injected = {
        id_key: next_id,
        title_key: collection_next.get(title_key),
        title_fr_key: collection_next.get(title_fr_key),
        date_key: collection_next.get("DAT_RELEASE"),
        "IMDB_RATING_WEIGHTED": collection_next.get("IMDB_RATING_WEIGHTED"),
        "POSTER_PATH": collection_next.get("POSTER_PATH"),
        "DISPLAY_ORDER": 0,
        "IS_COLLECTION_NEXT": True,
    }
    data["similar"] = [injected] + remaining
    if not was_present and isinstance(pagination, dict) and isinstance(pagination.get("similar"), dict):
        pagination["similar"]["total"] = (pagination["similar"].get("total") or 0) + 1
        pagination["similar"]["returned"] = len(data["similar"])


@app.get("/movies/{id}", summary="Movie full detail")
async def get_movie(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a movie plus embedded relations: genres, production
    companies, production countries, spoken languages, topics, lists, collections,
    movements, technicals, awards, nominations, cast, and crew. The id is the TMDb
    movie ID (ID_MOVIE).

    similar and recommendations are the grounded TMDb neighbour movies (from
    T_WC_T2S_MOVIE_SIMILAR / T_WC_T2S_MOVIE_RECOMMENDATION): each element carries
    ID_MOVIE, MOVIE_TITLE (localized to ui_language), DAT_RELEASE,
    IMDB_RATING_WEIGHTED and POSTER_PATH, ordered by DISPLAY_ORDER (TMDb page-1
    rank). similar is content-based (genres + keywords), recommendations is
    behaviour-based; only neighbours present in the read-model are returned.

    collection_name and collection_movies describe the movie's T2S collection: the
    localized collection name, and every member of the collection in chronological
    (release-date) order. A T2S collection is cross-type — it can hold both movies AND
    series (e.g. Star Trek) — so collection_movies mixes both: each item carries
    ENTITY_TYPE ('movie' | 'serie'), ID_MOVIE + localized MOVIE_TITLE (movies) or ID_SERIE
    + localized SERIE_TITLE (series), DAT_RELEASE (series first-air aliased), POSTER_PATH,
    IMDB_RATING_WEIGHTED and an IS_CURRENT flag on this movie (collection_movies is [] when
    standalone). collection_previous and collection_next are the adjacent members (or null
    at the ends) and may themselves be a series. As a franchise belt-and-suspenders,
    collection_next is forced to the #1 position of similar ONLY when it is a movie
    (same-type); a cross-type next (a series) is left as collection_next only, flagged
    IS_COLLECTION_NEXT, never injected into the movie similar list.

    A movie can belong to SEVERAL T2S collections. collections_context is a list with one
    entry PER collection the movie is in, each carrying ID_T2S_COLLECTION, collection_name,
    collection_movies (cross-type members with IS_CURRENT), collection_previous and
    collection_next — so a consumer can render one rail per collection. The list is
    primary-first: entry [0] is the same collection the single collection_* fields above
    describe (backward-compat). collections_context is [] when the movie is standalone.

    Each nested list element carries the canonical image path of its related entity:
    PROFILE_PATH for cast/crew (persons); LOGO_PATH for companies; POSTER_PATH for
    topics, lists, collections, movements, awards, and nominations. Topics, lists,
    collections, movements, awards, nominations, and technicals also include
    WIKIPEDIA_IMAGE_PATH. Companies, topics, lists, collections, movements, and
    technicals also include IMDB_RATING_WEIGHTED and POPULARITY for the related
    entity. Technicals additionally expose DESCRIPTION (localized to ui_language) and
    TECHNICAL_TYPE (sound_system, color_technology, film_technology, sound_technology, film_format).

    genres is a list of objects (not bare ids): each carries ID_GENRE and GENRE_NAME
    (localized to ui_language via T_WC_TMDB_GENRE_LANG, English fallback), ordered by
    English name; ID_GENRE links to GET /genres/{ID_GENRE}.

    The posters and backdrops lists each contain every image of the matching type
    available for this movie from T_WC_T2S_MOVIE_IMAGE (TYPE_IMAGE = 'poster' for
    posters, 'backdrop' for backdrops), ordered by DISPLAY_ORDER; each element
    exposes ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE,
    VOTE_COUNT, DISPLAY_ORDER. When ui_language is not the default 'en', the
    top-level POSTER_PATH is overridden with the IMAGE_PATH of the main (lowest
    DISPLAY_ORDER) poster whose LANG matches ui_language, falling back to the
    canonical POSTER_PATH when no localized poster exists.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER.

    The videos list merges TMDb-sourced videos (T_WC_TMDB_MOVIE_VIDEO) and
    Wikidata-sourced videos (T_WC_WIKIDATA_MEDIA_RESOURCE with RESOURCE_KIND='video',
    joined via ID_WIKIDATA). Each element exposes a unified shape: SOURCE
    ('tmdb' / 'wikidata'), VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE, LANG,
    OFFICIAL (tmdb only), DAT_PUBLISHED (tmdb only), DURATION_SECONDS (wikidata only),
    WATCH_URL, EMBED_URL, FILE_URL, THUMBNAIL_URL, DISPLAY_ORDER. TMDb rows come
    first (OFFICIAL DESC, DISPLAY_ORDER ASC), then Wikidata rows
    (IS_PREFERRED_RESOURCE DESC, SOURCE_PRIORITY ASC); TMDb YouTube/Vimeo URLs are
    synthesized from VIDEO_SITE + VIDEO_KEY, Wikidata URLs are pivoted from
    T_WC_WIKIDATA_MEDIA_RESOURCE_URL by URL_TYPE."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_MOVIE WHERE ID_MOVIE = %s", (id,))
            movie = cursor.fetchone()
        if not movie:
            raise HTTPException(status_code=404, detail=f"Movie {id} not found")
        exclude_self_credits = movie.get("IS_DOCUMENTARY") != 1
        _cast_filter = (
            " AND pm.CAST_CHARACTER NOT IN (%s)" % ",".join(["%s"] * len(CAST_CHARACTER_EXCLUSIONS))
            if exclude_self_credits else ""
        )
        _cast_params = (id, *CAST_CHARACTER_EXCLUSIONS) if exclude_self_credits else (id,)
        pcollections = {
            "companies": ("""
                SELECT c.ID_COMPANY, c.COMPANY_NAME, c.LOGO_PATH, c.IMDB_RATING_WEIGHTED, c.POPULARITY,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_COMPANY mc
                JOIN T_WC_T2S_COMPANY c ON mc.ID_COMPANY = c.ID_COMPANY
                WHERE mc.ID_MOVIE = %s ORDER BY c.ID_COMPANY ASC
            """, (id,), None),
            "topics": ("""
                SELECT t.ID_TOPIC, t.TOPIC_NAME, t.TOPIC_NAME_FR, t.TOPIC_TYPE, t.POSTER_PATH, t.WIKIPEDIA_IMAGE_PATH,
                       t.IMDB_RATING_WEIGHTED, t.POPULARITY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_TOPIC mt
                JOIN T_WC_T2S_TOPIC t ON mt.ID_TOPIC = t.ID_TOPIC
                WHERE mt.ID_MOVIE = %s ORDER BY mt.DISPLAY_ORDER ASC, t.ID_TOPIC ASC
            """, (id,), None),
            "lists": ("""
                SELECT l.ID_T2S_LIST, l.LIST_NAME, l.LIST_NAME_FR, l.LIST_TYPE, l.POSTER_PATH, l.WIKIPEDIA_IMAGE_PATH,
                       l.IMDB_RATING_WEIGHTED, l.POPULARITY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_LIST ml
                JOIN T_WC_T2S_LIST l ON ml.ID_T2S_LIST = l.ID_T2S_LIST
                WHERE ml.ID_MOVIE = %s ORDER BY ml.DISPLAY_ORDER ASC, l.ID_T2S_LIST ASC
            """, (id,), None),
            "collections": ("""
                SELECT c.ID_T2S_COLLECTION, c.COLLECTION_NAME, c.COLLECTION_NAME_FR, c.POSTER_PATH, c.WIKIPEDIA_IMAGE_PATH,
                       c.IMDB_RATING_WEIGHTED, c.POPULARITY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_COLLECTION mc
                JOIN T_WC_T2S_COLLECTION c ON mc.ID_T2S_COLLECTION = c.ID_T2S_COLLECTION
                WHERE mc.ID_MOVIE = %s ORDER BY mc.DISPLAY_ORDER ASC, c.ID_T2S_COLLECTION ASC
            """, (id,), None),
            "movements": ("""
                SELECT m.ID_MOVEMENT, m.MOVEMENT_NAME, m.MOVEMENT_NAME_FR, m.POSTER_PATH, m.WIKIPEDIA_IMAGE_PATH,
                       m.IMDB_RATING_WEIGHTED, m.POPULARITY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_MOVEMENT mm
                JOIN T_WC_T2S_MOVEMENT m ON mm.ID_MOVEMENT = m.ID_MOVEMENT
                WHERE mm.ID_MOVIE = %s ORDER BY mm.DISPLAY_ORDER ASC, m.ID_MOVEMENT ASC
            """, (id,), None),
            "technicals": ("""
                SELECT t.ID_TECHNICAL, t.DESCRIPTION, t.DESCRIPTION_FR, t.TECHNICAL_TYPE,
                       t.WIKIPEDIA_IMAGE_PATH, t.IMDB_RATING_WEIGHTED, t.POPULARITY,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_TECHNICAL mt
                JOIN T_WC_T2S_TECHNICAL t ON mt.ID_TECHNICAL = t.ID_TECHNICAL
                WHERE mt.ID_MOVIE = %s ORDER BY mt.DISPLAY_ORDER ASC, t.ID_TECHNICAL ASC
            """, (id,), None),
            "awards": ("""
                SELECT a.ID_AWARD, a.AWARD_NAME, a.AWARD_NAME_FR, a.POSTER_PATH, a.WIKIPEDIA_IMAGE_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_AWARD ma
                JOIN T_WC_T2S_AWARD a ON ma.ID_AWARD = a.ID_AWARD
                WHERE ma.ID_MOVIE = %s ORDER BY ma.DISPLAY_ORDER ASC, a.ID_AWARD ASC
            """, (id,), None),
            "nominations": ("""
                SELECT n.ID_NOMINATION, n.NOMINATION_NAME, n.NOMINATION_NAME_FR, n.POSTER_PATH, n.WIKIPEDIA_IMAGE_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_NOMINATION mn
                JOIN T_WC_T2S_NOMINATION n ON mn.ID_NOMINATION = n.ID_NOMINATION
                WHERE mn.ID_MOVIE = %s ORDER BY mn.DISPLAY_ORDER ASC, n.ID_NOMINATION ASC
            """, (id,), None),
            "cast": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH,
                       MAX(pm.CREDIT_TYPE) AS CREDIT_TYPE,
                       GROUP_CONCAT(DISTINCT pm.CAST_CHARACTER SEPARATOR ', ') AS CAST_CHARACTER,
                       GROUP_CONCAT(DISTINCT pm.CREW_DEPARTMENT SEPARATOR ', ') AS CREW_DEPARTMENT,
                       GROUP_CONCAT(DISTINCT pm.CREW_JOB SEPARATOR ', ') AS CREW_JOB,
                       MIN(pm.DISPLAY_ORDER) AS DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_MOVIE pm
                JOIN T_WC_T2S_PERSON p ON pm.ID_PERSON = p.ID_PERSON
                WHERE pm.ID_MOVIE = %s AND pm.CREDIT_TYPE = 'cast'""" + _cast_filter + """
                GROUP BY p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH
                ORDER BY MIN(pm.DISPLAY_ORDER) ASC, p.ID_PERSON ASC
            """, _cast_params, "person"),
            "crew": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH,
                       MAX(pm.CREDIT_TYPE) AS CREDIT_TYPE,
                       GROUP_CONCAT(DISTINCT pm.CAST_CHARACTER SEPARATOR ', ') AS CAST_CHARACTER,
                       GROUP_CONCAT(DISTINCT pm.CREW_DEPARTMENT SEPARATOR ', ') AS CREW_DEPARTMENT,
                       GROUP_CONCAT(DISTINCT pm.CREW_JOB SEPARATOR ', ') AS CREW_JOB,
                       MIN(pm.DISPLAY_ORDER) AS DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_MOVIE pm
                JOIN T_WC_T2S_PERSON p ON pm.ID_PERSON = p.ID_PERSON
                WHERE pm.ID_MOVIE = %s AND pm.CREDIT_TYPE = 'crew'
                GROUP BY p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH
                ORDER BY MIN(pm.DISPLAY_ORDER) ASC, p.ID_PERSON ASC
            """, (id,), "person"),
            "similar": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, ms.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_SIMILAR ms
                JOIN T_WC_T2S_MOVIE m ON ms.ID_MOVIE_SIMILAR = m.ID_MOVIE
                WHERE ms.ID_MOVIE = %s ORDER BY ms.DISPLAY_ORDER ASC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "recommendations": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, mr.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_RECOMMENDATION mr
                JOIN T_WC_T2S_MOVIE m ON mr.ID_MOVIE_RECOMMENDED = m.ID_MOVIE
                WHERE mr.ID_MOVIE = %s ORDER BY mr.DISPLAY_ORDER ASC, m.ID_MOVIE ASC
            """, (id,), "movie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                cursor.execute("""
                    SELECT g.id AS ID_GENRE, g.name AS GENRE_NAME, gl.name AS GENRE_NAME_FR
                    FROM T_WC_T2S_MOVIE_GENRE mg
                    JOIN T_WC_TMDB_GENRE g ON g.id = mg.ID_GENRE
                    LEFT JOIN T_WC_TMDB_GENRE_LANG gl ON gl.id = g.id AND gl.LANG = 'fr'
                    WHERE mg.ID_MOVIE = %s
                    ORDER BY g.name ASC
                """, (id,))
                genres = cursor.fetchall()
                cursor.execute("SELECT COUNTRY_CODE FROM T_WC_T2S_MOVIE_PRODUCTION_COUNTRY WHERE ID_MOVIE = %s", (id,))
                production_countries = [r["COUNTRY_CODE"] for r in cursor.fetchall()]
                cursor.execute("SELECT SPOKEN_LANGUAGE FROM T_WC_T2S_MOVIE_SPOKEN_LANGUAGE WHERE ID_MOVIE = %s", (id,))
                spoken_languages = [r["SPOKEN_LANGUAGE"] for r in cursor.fetchall()]
                cursor.execute("""
                    SELECT ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT,
                           VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER
                    FROM T_WC_T2S_MOVIE_IMAGE
                    WHERE ID_MOVIE = %s AND TYPE_IMAGE = 'poster'
                    ORDER BY DISPLAY_ORDER ASC
                """, (id,))
                posters = cursor.fetchall()
                cursor.execute("""
                    SELECT ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT,
                           VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER
                    FROM T_WC_T2S_MOVIE_IMAGE
                    WHERE ID_MOVIE = %s AND TYPE_IMAGE = 'backdrop'
                    ORDER BY DISPLAY_ORDER ASC
                """, (id,))
                backdrops = cursor.fetchall()
                wikipedia_images = _fetch_wikipedia_images(cursor, movie.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, movie.get("ID_WIKIDATA"), ui_language)
                videos = _fetch_tmdb_videos(cursor, "movie", id) + _fetch_wikidata_videos(cursor, movie.get("ID_WIKIDATA"))
                collection_contexts = _all_collection_contexts(cursor, "movie", id, ui_language)
                _primary_collection = collection_contexts[0] if collection_contexts else None
                collection_name = _primary_collection["collection_name"] if _primary_collection else None
                collection_movies = _primary_collection["collection_movies"] if _primary_collection else []
                collection_previous = _primary_collection["collection_previous"] if _primary_collection else None
                collection_next = _primary_collection["collection_next"] if _primary_collection else None
                _hoist_collection_next_into_similar(data, pagination, collection_next, "movie")
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {
            **movie,
            "genres": genres,
            "companies": data["companies"],
            "production_countries": production_countries,
            "spoken_languages": spoken_languages,
            "topics": data["topics"],
            "lists": data["lists"],
            "collections": data["collections"],
            "movements": data["movements"],
            "technicals": data["technicals"],
            "awards": data["awards"],
            "nominations": data["nominations"],
            "cast": data["cast"],
            "crew": data["crew"],
            "similar": data["similar"],
            "recommendations": data["recommendations"],
            "collection_name": collection_name,
            "collection_movies": collection_movies,
            "collection_previous": collection_previous,
            "collection_next": collection_next,
            # FASTAPI-TEXT2SQL-153: one context per collection the entity belongs to (the
            # collection_* fields above remain the PRIMARY one, for backward-compat).
            "collections_context": collection_contexts,
            "posters": list(posters),
            "backdrops": list(backdrops),
            "wikipedia_images": wikipedia_images,
            "wikipedia_content": wikipedia_content,
            "videos": videos,
            "pagination": pagination,
        }
        logs.log_usage("movies", {"id": id, "response": result}, strapiversion)
        apply_localized_main_image(result, posters, "POSTER_PATH", ui_language)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        apply_localized_text(result, conn, "T_WC_T2S_MOVIE_LANG", "ID_MOVIE", id, ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/series/{id}", summary="TV series full detail")
async def get_series(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a TV series plus embedded relations: genres, production
    companies, networks, production countries, spoken languages, topics, lists,
    collections, movements, awards, nominations, cast, and crew. The id is the TMDb
    series ID (ID_SERIE).

    similar and recommendations are the grounded TMDb neighbour series (from
    T_WC_T2S_SERIE_SIMILAR / T_WC_T2S_SERIE_RECOMMENDATION): each element carries
    ID_SERIE, SERIE_TITLE (localized to ui_language), DAT_FIRST_AIR,
    IMDB_RATING_WEIGHTED and POSTER_PATH, ordered by DISPLAY_ORDER (TMDb page-1
    rank). similar is content-based, recommendations is behaviour-based; only
    neighbours present in the read-model are returned.

    collection_name and collection_movies describe the series' T2S collection: the
    localized collection name, and every member in chronological (release-date) order. A
    T2S collection is cross-type — it can hold both series AND movies (e.g. Star Trek) — so
    collection_movies mixes both: each item carries ENTITY_TYPE ('movie' | 'serie'),
    ID_SERIE + localized SERIE_TITLE (series) or ID_MOVIE + localized MOVIE_TITLE (movies),
    DAT_RELEASE (series first-air aliased), POSTER_PATH, IMDB_RATING_WEIGHTED and an
    IS_CURRENT flag on this series (collection_movies is [] when standalone).
    collection_previous and collection_next are the adjacent members (or null at the ends)
    and may themselves be a movie. As a belt-and-suspenders, collection_next is forced to
    the #1 position of similar ONLY when it is a series (same-type); a cross-type next (a
    movie) is left as collection_next only, flagged IS_COLLECTION_NEXT, never injected into
    the series similar list.

    A series can belong to SEVERAL T2S collections. collections_context is a list with one
    entry PER collection the series is in, each carrying ID_T2S_COLLECTION, collection_name,
    collection_movies (cross-type members with IS_CURRENT), collection_previous and
    collection_next — so a consumer can render one rail per collection. The list is
    primary-first: entry [0] is the same collection the single collection_* fields above
    describe (backward-compat). collections_context is [] when the series is standalone.

    Each nested list element carries the canonical image path of its related entity:
    PROFILE_PATH for cast/crew (persons); LOGO_PATH for companies and networks;
    POSTER_PATH for topics, lists, collections, movements, awards, and nominations.
    Topics, lists, collections, movements, awards, and nominations also include
    WIKIPEDIA_IMAGE_PATH. Companies, topics, lists, collections, and movements also
    include IMDB_RATING_WEIGHTED and POPULARITY for the related entity.

    genres is a list of objects (not bare ids): each carries ID_GENRE and GENRE_NAME
    (localized to ui_language via T_WC_TMDB_GENRE_LANG, English fallback), ordered by
    English name; ID_GENRE links to GET /genres/{ID_GENRE}.

    The posters and backdrops lists each contain every image of the matching type
    available for this series from T_WC_T2S_SERIE_IMAGE (TYPE_IMAGE = 'poster' for
    posters, 'backdrop' for backdrops), ordered by DISPLAY_ORDER; each element
    exposes ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE,
    VOTE_COUNT, DISPLAY_ORDER. When ui_language is not the default 'en', the
    top-level POSTER_PATH is overridden with the IMAGE_PATH of the main (lowest
    DISPLAY_ORDER) poster whose LANG matches ui_language, falling back to the
    canonical POSTER_PATH when no localized poster exists.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER.

    The seasons list contains every season of this series from T_WC_TMDB_SEASON,
    ordered by SEASON_NUMBER ASC; each element carries ID_SEASON, SEASON_NUMBER, TITLE,
    OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, POSTER_PATH, EPISODE_COUNT,
    VOTE_AVERAGE, ID_IMDB, ID_WIKIDATA, ID_TVDB.

    The videos list merges TMDb-sourced videos (T_WC_TMDB_SERIE_VIDEO) and
    Wikidata-sourced videos (T_WC_WIKIDATA_MEDIA_RESOURCE with RESOURCE_KIND='video',
    joined via ID_WIKIDATA). Each element exposes a unified shape: SOURCE
    ('tmdb' / 'wikidata'), VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE, LANG,
    OFFICIAL (tmdb only), DAT_PUBLISHED (tmdb only), DURATION_SECONDS (wikidata only),
    WATCH_URL, EMBED_URL, FILE_URL, THUMBNAIL_URL, DISPLAY_ORDER. TMDb rows come
    first (OFFICIAL DESC, DISPLAY_ORDER ASC), then Wikidata rows
    (IS_PREFERRED_RESOURCE DESC, SOURCE_PRIORITY ASC); TMDb YouTube/Vimeo URLs are
    synthesized from VIDEO_SITE + VIDEO_KEY, Wikidata URLs are pivoted from
    T_WC_WIKIDATA_MEDIA_RESOURCE_URL by URL_TYPE."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_SERIE WHERE ID_SERIE = %s", (id,))
            serie = cursor.fetchone()
        if not serie:
            raise HTTPException(status_code=404, detail=f"Series {id} not found")
        pcollections = {
            "companies": ("""
                SELECT c.ID_COMPANY, c.COMPANY_NAME, c.LOGO_PATH, c.IMDB_RATING_WEIGHTED, c.POPULARITY,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_COMPANY sc
                JOIN T_WC_T2S_COMPANY c ON sc.ID_COMPANY = c.ID_COMPANY
                WHERE sc.ID_SERIE = %s ORDER BY c.ID_COMPANY ASC
            """, (id,), None),
            "networks": ("""
                SELECT n.ID_NETWORK, n.NETWORK_NAME, n.LOGO_PATH, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_NETWORK sn
                JOIN T_WC_T2S_NETWORK n ON sn.ID_NETWORK = n.ID_NETWORK
                WHERE sn.ID_SERIE = %s ORDER BY n.ID_NETWORK ASC
            """, (id,), None),
            "topics": ("""
                SELECT t.ID_TOPIC, t.TOPIC_NAME, t.TOPIC_NAME_FR, t.TOPIC_TYPE, t.POSTER_PATH, t.WIKIPEDIA_IMAGE_PATH,
                       t.IMDB_RATING_WEIGHTED, t.POPULARITY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_TOPIC st
                JOIN T_WC_T2S_TOPIC t ON st.ID_TOPIC = t.ID_TOPIC
                WHERE st.ID_SERIE = %s ORDER BY st.DISPLAY_ORDER ASC, t.ID_TOPIC ASC
            """, (id,), None),
            "lists": ("""
                SELECT l.ID_T2S_LIST, l.LIST_NAME, l.LIST_NAME_FR, l.LIST_TYPE, l.POSTER_PATH, l.WIKIPEDIA_IMAGE_PATH,
                       l.IMDB_RATING_WEIGHTED, l.POPULARITY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_LIST sl
                JOIN T_WC_T2S_LIST l ON sl.ID_T2S_LIST = l.ID_T2S_LIST
                WHERE sl.ID_SERIE = %s ORDER BY sl.DISPLAY_ORDER ASC, l.ID_T2S_LIST ASC
            """, (id,), None),
            "collections": ("""
                SELECT c.ID_T2S_COLLECTION, c.COLLECTION_NAME, c.COLLECTION_NAME_FR, c.POSTER_PATH, c.WIKIPEDIA_IMAGE_PATH,
                       c.IMDB_RATING_WEIGHTED, c.POPULARITY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_COLLECTION sc
                JOIN T_WC_T2S_COLLECTION c ON sc.ID_T2S_COLLECTION = c.ID_T2S_COLLECTION
                WHERE sc.ID_SERIE = %s ORDER BY sc.DISPLAY_ORDER ASC, c.ID_T2S_COLLECTION ASC
            """, (id,), None),
            "movements": ("""
                SELECT m.ID_MOVEMENT, m.MOVEMENT_NAME, m.MOVEMENT_NAME_FR, m.POSTER_PATH, m.WIKIPEDIA_IMAGE_PATH,
                       m.IMDB_RATING_WEIGHTED, m.POPULARITY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_MOVEMENT sm
                JOIN T_WC_T2S_MOVEMENT m ON sm.ID_MOVEMENT = m.ID_MOVEMENT
                WHERE sm.ID_SERIE = %s ORDER BY sm.DISPLAY_ORDER ASC, m.ID_MOVEMENT ASC
            """, (id,), None),
            "awards": ("""
                SELECT a.ID_AWARD, a.AWARD_NAME, a.AWARD_NAME_FR, a.POSTER_PATH, a.WIKIPEDIA_IMAGE_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_AWARD sa
                JOIN T_WC_T2S_AWARD a ON sa.ID_AWARD = a.ID_AWARD
                WHERE sa.ID_SERIE = %s ORDER BY sa.DISPLAY_ORDER ASC, a.ID_AWARD ASC
            """, (id,), None),
            "nominations": ("""
                SELECT n.ID_NOMINATION, n.NOMINATION_NAME, n.NOMINATION_NAME_FR, n.POSTER_PATH, n.WIKIPEDIA_IMAGE_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_NOMINATION sn
                JOIN T_WC_T2S_NOMINATION n ON sn.ID_NOMINATION = n.ID_NOMINATION
                WHERE sn.ID_SERIE = %s ORDER BY sn.DISPLAY_ORDER ASC, n.ID_NOMINATION ASC
            """, (id,), None),
            "cast": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH,
                       MAX(ps.CREDIT_TYPE) AS CREDIT_TYPE,
                       GROUP_CONCAT(DISTINCT ps.CAST_CHARACTER SEPARATOR ', ') AS CAST_CHARACTER,
                       GROUP_CONCAT(DISTINCT ps.CREW_DEPARTMENT SEPARATOR ', ') AS CREW_DEPARTMENT,
                       MIN(ps.DISPLAY_ORDER) AS DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_SERIE ps
                JOIN T_WC_T2S_PERSON p ON ps.ID_PERSON = p.ID_PERSON
                WHERE ps.ID_SERIE = %s AND ps.CREDIT_TYPE = 'cast'
                GROUP BY p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH
                ORDER BY MIN(ps.DISPLAY_ORDER) ASC, p.ID_PERSON ASC
            """, (id,), "person"),
            "crew": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH,
                       MAX(ps.CREDIT_TYPE) AS CREDIT_TYPE,
                       GROUP_CONCAT(DISTINCT ps.CAST_CHARACTER SEPARATOR ', ') AS CAST_CHARACTER,
                       GROUP_CONCAT(DISTINCT ps.CREW_DEPARTMENT SEPARATOR ', ') AS CREW_DEPARTMENT,
                       MIN(ps.DISPLAY_ORDER) AS DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_SERIE ps
                JOIN T_WC_T2S_PERSON p ON ps.ID_PERSON = p.ID_PERSON
                WHERE ps.ID_SERIE = %s AND ps.CREDIT_TYPE = 'crew'
                GROUP BY p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH
                ORDER BY MIN(ps.DISPLAY_ORDER) ASC, p.ID_PERSON ASC
            """, (id,), "person"),
            "seasons": ("""
                SELECT ID_SEASON, SEASON_NUMBER, TITLE, OVERVIEW, DAT_AIR,
                       AIR_YEAR, AIR_MONTH, AIR_DAY, POSTER_PATH, EPISODE_COUNT,
                       VOTE_AVERAGE, ID_IMDB, ID_WIKIDATA, ID_TVDB,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_TMDB_SEASON
                WHERE ID_SERIE = %s
                ORDER BY SEASON_NUMBER ASC
            """, (id,), "season"),
            "similar": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH, ss.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_SIMILAR ss
                JOIN T_WC_T2S_SERIE s ON ss.ID_SERIE_SIMILAR = s.ID_SERIE
                WHERE ss.ID_SERIE = %s ORDER BY ss.DISPLAY_ORDER ASC, s.ID_SERIE ASC
            """, (id,), "serie"),
            "recommendations": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH, sr.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_RECOMMENDATION sr
                JOIN T_WC_T2S_SERIE s ON sr.ID_SERIE_RECOMMENDED = s.ID_SERIE
                WHERE sr.ID_SERIE = %s ORDER BY sr.DISPLAY_ORDER ASC, s.ID_SERIE ASC
            """, (id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                cursor.execute("""
                    SELECT g.id AS ID_GENRE, g.name AS GENRE_NAME, gl.name AS GENRE_NAME_FR
                    FROM T_WC_T2S_SERIE_GENRE sg
                    JOIN T_WC_TMDB_GENRE g ON g.id = sg.ID_GENRE
                    LEFT JOIN T_WC_TMDB_GENRE_LANG gl ON gl.id = g.id AND gl.LANG = 'fr'
                    WHERE sg.ID_SERIE = %s
                    ORDER BY g.name ASC
                """, (id,))
                genres = cursor.fetchall()
                cursor.execute("SELECT COUNTRY_CODE FROM T_WC_T2S_SERIE_PRODUCTION_COUNTRY WHERE ID_SERIE = %s", (id,))
                production_countries = [r["COUNTRY_CODE"] for r in cursor.fetchall()]
                cursor.execute("SELECT SPOKEN_LANGUAGE FROM T_WC_T2S_SERIE_SPOKEN_LANGUAGE WHERE ID_SERIE = %s", (id,))
                spoken_languages = [r["SPOKEN_LANGUAGE"] for r in cursor.fetchall()]
                cursor.execute("""
                    SELECT ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT,
                           VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER
                    FROM T_WC_T2S_SERIE_IMAGE
                    WHERE ID_SERIE = %s AND TYPE_IMAGE = 'poster'
                    ORDER BY DISPLAY_ORDER ASC
                """, (id,))
                posters = cursor.fetchall()
                cursor.execute("""
                    SELECT ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT,
                           VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER
                    FROM T_WC_T2S_SERIE_IMAGE
                    WHERE ID_SERIE = %s AND TYPE_IMAGE = 'backdrop'
                    ORDER BY DISPLAY_ORDER ASC
                """, (id,))
                backdrops = cursor.fetchall()
                wikipedia_images = _fetch_wikipedia_images(cursor, serie.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, serie.get("ID_WIKIDATA"), ui_language)
                videos = _fetch_tmdb_videos(cursor, "serie", id) + _fetch_wikidata_videos(cursor, serie.get("ID_WIKIDATA"))
                collection_contexts = _all_collection_contexts(cursor, "serie", id, ui_language)
                _primary_collection = collection_contexts[0] if collection_contexts else None
                collection_name = _primary_collection["collection_name"] if _primary_collection else None
                collection_movies = _primary_collection["collection_movies"] if _primary_collection else []
                collection_previous = _primary_collection["collection_previous"] if _primary_collection else None
                collection_next = _primary_collection["collection_next"] if _primary_collection else None
                _hoist_collection_next_into_similar(data, pagination, collection_next, "serie")
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {
            **serie,
            "genres": genres,
            "companies": data["companies"],
            "networks": data["networks"],
            "production_countries": production_countries,
            "spoken_languages": spoken_languages,
            "topics": data["topics"],
            "lists": data["lists"],
            "collections": data["collections"],
            "movements": data["movements"],
            "awards": data["awards"],
            "nominations": data["nominations"],
            "cast": data["cast"],
            "crew": data["crew"],
            "similar": data["similar"],
            "recommendations": data["recommendations"],
            "collection_name": collection_name,
            "collection_movies": collection_movies,
            "collection_previous": collection_previous,
            "collection_next": collection_next,
            # FASTAPI-TEXT2SQL-153: one context per collection the entity belongs to (the
            # collection_* fields above remain the PRIMARY one, for backward-compat).
            "collections_context": collection_contexts,
            "posters": list(posters),
            "backdrops": list(backdrops),
            "seasons": data["seasons"],
            "wikipedia_images": wikipedia_images,
            "wikipedia_content": wikipedia_content,
            "videos": videos,
            "pagination": pagination,
        }
        logs.log_usage("series", {"id": id, "response": result}, strapiversion)
        apply_localized_main_image(result, posters, "POSTER_PATH", ui_language)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        apply_localized_text(result, conn, "T_WC_T2S_SERIE_LANG", "ID_SERIE", id, ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/seasons/{id_serie}/{season_number}", summary="TV series season full detail")
async def get_season(id_serie: int, season_number: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a TV series season plus embedded relations: cast, crew,
    posters, backdrops, and a navigation stub for the parent series. The composite
    key is (ID_SERIE, SEASON_NUMBER); season 0 is the specials season when present.

    Cast/crew are grouped one row per person: a person crediting several
    characters or jobs appears once, with CAST_CHARACTER, CREW_DEPARTMENT and
    CREW_JOB comma-joined across their credits. Each element carries PROFILE_PATH
    for the person plus CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB,
    TOTAL_EPISODE_COUNT (the max across their credits), and DISPLAY_ORDER from
    T_WC_TMDB_PERSON_SEASON, ordered by the person's best (minimum) DISPLAY_ORDER.

    The posters and backdrops lists each contain every image of the matching type
    available for this season from T_WC_TMDB_SEASON_IMAGE (TYPE_IMAGE = 'poster' for
    posters, 'backdrop' for backdrops), ordered by DISPLAY_ORDER; each element
    exposes ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE,
    VOTE_COUNT, DISPLAY_ORDER. When ui_language is not the default 'en', the
    top-level POSTER_PATH is overridden with the IMAGE_PATH of the main (lowest
    DISPLAY_ORDER) poster whose LANG matches ui_language, falling back to the
    canonical POSTER_PATH when no localized poster exists.

    The series object is a navigation stub with ID_SERIE, SERIE_TITLE, POSTER_PATH
    so the frontend can render breadcrumbs without a second /series/{id} round trip.

    The episodes list contains every episode of this season from T_WC_TMDB_EPISODE,
    ordered by EPISODE_NUMBER ASC. Each element is a summary row that carries
    ID_EPISODE, EPISODE_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH,
    AIR_DAY, RUNTIME, EPISODE_TYPE, STILL_PATH, VOTE_AVERAGE, VOTE_COUNT, ID_IMDB,
    ID_WIKIDATA, and ID_TVDB. Episode cast/crew, additional stills, and Wikipedia
    payloads live on /episodes/{id_serie}/{season_number}/{episode_number} to keep
    the season payload bounded.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER.

    The videos list contains TMDb-sourced videos for this season from
    T_WC_TMDB_SEASON_VIDEO (no Wikidata media is modeled at the season level). Each
    element exposes the unified shape: SOURCE='tmdb', VIDEO_KEY, VIDEO_NAME,
    VIDEO_SITE, VIDEO_TYPE, LANG, OFFICIAL, DAT_PUBLISHED, WATCH_URL, EMBED_URL,
    THUMBNAIL_URL, DISPLAY_ORDER. WATCH/EMBED/THUMBNAIL URLs are synthesized from
    VIDEO_SITE + VIDEO_KEY (YouTube and Vimeo). Sorted OFFICIAL DESC then
    DISPLAY_ORDER ASC.

    Note: this endpoint reads from T_WC_TMDB_SEASON, T_WC_TMDB_PERSON_SEASON,
    T_WC_TMDB_SEASON_IMAGE, and T_WC_TMDB_EPISODE because the T_WC_T2S_*
    equivalents do not exist yet. Registered as migration sites in
    SEASONS_AND_EPISODES.md section 6.1."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM T_WC_TMDB_SEASON WHERE ID_SERIE = %s AND SEASON_NUMBER = %s",
                (id_serie, season_number),
            )
            season = cursor.fetchone()
        if not season:
            raise HTTPException(
                status_code=404,
                detail=f"Season {season_number} of series {id_serie} not found",
            )
        id_season = season["ID_SEASON"]
        pcollections = {
            "cast": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH,
                       MAX(ps.CREDIT_TYPE) AS CREDIT_TYPE,
                       GROUP_CONCAT(DISTINCT ps.CAST_CHARACTER SEPARATOR ', ') AS CAST_CHARACTER,
                       GROUP_CONCAT(DISTINCT ps.CREW_DEPARTMENT SEPARATOR ', ') AS CREW_DEPARTMENT,
                       GROUP_CONCAT(DISTINCT ps.CREW_JOB SEPARATOR ', ') AS CREW_JOB,
                       MAX(ps.TOTAL_EPISODE_COUNT) AS TOTAL_EPISODE_COUNT,
                       MIN(ps.DISPLAY_ORDER) AS DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_TMDB_PERSON_SEASON ps
                JOIN T_WC_T2S_PERSON p ON ps.ID_PERSON = p.ID_PERSON
                WHERE ps.ID_SEASON = %s AND ps.CREDIT_TYPE = 'cast'
                GROUP BY p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH
                ORDER BY MIN(ps.DISPLAY_ORDER) ASC, p.ID_PERSON ASC
            """, (id_season,), "person"),
            "crew": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH,
                       MAX(ps.CREDIT_TYPE) AS CREDIT_TYPE,
                       GROUP_CONCAT(DISTINCT ps.CAST_CHARACTER SEPARATOR ', ') AS CAST_CHARACTER,
                       GROUP_CONCAT(DISTINCT ps.CREW_DEPARTMENT SEPARATOR ', ') AS CREW_DEPARTMENT,
                       GROUP_CONCAT(DISTINCT ps.CREW_JOB SEPARATOR ', ') AS CREW_JOB,
                       MAX(ps.TOTAL_EPISODE_COUNT) AS TOTAL_EPISODE_COUNT,
                       MIN(ps.DISPLAY_ORDER) AS DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_TMDB_PERSON_SEASON ps
                JOIN T_WC_T2S_PERSON p ON ps.ID_PERSON = p.ID_PERSON
                WHERE ps.ID_SEASON = %s AND ps.CREDIT_TYPE = 'crew'
                GROUP BY p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH
                ORDER BY MIN(ps.DISPLAY_ORDER) ASC, p.ID_PERSON ASC
            """, (id_season,), "person"),
            "episodes": ("""
                SELECT ID_EPISODE, EPISODE_NUMBER, TITLE, OVERVIEW, DAT_AIR,
                       AIR_YEAR, AIR_MONTH, AIR_DAY, RUNTIME, EPISODE_TYPE,
                       STILL_PATH, VOTE_AVERAGE, VOTE_COUNT,
                       ID_IMDB, ID_WIKIDATA, ID_TVDB,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_TMDB_EPISODE
                WHERE ID_SEASON = %s
                ORDER BY EPISODE_NUMBER ASC
            """, (id_season,), None),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                cursor.execute("""
                    SELECT ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT,
                           VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER
                    FROM T_WC_TMDB_SEASON_IMAGE
                    WHERE ID_SEASON = %s AND TYPE_IMAGE = 'poster'
                    ORDER BY DISPLAY_ORDER ASC
                """, (id_season,))
                posters = cursor.fetchall()
                cursor.execute("""
                    SELECT ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT,
                           VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER
                    FROM T_WC_TMDB_SEASON_IMAGE
                    WHERE ID_SEASON = %s AND TYPE_IMAGE = 'backdrop'
                    ORDER BY DISPLAY_ORDER ASC
                """, (id_season,))
                backdrops = cursor.fetchall()
                cursor.execute("""
                    SELECT ID_SERIE, SERIE_TITLE, SERIE_TITLE_FR, POSTER_PATH
                    FROM T_WC_T2S_SERIE WHERE ID_SERIE = %s
                """, (id_serie,))
                series = cursor.fetchone()
                wikipedia_images = _fetch_wikipedia_images(cursor, season.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, season.get("ID_WIKIDATA"), ui_language)
                videos = _fetch_tmdb_videos(cursor, "season", id_season)
        if collection is not None:
            return _targeted_collection_response(
                conn, {"id_serie": id_serie, "season_number": season_number}, collection, data, pagination, kinds, ui_language
            )
        result = {
            **season,
            "cast": data["cast"],
            "crew": data["crew"],
            "posters": list(posters),
            "backdrops": list(backdrops),
            "series": series,
            "episodes": data["episodes"],
            "wikipedia_images": wikipedia_images,
            "wikipedia_content": wikipedia_content,
            "videos": videos,
            "pagination": pagination,
        }
        logs.log_usage(
            "seasons",
            {"id_serie": id_serie, "season_number": season_number, "response": result},
            strapiversion,
        )
        apply_localized_main_image(result, posters, "POSTER_PATH", ui_language)
        groups = _localized_image_groups(data, kinds)
        groups.setdefault("serie", []).append(result["series"])
        apply_localized_related_images(conn, groups, ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get(
    "/episodes/{id_serie}/{season_number}/{episode_number}",
    summary="TV series episode full detail",
)
async def get_episode(
    id_serie: int,
    season_number: int,
    episode_number: int,
    ui_language: Optional[str] = "en",
    collection: Optional[str] = None,
    page: int = 1,
    rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT,
    api_key: str = Depends(get_api_key),
):
    """Return all fields for a TV series episode plus embedded relations: cast, crew,
    stills, navigation stubs for the parent season and series, and Wikipedia images
    and content when the episode has an `ID_WIKIDATA`. The composite key is
    (ID_SERIE, SEASON_NUMBER, EPISODE_NUMBER).

    Episodes carry their canonical frame as `STILL_PATH` directly on the base row
    (no separate poster table); the `stills` list exposes additional frames stored
    in T_WC_TMDB_EPISODE_IMAGE.

    Cast/crew are grouped one row per person: a person crediting several
    characters or jobs appears once, with CAST_CHARACTER, CREW_DEPARTMENT and
    CREW_JOB comma-joined across their credits. Each element carries PROFILE_PATH
    for the person plus CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, and
    DISPLAY_ORDER from T_WC_TMDB_PERSON_EPISODE, ordered by the person's best
    (minimum) DISPLAY_ORDER.

    The stills list contains every image attached to this episode from
    T_WC_TMDB_EPISODE_IMAGE, ordered by DISPLAY_ORDER; each element exposes ID_ROW,
    TYPE_IMAGE, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE,
    VOTE_COUNT, DISPLAY_ORDER. TMDb episodes typically only have still frames, but
    any other TYPE_IMAGE rows present upstream are returned as-is.

    The season object is a navigation stub with ID_SEASON, SEASON_NUMBER, TITLE,
    POSTER_PATH so the frontend can render breadcrumbs without a second
    /seasons/{id_serie}/{season_number} round trip.

    The series object is a navigation stub with ID_SERIE, SERIE_TITLE, POSTER_PATH.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER. Most
    episodes do not have an ID_WIKIDATA, in which case this list is empty.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER. Empty when ID_WIKIDATA is
    NULL.

    The videos list contains TMDb-sourced videos for this episode from
    T_WC_TMDB_EPISODE_VIDEO (no Wikidata media is modeled at the episode level). Each
    element exposes the unified shape: SOURCE='tmdb', VIDEO_KEY, VIDEO_NAME,
    VIDEO_SITE, VIDEO_TYPE, LANG, OFFICIAL, DAT_PUBLISHED, WATCH_URL, EMBED_URL,
    THUMBNAIL_URL, DISPLAY_ORDER. WATCH/EMBED/THUMBNAIL URLs are synthesized from
    VIDEO_SITE + VIDEO_KEY (YouTube and Vimeo). Sorted OFFICIAL DESC then
    DISPLAY_ORDER ASC.

    Note: this endpoint reads from T_WC_TMDB_EPISODE, T_WC_TMDB_PERSON_EPISODE, and
    T_WC_TMDB_EPISODE_IMAGE because the T_WC_T2S_* equivalents do not exist yet.
    Registered as a migration site in SEASONS_AND_EPISODES.md section 6.1."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM T_WC_TMDB_EPISODE
                WHERE ID_SERIE = %s AND SEASON_NUMBER = %s AND EPISODE_NUMBER = %s
                """,
                (id_serie, season_number, episode_number),
            )
            episode = cursor.fetchone()
        if not episode:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Episode {episode_number} of season {season_number} "
                    f"of series {id_serie} not found"
                ),
            )
        id_episode = episode["ID_EPISODE"]
        id_season = episode["ID_SEASON"]
        pcollections = {
            "cast": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH,
                       MAX(pe.CREDIT_TYPE) AS CREDIT_TYPE,
                       GROUP_CONCAT(DISTINCT pe.CAST_CHARACTER SEPARATOR ', ') AS CAST_CHARACTER,
                       GROUP_CONCAT(DISTINCT pe.CREW_DEPARTMENT SEPARATOR ', ') AS CREW_DEPARTMENT,
                       GROUP_CONCAT(DISTINCT pe.CREW_JOB SEPARATOR ', ') AS CREW_JOB,
                       MIN(pe.DISPLAY_ORDER) AS DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_TMDB_PERSON_EPISODE pe
                JOIN T_WC_T2S_PERSON p ON pe.ID_PERSON = p.ID_PERSON
                WHERE pe.ID_EPISODE = %s AND pe.CREDIT_TYPE = 'cast'
                GROUP BY p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH
                ORDER BY MIN(pe.DISPLAY_ORDER) ASC, p.ID_PERSON ASC
            """, (id_episode,), "person"),
            "crew": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH,
                       MAX(pe.CREDIT_TYPE) AS CREDIT_TYPE,
                       GROUP_CONCAT(DISTINCT pe.CAST_CHARACTER SEPARATOR ', ') AS CAST_CHARACTER,
                       GROUP_CONCAT(DISTINCT pe.CREW_DEPARTMENT SEPARATOR ', ') AS CREW_DEPARTMENT,
                       GROUP_CONCAT(DISTINCT pe.CREW_JOB SEPARATOR ', ') AS CREW_JOB,
                       MIN(pe.DISPLAY_ORDER) AS DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_TMDB_PERSON_EPISODE pe
                JOIN T_WC_T2S_PERSON p ON pe.ID_PERSON = p.ID_PERSON
                WHERE pe.ID_EPISODE = %s AND pe.CREDIT_TYPE = 'crew'
                GROUP BY p.ID_PERSON, p.PERSON_NAME, p.PROFILE_PATH
                ORDER BY MIN(pe.DISPLAY_ORDER) ASC, p.ID_PERSON ASC
            """, (id_episode,), "person"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                cursor.execute("""
                    SELECT ID_ROW, TYPE_IMAGE, IMAGE_PATH, LANG, ASPECT_RATIO,
                           WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER
                    FROM T_WC_TMDB_EPISODE_IMAGE
                    WHERE ID_EPISODE = %s
                    ORDER BY DISPLAY_ORDER ASC
                """, (id_episode,))
                stills = cursor.fetchall()
                cursor.execute("""
                    SELECT ID_SEASON, SEASON_NUMBER, TITLE, POSTER_PATH
                    FROM T_WC_TMDB_SEASON WHERE ID_SEASON = %s
                """, (id_season,))
                season = cursor.fetchone()
                cursor.execute("""
                    SELECT ID_SERIE, SERIE_TITLE, SERIE_TITLE_FR, POSTER_PATH
                    FROM T_WC_T2S_SERIE WHERE ID_SERIE = %s
                """, (id_serie,))
                series = cursor.fetchone()
                wikipedia_images = _fetch_wikipedia_images(cursor, episode.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, episode.get("ID_WIKIDATA"), ui_language)
                videos = _fetch_tmdb_videos(cursor, "episode", id_episode)
        if collection is not None:
            return _targeted_collection_response(
                conn,
                {"id_serie": id_serie, "season_number": season_number, "episode_number": episode_number},
                collection, data, pagination, kinds, ui_language,
            )
        result = {
            **episode,
            "cast": data["cast"],
            "crew": data["crew"],
            "stills": list(stills),
            "season": season,
            "series": series,
            "wikipedia_images": wikipedia_images,
            "wikipedia_content": wikipedia_content,
            "videos": videos,
            "pagination": pagination,
        }
        logs.log_usage(
            "episodes",
            {
                "id_serie": id_serie,
                "season_number": season_number,
                "episode_number": episode_number,
                "response": result,
            },
            strapiversion,
        )
        groups = _localized_image_groups(data, kinds)
        groups.setdefault("season", []).append(result["season"])
        groups.setdefault("serie", []).append(result["series"])
        apply_localized_related_images(conn, groups, ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/persons/{id}", summary="Person full detail")
async def get_person(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a person plus embedded relations: movie cast and crew,
    series cast and crew, groups, causes of death, awards, and nominations.
    The id is the TMDb person ID (ID_PERSON).
    Fields: ID_PERSON, PERSON_NAME, ID_IMDB, ID_WIKIDATA, BIOGRAPHY, BIRTH_YEAR,
    BIRTH_MONTH, BIRTH_DAY, DEATH_YEAR, DEATH_MONTH, DEATH_DAY, GENDER (1=female 2=male),
    PROFILE_PATH, COUNTRY_OF_BIRTH, POPULARITY, KNOWN_FOR_DEPARTMENT, WIKIDATA_NAME,
    ALIASES, INSTANCE_OF.

    Each nested list element carries the canonical image path of its related entity:
    POSTER_PATH for movie_cast/movie_crew (movies) and series_cast/series_crew (series);
    PROFILE_PATH for groups and deaths; POSTER_PATH for awards and nominations.
    Groups, deaths, awards, and nominations also include WIKIPEDIA_IMAGE_PATH.

    The portraits list contains every profile picture available for this person from
    T_WC_T2S_PERSON_IMAGE (TYPE_IMAGE = 'profile'), ordered by DISPLAY_ORDER; each
    element exposes ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT,
    VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER. When ui_language is not the default
    'en', the top-level PROFILE_PATH is overridden with the IMAGE_PATH of the main
    (lowest DISPLAY_ORDER) portrait whose LANG matches ui_language, falling back to
    the canonical PROFILE_PATH when no localized portrait exists.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER.

    The videos list contains Wikidata-sourced videos for this person from
    T_WC_WIKIDATA_MEDIA_RESOURCE (RESOURCE_KIND='video', joined via ID_WIKIDATA);
    TMDb does not store person-level videos. Each element exposes the unified shape:
    SOURCE='wikidata', VIDEO_KEY (SOURCE_IDENTIFIER), VIDEO_NAME (RESOURCE_TITLE),
    VIDEO_SITE (SOURCE_PLATFORM), VIDEO_TYPE (CONTENT_ROLE), LANG, DURATION_SECONDS,
    WATCH_URL, EMBED_URL, FILE_URL, THUMBNAIL_URL. URLs are pivoted from
    T_WC_WIKIDATA_MEDIA_RESOURCE_URL by URL_TYPE. Sorted IS_PREFERRED_RESOURCE DESC
    then SOURCE_PRIORITY ASC."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_PERSON WHERE ID_PERSON = %s", (id,))
            person = cursor.fetchone()
        if not person:
            raise HTTPException(status_code=404, detail=f"Person {id} not found")
        _excl_ph = ",".join(["%s"] * len(CAST_CHARACTER_EXCLUSIONS))
        pcollections = {
            "movie_cast": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED,
                       m.POSTER_PATH, m.IS_DOCUMENTARY, pm.CREDIT_TYPE, pm.CAST_CHARACTER,
                       pm.CREW_DEPARTMENT, pm.DISPLAY_ORDER, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_MOVIE pm
                JOIN T_WC_T2S_MOVIE m ON pm.ID_MOVIE = m.ID_MOVIE
                WHERE pm.ID_PERSON = %s AND pm.CREDIT_TYPE = 'cast'
                  AND NOT (m.IS_DOCUMENTARY <> 1 AND pm.CAST_CHARACTER IN (""" + _excl_ph + """))
                ORDER BY m.IMDB_RATING_WEIGHTED DESC, m.ID_MOVIE ASC
            """, (id, *CAST_CHARACTER_EXCLUSIONS), "movie"),
            "movie_crew": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED,
                       m.POSTER_PATH, m.IS_DOCUMENTARY, pm.CREDIT_TYPE, pm.CAST_CHARACTER,
                       pm.CREW_DEPARTMENT, pm.DISPLAY_ORDER, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_MOVIE pm
                JOIN T_WC_T2S_MOVIE m ON pm.ID_MOVIE = m.ID_MOVIE
                WHERE pm.ID_PERSON = %s AND pm.CREDIT_TYPE = 'crew'
                ORDER BY m.IMDB_RATING_WEIGHTED DESC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series_cast": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED,
                       s.POSTER_PATH, ps.CREDIT_TYPE, ps.CAST_CHARACTER, ps.CREW_DEPARTMENT,
                       ps.DISPLAY_ORDER, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_SERIE ps
                JOIN T_WC_T2S_SERIE s ON ps.ID_SERIE = s.ID_SERIE
                WHERE ps.ID_PERSON = %s AND ps.CREDIT_TYPE = 'cast'
                ORDER BY s.IMDB_RATING_WEIGHTED DESC, s.ID_SERIE ASC
            """, (id,), "serie"),
            "series_crew": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED,
                       s.POSTER_PATH, ps.CREDIT_TYPE, ps.CAST_CHARACTER, ps.CREW_DEPARTMENT,
                       ps.DISPLAY_ORDER, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_SERIE ps
                JOIN T_WC_T2S_SERIE s ON ps.ID_SERIE = s.ID_SERIE
                WHERE ps.ID_PERSON = %s AND ps.CREDIT_TYPE = 'crew'
                ORDER BY s.IMDB_RATING_WEIGHTED DESC, s.ID_SERIE ASC
            """, (id,), "serie"),
            "groups": ("""
                SELECT g.ID_GROUP, g.GROUP_NAME, g.GROUP_NAME_FR, g.GROUP_TYPE, g.PROFILE_PATH, g.WIKIPEDIA_IMAGE_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_GROUP pg
                JOIN T_WC_T2S_GROUP g ON pg.ID_GROUP = g.ID_GROUP
                WHERE pg.ID_PERSON = %s ORDER BY pg.DISPLAY_ORDER ASC, g.ID_GROUP ASC
            """, (id,), None),
            "deaths": ("""
                SELECT d.ID_DEATH, d.DEATH_NAME, d.DEATH_NAME_FR, d.DEATH_TYPE, d.PROFILE_PATH, d.WIKIPEDIA_IMAGE_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_DEATH pd
                JOIN T_WC_T2S_DEATH d ON pd.ID_DEATH = d.ID_DEATH
                WHERE pd.ID_PERSON = %s ORDER BY pd.DISPLAY_ORDER ASC, d.ID_DEATH ASC
            """, (id,), None),
            "awards": ("""
                SELECT a.ID_AWARD, a.AWARD_NAME, a.AWARD_NAME_FR, a.POSTER_PATH, a.WIKIPEDIA_IMAGE_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_AWARD pa
                JOIN T_WC_T2S_AWARD a ON pa.ID_AWARD = a.ID_AWARD
                WHERE pa.ID_PERSON = %s ORDER BY pa.DISPLAY_ORDER ASC, a.ID_AWARD ASC
            """, (id,), None),
            "nominations": ("""
                SELECT n.ID_NOMINATION, n.NOMINATION_NAME, n.NOMINATION_NAME_FR, n.POSTER_PATH, n.WIKIPEDIA_IMAGE_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_NOMINATION pn
                JOIN T_WC_T2S_NOMINATION n ON pn.ID_NOMINATION = n.ID_NOMINATION
                WHERE pn.ID_PERSON = %s ORDER BY pn.DISPLAY_ORDER ASC, n.ID_NOMINATION ASC
            """, (id,), None),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                cursor.execute("""
                    SELECT ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT,
                           VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER
                    FROM T_WC_T2S_PERSON_IMAGE
                    WHERE ID_PERSON = %s AND TYPE_IMAGE = 'profile'
                    ORDER BY DISPLAY_ORDER ASC
                """, (id,))
                portraits = cursor.fetchall()
                wikipedia_images = _fetch_wikipedia_images(cursor, person.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, person.get("ID_WIKIDATA"), ui_language)
                videos = _fetch_wikidata_videos(cursor, person.get("ID_WIKIDATA"))
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {
            **person,
            "movie_cast": data["movie_cast"],
            "movie_crew": data["movie_crew"],
            "series_cast": data["series_cast"],
            "series_crew": data["series_crew"],
            "groups": data["groups"],
            "deaths": data["deaths"],
            "awards": data["awards"],
            "nominations": data["nominations"],
            "portraits": list(portraits),
            "wikipedia_images": wikipedia_images,
            "wikipedia_content": wikipedia_content,
            "videos": videos,
            "pagination": pagination,
        }
        logs.log_usage("persons", {"id": id, "response": result}, strapiversion)
        apply_localized_main_image(result, portraits, "PROFILE_PATH", ui_language)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/companies/{id}", summary="Production company full detail")
async def get_company(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a production company plus associated movies and TV series,
    ordered by adjusted IMDb rating. The id is ID_COMPANY.

    The company itself includes LOGO_PATH, MOVIE_COUNT, SERIE_COUNT,
    IMDB_RATING_WEIGHTED, and POPULARITY. Each nested list element carries
    POSTER_PATH for the related movie or TV series."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_COMPANY WHERE ID_COMPANY = %s", (id,))
            company = cursor.fetchone()
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_COMPANY mc
                JOIN T_WC_T2S_MOVIE m ON mc.ID_MOVIE = m.ID_MOVIE
                WHERE mc.ID_COMPANY = %s ORDER BY m.IMDB_RATING_WEIGHTED DESC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_COMPANY sc
                JOIN T_WC_T2S_SERIE s ON sc.ID_SERIE = s.ID_SERIE
                WHERE sc.ID_COMPANY = %s ORDER BY s.IMDB_RATING_WEIGHTED DESC, s.ID_SERIE ASC
            """, (id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**company, "movies": data["movies"], "series": data["series"], "pagination": pagination}
        logs.log_usage("companies", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/networks/{id}", summary="TV network full detail")
async def get_network(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a TV network plus associated TV series, ordered by
    adjusted IMDb rating. The id is ID_NETWORK.

    Each nested series carries POSTER_PATH."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_NETWORK WHERE ID_NETWORK = %s", (id,))
            network = cursor.fetchone()
        if not network:
            raise HTTPException(status_code=404, detail=f"Network {id} not found")
        pcollections = {
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_NETWORK sn
                JOIN T_WC_T2S_SERIE s ON sn.ID_SERIE = s.ID_SERIE
                WHERE sn.ID_NETWORK = %s ORDER BY s.IMDB_RATING_WEIGHTED DESC, s.ID_SERIE ASC
            """, (id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**network, "series": data["series"], "pagination": pagination}
        logs.log_usage("networks", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/collections/{id}", summary="Film/series collection full detail")
async def get_collection(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a named collection (trilogy, saga, universe, franchise) plus
    member movies and TV series ordered by DISPLAY_ORDER. The id is ID_T2S_COLLECTION.

    The collection itself includes POSTER_PATH, WIKIPEDIA_IMAGE_PATH,
    IMDB_RATING_WEIGHTED, and POPULARITY. Each nested list element carries
    POSTER_PATH for the related movie or TV series.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_COLLECTION WHERE ID_T2S_COLLECTION = %s", (id,))
            collection_row = cursor.fetchone()
        if not collection_row:
            raise HTTPException(status_code=404, detail=f"Collection {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, mc.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_COLLECTION mc
                JOIN T_WC_T2S_MOVIE m ON mc.ID_MOVIE = m.ID_MOVIE
                WHERE mc.ID_T2S_COLLECTION = %s ORDER BY mc.DISPLAY_ORDER ASC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH, sc.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_COLLECTION sc
                JOIN T_WC_T2S_SERIE s ON sc.ID_SERIE = s.ID_SERIE
                WHERE sc.ID_T2S_COLLECTION = %s ORDER BY sc.DISPLAY_ORDER ASC, s.ID_SERIE ASC
            """, (id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, collection_row.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, collection_row.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**collection_row, "movies": data["movies"], "series": data["series"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("collections", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/topics/{id}", summary="Topic full detail")
async def get_topic(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a topic (theme, keyword, recurring-character collection) plus linked
    movies and TV series ordered by DISPLAY_ORDER. The id is ID_TOPIC.

    The topic itself includes POSTER_PATH, WIKIPEDIA_IMAGE_PATH,
    IMDB_RATING_WEIGHTED, and POPULARITY. Each nested list element carries
    POSTER_PATH for the related movie or TV series.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_TOPIC WHERE ID_TOPIC = %s", (id,))
            topic = cursor.fetchone()
        if not topic:
            raise HTTPException(status_code=404, detail=f"Topic {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, mt.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_TOPIC mt
                JOIN T_WC_T2S_MOVIE m ON mt.ID_MOVIE = m.ID_MOVIE
                WHERE mt.ID_TOPIC = %s ORDER BY mt.DISPLAY_ORDER ASC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH, st.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_TOPIC st
                JOIN T_WC_T2S_SERIE s ON st.ID_SERIE = s.ID_SERIE
                WHERE st.ID_TOPIC = %s ORDER BY st.DISPLAY_ORDER ASC, s.ID_SERIE ASC
            """, (id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, topic.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, topic.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**topic, "movies": data["movies"], "series": data["series"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("topics", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/lists/{id}", summary="Curated list full detail")
async def get_list(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a named curated list plus member movies and TV series
    ordered by DISPLAY_ORDER. The id is ID_T2S_LIST.

    The list itself includes POSTER_PATH, WIKIPEDIA_IMAGE_PATH,
    IMDB_RATING_WEIGHTED, and POPULARITY. Each nested list element carries
    POSTER_PATH for the related movie or TV series.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_LIST WHERE ID_T2S_LIST = %s", (id,))
            lst = cursor.fetchone()
        if not lst:
            raise HTTPException(status_code=404, detail=f"List {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, ml.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_LIST ml
                JOIN T_WC_T2S_MOVIE m ON ml.ID_MOVIE = m.ID_MOVIE
                WHERE ml.ID_T2S_LIST = %s ORDER BY ml.DISPLAY_ORDER ASC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH, sl.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_LIST sl
                JOIN T_WC_T2S_SERIE s ON sl.ID_SERIE = s.ID_SERIE
                WHERE sl.ID_T2S_LIST = %s ORDER BY sl.DISPLAY_ORDER ASC, s.ID_SERIE ASC
            """, (id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, lst.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, lst.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**lst, "movies": data["movies"], "series": data["series"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("lists", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/movements/{id}", summary="Film movement or style full detail")
async def get_movement(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a film movement or style plus associated movies and TV series
    ordered by DISPLAY_ORDER. The id is ID_MOVEMENT.

    The movement itself includes POSTER_PATH, WIKIPEDIA_IMAGE_PATH,
    IMDB_RATING_WEIGHTED, and POPULARITY. Each nested list element carries
    POSTER_PATH for the related movie or TV series.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_MOVEMENT WHERE ID_MOVEMENT = %s", (id,))
            movement = cursor.fetchone()
        if not movement:
            raise HTTPException(status_code=404, detail=f"Movement {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, mm.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_MOVEMENT mm
                JOIN T_WC_T2S_MOVIE m ON mm.ID_MOVIE = m.ID_MOVIE
                WHERE mm.ID_MOVEMENT = %s ORDER BY mm.DISPLAY_ORDER ASC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH, sm.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_MOVEMENT sm
                JOIN T_WC_T2S_SERIE s ON sm.ID_SERIE = s.ID_SERIE
                WHERE sm.ID_MOVEMENT = %s ORDER BY sm.DISPLAY_ORDER ASC, s.ID_SERIE ASC
            """, (id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, movement.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, movement.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**movement, "movies": data["movies"], "series": data["series"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("movements", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/technicals/{id}", summary="Technical format full detail")
async def get_technical(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a technical format (sound system, color/film/sound technology,
    or film format) plus associated movies and sibling technicals sharing the same
    TECHNICAL_TYPE. The id is ID_TECHNICAL.

    The technical itself includes WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, and
    POPULARITY. Each nested movie carries POSTER_PATH; each sibling carries
    DESCRIPTION (localized to ui_language), WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED,
    POPULARITY, and MOVIE_COUNT for navigation between related technical formats.

    No `series` array is returned because T_WC_T2S_SERIE_TECHNICAL does not exist yet.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_TECHNICAL WHERE ID_TECHNICAL = %s", (id,))
            technical = cursor.fetchone()
        if not technical:
            raise HTTPException(status_code=404, detail=f"Technical {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, mt.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_TECHNICAL mt
                JOIN T_WC_T2S_MOVIE m ON mt.ID_MOVIE = m.ID_MOVIE
                WHERE mt.ID_TECHNICAL = %s
                ORDER BY mt.DISPLAY_ORDER ASC, m.IMDB_RATING_WEIGHTED DESC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "siblings": ("""
                SELECT ID_TECHNICAL, DESCRIPTION, DESCRIPTION_FR, WIKIPEDIA_IMAGE_PATH,
                       IMDB_RATING_WEIGHTED, POPULARITY, MOVIE_COUNT, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_TECHNICAL
                WHERE TECHNICAL_TYPE = %s AND ID_TECHNICAL <> %s
                ORDER BY MOVIE_COUNT DESC, ID_TECHNICAL ASC
            """, (technical["TECHNICAL_TYPE"], id), None),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, technical.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, technical.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**technical, "movies": data["movies"], "siblings": data["siblings"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("technicals", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/genres/{id}", summary="Movie / TV genre full detail")
async def get_genre(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return the closed-vocabulary genre identified by ID_GENRE (the TMDb genre id,
    e.g. 28 = Action, 878 = Science Fiction) plus its member movies and TV series.

    The genre is stored in the reference table T_WC_TMDB_GENRE (legacy lowercase PK
    `id` / `name`), so the base row is aliased to the API's canonical shape:
    ID_GENRE, GENRE_NAME (localized to ui_language via T_WC_TMDB_GENRE_LANG, English
    fallback), APPLIES_TO_MOVIE, APPLIES_TO_SERIE. The APPLIES_TO_* flags say which
    side the genre is valid for (8 ids apply to both; the rest are movie- or TV-only).

    movies (via T_WC_T2S_MOVIE_GENRE) and series (via T_WC_T2S_SERIE_GENRE) are each
    ordered by IMDB_RATING_WEIGHTED DESC — best-rated first. A TV-only genre yields an
    empty movies array and vice versa. Each nested movie/serie carries a localized
    POSTER_PATH. There is no wikipedia_images / wikipedia_content block because
    T_WC_TMDB_GENRE has no ID_WIKIDATA."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT g.id AS ID_GENRE, g.name AS GENRE_NAME, gl.name AS GENRE_NAME_FR,
                       g.APPLIES_TO_MOVIE, g.APPLIES_TO_SERIE
                FROM T_WC_TMDB_GENRE g
                LEFT JOIN T_WC_TMDB_GENRE_LANG gl ON gl.id = g.id AND gl.LANG = 'fr'
                WHERE g.id = %s
            """, (id,))
            genre = cursor.fetchone()
        if not genre:
            raise HTTPException(status_code=404, detail=f"Genre {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_GENRE mg
                JOIN T_WC_T2S_MOVIE m ON mg.ID_MOVIE = m.ID_MOVIE
                WHERE mg.ID_GENRE = %s
                ORDER BY m.IMDB_RATING_WEIGHTED DESC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_GENRE sg
                JOIN T_WC_T2S_SERIE s ON sg.ID_SERIE = s.ID_SERIE
                WHERE sg.ID_GENRE = %s
                ORDER BY s.IMDB_RATING_WEIGHTED DESC, s.ID_SERIE ASC
            """, (id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**genre, "movies": data["movies"], "series": data["series"], "pagination": pagination}
        logs.log_usage("genres", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/groups/{id}", summary="Person group full detail")
async def get_group(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a group (organization, club, musical group) plus associated
    persons ordered by DISPLAY_ORDER. The id is ID_GROUP.

    The group itself includes PROFILE_PATH and WIKIPEDIA_IMAGE_PATH. Each nested person
    carries PROFILE_PATH.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_GROUP WHERE ID_GROUP = %s", (id,))
            group = cursor.fetchone()
        if not group:
            raise HTTPException(status_code=404, detail=f"Group {id} not found")
        pcollections = {
            "persons": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.POPULARITY, p.PROFILE_PATH, pg.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_GROUP pg
                JOIN T_WC_T2S_PERSON p ON pg.ID_PERSON = p.ID_PERSON
                WHERE pg.ID_GROUP = %s ORDER BY pg.DISPLAY_ORDER ASC, p.ID_PERSON ASC
            """, (id,), "person"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, group.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, group.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**group, "persons": data["persons"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("groups", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/deaths/{id}", summary="Cause of death full detail")
async def get_death(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a cause or circumstance of death plus associated persons
    ordered by DISPLAY_ORDER. The id is ID_DEATH.

    The death itself includes PROFILE_PATH and WIKIPEDIA_IMAGE_PATH. Each nested person
    carries PROFILE_PATH.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_DEATH WHERE ID_DEATH = %s", (id,))
            death = cursor.fetchone()
        if not death:
            raise HTTPException(status_code=404, detail=f"Death {id} not found")
        pcollections = {
            "persons": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.POPULARITY, p.PROFILE_PATH, pd.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_DEATH pd
                JOIN T_WC_T2S_PERSON p ON pd.ID_PERSON = p.ID_PERSON
                WHERE pd.ID_DEATH = %s ORDER BY pd.DISPLAY_ORDER ASC, p.ID_PERSON ASC
            """, (id,), "person"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, death.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, death.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**death, "persons": data["persons"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("deaths", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/awards/{id}", summary="Award full detail")
async def get_award(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for an award plus associated movies, TV series, and persons,
    all ordered by DISPLAY_ORDER. The id is ID_AWARD.

    The award itself includes POSTER_PATH and WIKIPEDIA_IMAGE_PATH. Each nested list
    element carries the canonical image path of its related entity: POSTER_PATH for
    movies and series; PROFILE_PATH for persons.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_AWARD WHERE ID_AWARD = %s", (id,))
            award = cursor.fetchone()
        if not award:
            raise HTTPException(status_code=404, detail=f"Award {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, ma.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_AWARD ma
                JOIN T_WC_T2S_MOVIE m ON ma.ID_MOVIE = m.ID_MOVIE
                WHERE ma.ID_AWARD = %s ORDER BY ma.DISPLAY_ORDER ASC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH, sa.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_AWARD sa
                JOIN T_WC_T2S_SERIE s ON sa.ID_SERIE = s.ID_SERIE
                WHERE sa.ID_AWARD = %s ORDER BY sa.DISPLAY_ORDER ASC, s.ID_SERIE ASC
            """, (id,), "serie"),
            "persons": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.POPULARITY, p.PROFILE_PATH, pa.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_AWARD pa
                JOIN T_WC_T2S_PERSON p ON pa.ID_PERSON = p.ID_PERSON
                WHERE pa.ID_AWARD = %s ORDER BY pa.DISPLAY_ORDER ASC, p.ID_PERSON ASC
            """, (id,), "person"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, award.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, award.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**award, "movies": data["movies"], "series": data["series"], "persons": data["persons"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("awards", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/nominations/{id}", summary="Award nomination full detail")
async def get_nomination(id: int, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for an award nomination plus associated movies, TV series, and
    persons, all ordered by DISPLAY_ORDER. The id is ID_NOMINATION.

    The nomination itself includes POSTER_PATH and WIKIPEDIA_IMAGE_PATH. Each nested
    list element carries the canonical image path of its related entity: POSTER_PATH
    for movies and series; PROFILE_PATH for persons.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_NOMINATION WHERE ID_NOMINATION = %s", (id,))
            nomination = cursor.fetchone()
        if not nomination:
            raise HTTPException(status_code=404, detail=f"Nomination {id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED, m.POSTER_PATH, mn.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_MOVIE_NOMINATION mn
                JOIN T_WC_T2S_MOVIE m ON mn.ID_MOVIE = m.ID_MOVIE
                WHERE mn.ID_NOMINATION = %s ORDER BY mn.DISPLAY_ORDER ASC, m.ID_MOVIE ASC
            """, (id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED, s.POSTER_PATH, sn.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_SERIE_NOMINATION sn
                JOIN T_WC_T2S_SERIE s ON sn.ID_SERIE = s.ID_SERIE
                WHERE sn.ID_NOMINATION = %s ORDER BY sn.DISPLAY_ORDER ASC, s.ID_SERIE ASC
            """, (id,), "serie"),
            "persons": ("""
                SELECT p.ID_PERSON, p.PERSON_NAME, p.POPULARITY, p.PROFILE_PATH, pn.DISPLAY_ORDER,
                       COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_T2S_PERSON_NOMINATION pn
                JOIN T_WC_T2S_PERSON p ON pn.ID_PERSON = p.ID_PERSON
                WHERE pn.ID_NOMINATION = %s ORDER BY pn.DISPLAY_ORDER ASC, p.ID_PERSON ASC
            """, (id,), "person"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, nomination.get("ID_WIKIDATA"), ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, nomination.get("ID_WIKIDATA"), ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"id": id}, collection, data, pagination, kinds, ui_language)
        result = {**nomination, "movies": data["movies"], "series": data["series"], "persons": data["persons"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("nominations", {"id": id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


@app.get("/locations/{wikidata_id}", summary="Location full detail")
async def get_location(wikidata_id: str, ui_language: Optional[str] = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT, api_key: str = Depends(get_api_key)):
    """Return all fields for a location identified by its Wikidata ID (e.g. Q90 for Paris)
    plus movies and series linked as narrative location (ID_PROPERTY=P840) or filming
    location (ID_PROPERTY=P915), ordered by adjusted IMDb rating.

    The location itself includes WIKIPEDIA_IMAGE_PATH. Each nested list element carries
    POSTER_PATH for the related movie or TV series.

    The wikipedia_images list contains the Wikipedia images for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_IMAGE; each element carries ID_ROW,
    LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE,
    FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER.

    The wikipedia_content list contains the Wikipedia section content for the requested ui_language (en/fr, English fallback) linked
    to ID_WIKIDATA from T_WC_WIKIPEDIA_PAGE_LANG_SECTION; each element carries the
    section title and content, ordered by DISPLAY_ORDER."""
    ui_language = normalize_ui_language(ui_language)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM T_WC_T2S_ITEM WHERE ID_WIKIDATA = %s", (wikidata_id,))
            location = cursor.fetchone()
        if not location:
            raise HTTPException(status_code=404, detail=f"Location {wikidata_id} not found")
        pcollections = {
            "movies": ("""
                SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.DAT_RELEASE, m.IMDB_RATING_WEIGHTED,
                       m.POSTER_PATH, wp.ID_PROPERTY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_WIKIDATA_ITEM_PROPERTY wp
                JOIN T_WC_T2S_MOVIE m ON wp.ID_WIKIDATA = m.ID_WIKIDATA
                WHERE wp.ID_ITEM = %s AND wp.ID_PROPERTY IN ('P840', 'P915')
                ORDER BY m.IMDB_RATING_WEIGHTED DESC, m.ID_MOVIE ASC
            """, (wikidata_id,), "movie"),
            "series": ("""
                SELECT s.ID_SERIE, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.DAT_FIRST_AIR, s.DAT_LAST_AIR, s.IMDB_RATING_WEIGHTED,
                       s.POSTER_PATH, wp.ID_PROPERTY, COUNT(*) OVER() AS _TOTAL_COUNT
                FROM T_WC_WIKIDATA_ITEM_PROPERTY wp
                JOIN T_WC_T2S_SERIE s ON wp.ID_WIKIDATA = s.ID_WIKIDATA
                WHERE wp.ID_ITEM = %s AND wp.ID_PROPERTY IN ('P840', 'P915')
                ORDER BY s.IMDB_RATING_WEIGHTED DESC, s.ID_SERIE ASC
            """, (wikidata_id,), "serie"),
        }
        with conn.cursor() as cursor:
            data, pagination, kinds = _run_collections(cursor, pcollections, collection, page, rows_per_page)
            if collection is None:
                wikipedia_images = _fetch_wikipedia_images(cursor, wikidata_id, ui_language)
                wikipedia_content = _fetch_wikipedia_content(cursor, wikidata_id, ui_language)
        if collection is not None:
            return _targeted_collection_response(conn, {"wikidata_id": wikidata_id}, collection, data, pagination, kinds, ui_language)
        result = {**location, "movies": data["movies"], "series": data["series"], "wikipedia_images": wikipedia_images, "wikipedia_content": wikipedia_content, "pagination": pagination}
        logs.log_usage("locations", {"wikidata_id": wikidata_id, "response": result}, strapiversion)
        apply_localized_related_images(conn, _localized_image_groups(data, kinds), ui_language)
        localize_response(result, ui_language)
        return result
    finally:
        conn.close()


# Root parent of the suggested-samples category tree (mirrors the front-end's $lngroot=1).
SAMPLES_ROOT_PARENT_ID = 1

# entity_type -> (table, id_column, [select columns]) used to hydrate a sample's
# assertion id-set into display rows. The selected columns mirror the related-entity
# arrays of the detail endpoints (id + localizable label + date/rating + image path);
# the trailing _FR columns are collapsed by localize_response at the end. "content"
# (a movie+series union) is handled specially in _hydrate_sample_rows.
SAMPLE_HYDRATION = {
    "movie":   ("T_WC_T2S_MOVIE",   "ID_MOVIE",    ["ID_MOVIE", "MOVIE_TITLE", "MOVIE_TITLE_FR", "DAT_RELEASE", "IMDB_RATING_WEIGHTED", "POSTER_PATH"]),
    "person":  ("T_WC_T2S_PERSON",  "ID_PERSON",   ["ID_PERSON", "PERSON_NAME", "PROFILE_PATH", "POPULARITY", "KNOWN_FOR_DEPARTMENT"]),
    "serie":   ("T_WC_T2S_SERIE",   "ID_SERIE",    ["ID_SERIE", "SERIE_TITLE", "SERIE_TITLE_FR", "DAT_FIRST_AIR", "IMDB_RATING_WEIGHTED", "POSTER_PATH"]),
    "topic":   ("T_WC_T2S_TOPIC",   "ID_TOPIC",    ["ID_TOPIC", "TOPIC_NAME", "TOPIC_NAME_FR", "POSTER_PATH", "WIKIPEDIA_IMAGE_PATH", "IMDB_RATING_WEIGHTED", "POPULARITY"]),
    "company": ("T_WC_T2S_COMPANY", "ID_COMPANY",  ["ID_COMPANY", "COMPANY_NAME", "LOGO_PATH", "MOVIE_COUNT", "SERIE_COUNT", "POPULARITY"]),
    "network": ("T_WC_T2S_NETWORK", "ID_NETWORK",  ["ID_NETWORK", "NETWORK_NAME", "LOGO_PATH", "SERIE_COUNT"]),
    "list":    ("T_WC_T2S_LIST",    "ID_T2S_LIST", ["ID_T2S_LIST", "LIST_NAME", "LIST_NAME_FR", "POSTER_PATH", "WIKIPEDIA_IMAGE_PATH", "IMDB_RATING_WEIGHTED", "POPULARITY"]),
    "collection": ("T_WC_T2S_COLLECTION", "ID_T2S_COLLECTION", ["ID_T2S_COLLECTION", "COLLECTION_NAME", "COLLECTION_NAME_FR", "POSTER_PATH", "WIKIPEDIA_IMAGE_PATH", "MOVIE_COUNT", "SERIE_COUNT", "IMDB_RATING_WEIGHTED"]),
    "location": ("T_WC_T2S_ITEM",   "ID_WIKIDATA", ["ID_WIKIDATA", "ITEM_LABEL", "ITEM_LABEL_FR", "WIKIPEDIA_IMAGE_PATH"]),
    # Secondary entities. group/death store their image in PROFILE_PATH, aliased to
    # POSTER_PATH so the front-end card picks it up (it reads POSTER_PATH ||
    # WIKIPEDIA_IMAGE_PATH); technical's label is DESCRIPTION. These carry a real image
    # column but image *coverage* is uneven, so a given sample only renders where rows
    # actually have a usable image (VOICE-AGENT-068 hides image-less showcase cards).
    "movement":   ("T_WC_T2S_MOVEMENT",   "ID_MOVEMENT",   ["ID_MOVEMENT", "MOVEMENT_NAME", "MOVEMENT_NAME_FR", "POSTER_PATH", "WIKIPEDIA_IMAGE_PATH"]),
    "award":      ("T_WC_T2S_AWARD",      "ID_AWARD",      ["ID_AWARD", "AWARD_NAME", "AWARD_NAME_FR", "POSTER_PATH", "WIKIPEDIA_IMAGE_PATH"]),
    "nomination": ("T_WC_T2S_NOMINATION", "ID_NOMINATION", ["ID_NOMINATION", "NOMINATION_NAME", "NOMINATION_NAME_FR", "POSTER_PATH", "WIKIPEDIA_IMAGE_PATH"]),
    "group":      ("T_WC_T2S_GROUP",      "ID_GROUP",      ["ID_GROUP", "GROUP_NAME", "GROUP_NAME_FR", "PROFILE_PATH AS POSTER_PATH", "WIKIPEDIA_IMAGE_PATH"]),
    "death":      ("T_WC_T2S_DEATH",      "ID_DEATH",      ["ID_DEATH", "DEATH_NAME", "DEATH_NAME_FR", "PROFILE_PATH AS POSTER_PATH", "WIKIPEDIA_IMAGE_PATH"]),
    "technical":  ("T_WC_T2S_TECHNICAL",  "ID_TECHNICAL",  ["ID_TECHNICAL", "DESCRIPTION", "DESCRIPTION_FR", "WIKIPEDIA_IMAGE_PATH"]),
}

# Evaluation categories whose samples preview the entity's FULL image set (every poster /
# portrait from the *_IMAGE table) instead of the single entity row. Maps the category id
# to the _RELATED_IMAGE_SOURCES key (which carries image table / id column / TYPE_IMAGE /
# target path field). The assertion still resolves to the entity id(s); each id's hydrated
# row is then expanded into one row per image, swapping the path field to each image.
SAMPLE_IMAGE_CATEGORIES = {
    13: "movie",   # Movies - Images queries (posters)   -> T_WC_T2S_MOVIE_IMAGE / POSTER_PATH
    24: "serie",   # TV Series - Images queries (posters) -> T_WC_T2S_SERIE_IMAGE / POSTER_PATH
    23: "person",  # Persons - Images queries (portraits) -> T_WC_T2S_PERSON_IMAGE / PROFILE_PATH
}

# Cap images hydrated per entity for image-query samples. Without a cap, one sample
# (8 entities) expands into every poster/portrait (hundreds each): the /samples payload
# ballooned to ~28 MB / 40 s and timed out (breaking the voice-agent showcase). A small
# cap keeps a rich poster/portrait wall while bounding the response.
MAX_SAMPLE_IMAGES_PER_ENTITY = 6

# Cap ids hydrated per sample preview. A malformed / no-LIMIT ASSERTION_REFRESH_SQL can
# resolve to 100k+ ids -> a 26 MB /samples response (broke the showcase). The eval scoring
# uses the raw assertion, not this preview, so capping the preview is safe.
MAX_SAMPLE_ENTITY_IDS = 12


def _sample_clause_expectation(clause):
    """Describe a non-materializable assertion clause as a flat expectation dict."""
    if clause["type"] == "count":
        return {"aggregate": f"COUNT({clause['arg']})", "operator": clause["op"], "value": clause["value"]}
    if clause["type"] == "scalar":
        return {"column": clause["column"], "operator": clause["op"], "value": clause["value"]}
    if clause["type"] == "cell":
        return {"cell": [clause["row"], clause["col"]], "operator": clause["op"], "value": clause["value"]}
    if clause["type"] == "id_exclusion":
        return {"column": clause["column"], "operator": "NOT IN", "value": clause["ids"]}
    return None


def _attach_sample_simulation(node, parsed, summary, pending, image_source=None):
    """Populate ``node['simulated_result']`` from a parsed assertion.

    For ``entity_rows`` the simulated_result is created with an empty ``result`` and the
    (sim, entity_type, ordered ids, image_source) tuple is appended to ``pending`` so rows
    can be hydrated in one batched pass per entity type. ``image_source`` is None for a
    normal sample; for the image-query categories (see ``SAMPLE_IMAGE_CATEGORIES``) it is
    the ``_RELATED_IMAGE_SOURCES`` key, and each id's row is later expanded into the
    entity's full poster / portrait set. ``scalar`` results are materialized inline from
    the literal value (no DB needed); ``count`` / ``bound`` carry only an ``expectation``
    block (no invented rows). A null/unknown assertion leaves simulated_result as None.
    """
    if not summary:
        return
    kind = summary["result_kind"]
    clauses = parsed["clauses"]

    if kind == "entity_rows":
        id_clause = next(c for c in clauses if c["type"] == "id_set")
        entity_type = id_clause["entity"]
        sim = {"result_kind": "entity_rows", "entity_type": entity_type, "total_count": 0, "result": []}
        node["simulated_result"] = sim
        if entity_type:  # unknown id-columns stay empty (no table to hydrate from)
            # image_source only applies when it matches the assertion's entity kind.
            effective_image_source = image_source if image_source == entity_type else None
            if effective_image_source:
                sim["image_gallery"] = True  # signals the front to show the full image set
            pending.append((sim, entity_type, list(dict.fromkeys(id_clause["ids"])), effective_image_source))
        return

    if kind == "scalar":
        literal = next(c for c in clauses if c["type"] in ("scalar", "cell") and c["op"] == "==")
        data = {"VALUE": literal["value"]} if literal["type"] == "cell" else {literal["column"]: literal["value"]}
        node["simulated_result"] = {
            "result_kind": "scalar",
            "total_count": 1,
            "result": [{"index": 0, "data": data}],
        }
        return

    # count / bound: no concrete rows, only the expectation.
    if kind == "count":
        source = next(c for c in clauses if c["type"] == "count")
    else:
        source = next((c for c in clauses if c["type"] in ("scalar", "cell", "id_exclusion")), None)
    node["simulated_result"] = {
        "result_kind": kind,
        "result": [],
        "expectation": _sample_clause_expectation(source) if source else None,
    }


def _hydrate_sample_rows(conn, pending):
    """Fill every pending entity_rows simulation with hydrated display rows.

    Ids are unioned per entity type and fetched with one batched query each, then each
    simulation's ``result`` is rebuilt in the assertion's id order (missing/deleted ids
    are skipped, and ``total_count`` reflects rows actually found). The "content" kind
    is a movie+series union resolved movie-first, then series for the remainder, with a
    MEDIA_TYPE tag on each row.

    Image-query samples (``image_source`` set — see ``SAMPLE_IMAGE_CATEGORIES``) expand
    each id's hydrated row into one row per image from the entity's ``*_IMAGE`` table
    (up to ``MAX_SAMPLE_IMAGES_PER_ENTITY`` posters / portraits by DISPLAY_ORDER), copying the row and swapping the
    path field (``POSTER_PATH`` / ``PROFILE_PATH``) to each image; an id with no images
    keeps its single entity row.
    """
    if not pending:
        return
    # Bound each sample's preview to a handful of ids: a malformed assertion (e.g. an
    # ASSERTION_REFRESH_SQL missing its LIMIT) can otherwise resolve to 100k+ ids and blow
    # the /samples response to tens of MB, breaking the showcase. Preview-only; the eval
    # scoring reads the raw assertion, not this. Images are further capped per entity.
    pending = [(sim, et, list(ids)[:MAX_SAMPLE_ENTITY_IDS], img) for sim, et, ids, img in pending]
    ids_by_type = {}
    for _sim, entity_type, ids, _image_source in pending:
        ids_by_type.setdefault(entity_type, []).extend(ids)

    row_maps = {}       # entity_type -> {id: data dict}
    images_by_source = {}  # image_source -> {id: [IMAGE_PATH, ...]}
    with conn.cursor() as cursor:
        for entity_type, ids in ids_by_type.items():
            unique_ids = list(dict.fromkeys(ids))
            if not unique_ids:
                row_maps[entity_type] = {}
                continue
            if entity_type == "content":
                row_maps[entity_type] = _hydrate_content_rows(cursor, unique_ids)
                continue
            table, id_column, columns = SAMPLE_HYDRATION[entity_type]
            placeholders = ",".join(["%s"] * len(unique_ids))
            cursor.execute(
                f"SELECT {', '.join(columns)} FROM {table} "
                f"WHERE {id_column} IN ({placeholders}) AND DELETED = 0",
                tuple(unique_ids),
            )
            row_maps[entity_type] = {row[id_column]: row for row in cursor.fetchall()}

        # Image-query samples: fetch every poster / portrait for the involved ids.
        image_ids_by_source = {}
        for _sim, _entity_type, ids, image_source in pending:
            if image_source:
                image_ids_by_source.setdefault(image_source, []).extend(ids)
        for image_source, ids in image_ids_by_source.items():
            images_by_source[image_source] = _fetch_sample_images(
                cursor, image_source, list(dict.fromkeys(ids))
            )

    for sim, entity_type, ids, image_source in pending:
        row_map = row_maps.get(entity_type, {})
        rows = []
        if image_source:
            path_field = _RELATED_IMAGE_SOURCES[image_source][3]
            images = images_by_source.get(image_source, {})
            for id_value in ids:
                base = row_map.get(id_value)
                if base is None:
                    continue
                paths = images.get(id_value) or []
                if paths:
                    for path in paths:
                        rows.append({"index": len(rows), "data": {**base, path_field: path}})
                else:  # no image rows: fall back to the entity's own single card
                    rows.append({"index": len(rows), "data": base})
        else:
            for id_value in ids:
                data = row_map.get(id_value)
                if data is not None:
                    rows.append({"index": len(rows), "data": data})
        sim["result"] = rows
        sim["total_count"] = len(rows)


def _hydrate_content_rows(cursor, ids):
    """Resolve ambiguous ID_CONTENT ids against movies first, then series.

    ID_CONTENT is a movie+series union; the same integer can exist as both a movie and
    a series, so this is best-effort: an id is taken as a movie when present in
    T_WC_T2S_MOVIE, otherwise as a series. Each returned row carries MEDIA_TYPE.
    """
    placeholders = ",".join(["%s"] * len(ids))
    resolved = {}
    cursor.execute(
        f"SELECT ID_MOVIE, MOVIE_TITLE, MOVIE_TITLE_FR, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH "
        f"FROM T_WC_T2S_MOVIE WHERE ID_MOVIE IN ({placeholders}) AND DELETED = 0",
        tuple(ids),
    )
    for row in cursor.fetchall():
        row["MEDIA_TYPE"] = "movie"
        resolved[row["ID_MOVIE"]] = row
    remaining = [i for i in ids if i not in resolved]
    if remaining:
        placeholders = ",".join(["%s"] * len(remaining))
        cursor.execute(
            f"SELECT ID_SERIE, SERIE_TITLE, SERIE_TITLE_FR, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH "
            f"FROM T_WC_T2S_SERIE WHERE ID_SERIE IN ({placeholders}) AND DELETED = 0",
            tuple(remaining),
        )
        for row in cursor.fetchall():
            row["MEDIA_TYPE"] = "serie"
            resolved[row["ID_SERIE"]] = row
    return resolved


def _fetch_sample_images(cursor, image_source, ids):
    """Return ``{entity_id: [IMAGE_PATH, ...]}`` for an image-query sample.

    Reads every image row of the category's ``TYPE_IMAGE`` (posters for movies / series,
    profiles for persons — from ``_RELATED_IMAGE_SOURCES``) for the given ids out of the
    entity's ``*_IMAGE`` table, across all languages, ordered by ``DISPLAY_ORDER``, capped
    at ``MAX_SAMPLE_IMAGES_PER_ENTITY`` per entity so a sample previews a bounded poster /
    portrait wall instead of the full (multi-hundred) set. Blank paths are skipped.
    """
    if not ids:
        return {}
    image_table, id_column, type_image, _path_field = _RELATED_IMAGE_SOURCES[image_source]
    placeholders = ",".join(["%s"] * len(ids))
    # Cap to MAX_SAMPLE_IMAGES_PER_ENTITY per entity IN SQL (ROW_NUMBER window) so the DB
    # returns only the few kept rows instead of every poster/portrait (hundreds each) --
    # bounds the read/transfer, not just the Python-side payload. The int cap is a trusted
    # constant; id_column/image_table come from _RELATED_IMAGE_SOURCES (never user input).
    cursor.execute(
        f"SELECT _IMG_ID, IMAGE_PATH FROM ("
        f"  SELECT {id_column} AS _IMG_ID, IMAGE_PATH, "
        f"         ROW_NUMBER() OVER (PARTITION BY {id_column} ORDER BY DISPLAY_ORDER ASC) AS _rn "
        f"  FROM {image_table} "
        f"  WHERE {id_column} IN ({placeholders}) AND TYPE_IMAGE = %s"
        f") ranked WHERE _rn <= {int(MAX_SAMPLE_IMAGES_PER_ENTITY)} "
        f"ORDER BY _IMG_ID, _rn",
        (*ids, type_image),
    )
    images = {}
    for row in cursor.fetchall():
        path = row.get("IMAGE_PATH")
        if path is None or (isinstance(path, str) and not path.strip()):
            continue
        bucket = images.setdefault(row["_IMG_ID"], [])
        if len(bucket) < MAX_SAMPLE_IMAGES_PER_ENTITY:  # cap per entity (bound /samples payload)
            bucket.append(path)
    return images


@app.get("/samples", summary="Suggested sample questions")
async def get_samples(ui_language: Optional[str] = "en", set: Optional[str] = "sample", api_key: str = Depends(get_api_key)):
    """Return the curated tree of suggested sample questions, each with a simulated result.

    Mirrors the front-end samples panel (lib/text2sql-samples.inc.php): a hierarchy of
    evaluation categories (T_WC_T2S_EVALUATION_CATEGORY, rooted at ID_PARENT = 1,
    ordered by DISPLAY_ORDER) whose leaves are sample questions (T_WC_T2S_EVALUATION
    rows with IS_SAMPLE = 1 AND DELETED = 0, ordered by DISPLAY_ORDER). Categories that
    contain no sample anywhere in their subtree are pruned, so the response carries only
    branches with at least one question — matching the public (non-private) front-end
    behavior.

    Each category node exposes ID_T2S_EVALUATION_CATEGORY, DESCRIPTION (localized to
    ui_language with English fallback), a ``samples`` array, and a ``categories`` array
    of child nodes. Each sample exposes:
      - ID_T2S_EVALUATION and QUESTION (localized; HTML entities decoded);
      - ``assertion``: the parsed ground-truth spec from ASSERTIONS_QUERY_RESULT
        (``raw``, ``result_kind`` of entity_rows|scalar|count|bound|unknown,
        ``entity_type``, ``expected_count``, ``count_operator``); null when the sample
        has no assertion;
      - ``simulated_result``: a renderable simulation of the expected answer whose row
        shape matches /search/text2sql (``result`` is a list of ``{index, data}``).
        For ``entity_rows`` the assertion ids are hydrated into display rows from the
        matching T_WC_T2S_* table; ``scalar`` carries the single known cell value;
        ``count`` / ``bound`` carry an ``expectation`` block and no rows. Null when
        nothing is materializable. For the image-query categories
        (``SAMPLE_IMAGE_CATEGORIES``: 13 movies posters, 24 series posters, 23 persons
        portraits) each entity row is expanded into one row per image from the entity's
        ``*_IMAGE`` table (POSTER_PATH / PROFILE_PATH swapped per image), previewing the
        full poster / portrait set instead of the single main image.

    Supported ui_language values are "en" (default) and "fr"; any other value falls
    back to English.

    ``set`` selects which curated set to return: "sample" (default — IS_SAMPLE = 1, the
    existing behavior) or "showcase" (IS_SHOWCASE = 1 — the advisor home-screen picks).
    Each sample node also carries ``IS_SHOWCASE`` so a client can filter client-side.
    """
    ui_language = normalize_ui_language(ui_language)
    # Which curated set to return. Whitelisted -> the resolved column name is safe to
    # interpolate into the query below (never the raw user value).
    sample_set = (set or "sample").strip().lower()
    sample_filter_col = "IS_SHOWCASE" if sample_set == "showcase" else "IS_SAMPLE"
    conn = get_db_connection()
    try:
        pending = []  # (simulated_result, entity_type, ordered ids) to hydrate in batch
        with conn.cursor() as cursor:
            def fetch_samples(category_id):
                image_source = SAMPLE_IMAGE_CATEGORIES.get(category_id)
                cursor.execute(
                    f"""SELECT ID_T2S_EVALUATION, QUESTION, QUESTION_FR, IS_SHOWCASE, ASSERTIONS_QUERY_RESULT
                       FROM T_WC_T2S_EVALUATION
                       WHERE ID_T2S_EVALUATION_CATEGORY = %s AND {sample_filter_col} = 1 AND DELETED = 0
                       ORDER BY DISPLAY_ORDER ASC""",
                    (category_id,),
                )
                rows = cursor.fetchall()  # materialize before reusing the cursor
                nodes = []
                for row in rows:
                    raw_assertion = row.pop("ASSERTIONS_QUERY_RESULT", None)
                    for key in ("QUESTION", "QUESTION_FR"):
                        if isinstance(row.get(key), str):
                            row[key] = html.unescape(row[key])
                    parsed = sa.parse_assertion(raw_assertion)
                    node = {**row, "assertion": sa.summarize(parsed, raw_assertion), "simulated_result": None}
                    # Guard: a non-empty assertion that the parser could not fully
                    # understand is logged (DB/format drift) but does not fail the request.
                    if raw_assertion is not None and str(raw_assertion).strip():
                        reason = sa.parse_failure(parsed, node["assertion"])
                        if reason:
                            print(
                                f"[samples] Unparsed assertion for ID_T2S_EVALUATION="
                                f"{row.get('ID_T2S_EVALUATION')}: {reason} "
                                f"| raw={str(raw_assertion).strip()!r}",
                                flush=True,
                            )
                    _attach_sample_simulation(node, parsed, node["assertion"], pending, image_source)
                    nodes.append(node)
                return nodes

            def build_subtree(parent_id):
                cursor.execute(
                    """SELECT ID_T2S_EVALUATION_CATEGORY, DESCRIPTION, DESCRIPTION_FR
                       FROM T_WC_T2S_EVALUATION_CATEGORY
                       WHERE ID_PARENT = %s AND DELETED = 0
                       ORDER BY DISPLAY_ORDER ASC""",
                    (parent_id,),
                )
                categories = cursor.fetchall()  # materialize before reusing the cursor
                nodes = []
                for cat in categories:
                    cat_id = cat["ID_T2S_EVALUATION_CATEGORY"]
                    children = build_subtree(cat_id)
                    samples = fetch_samples(cat_id)
                    # Prune empty branches: keep a category only if it (or a descendant)
                    # carries at least one sample — the non-private front-end behavior.
                    if not children and not samples:
                        continue
                    cat["categories"] = children
                    cat["samples"] = samples
                    nodes.append(cat)
                return nodes

            categories = build_subtree(SAMPLES_ROOT_PARENT_ID)

        # Hydrate every entity_rows simulation in one batched pass per entity type.
        _hydrate_sample_rows(conn, pending)

        result = {"ui_language": ui_language, "set": sample_set, "categories": categories}
        logs.log_usage("samples", {"ui_language": ui_language, "response": result}, strapiversion)
        localize_response(result, ui_language)  # collapses _FR on categories, samples, and hydrated rows
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MCP (Model Context Protocol) server — tools, resource, middleware, mount
# ---------------------------------------------------------------------------

@mcp.tool(name="sql_search")
async def _mcp_sql_search(
    question: str,
    ui_language: str = "en",
    llm_model_entity_extraction: str = "default",
    llm_model_text2sql: str = "default",
    llm_model_complex: str = "default",
) -> str:
    """
    Query the cinema and TV database in natural language.

    Covers movies, TV series, persons (actors, directors, writers, crew),
    production companies, TV networks, topics (themes, recurring-character collections),
    curated lists (rankings, canons), collections (trilogies, sagas, universes, franchises),
    film movements, person groups, causes of death, awards, nominations, and locations
    (narrative or filming).

    The result returns rows with entity IDs and key fields (title, release date,
    IMDb rating, poster path), plus a plain-language `answer` field generated in
    the requested `ui_language`. Supported `ui_language` values are "en" (English,
    the default) and "fr" (French); any other value falls back to English. Use the
    entity tools below to fetch full details.

    Optional model overrides (each defaults to "default" = the server's configured
    model, currently gpt-4o): llm_model_entity_extraction, llm_model_text2sql, and
    llm_model_complex route the entity-extraction, SQL-generation, and complex-question
    steps through a chosen provider/model (an OpenAI "gpt-*"/"o1*"/"o3*" model, a
    "claude-*" model, or a "gemini-*" model).

    For precise field knowledge (column names, value ranges, genre codes) read
    the resource context://database-scope before formulating complex questions.

    Data coverage: ~620k movies, ~88k TV series, ~890k persons. Up to early 2024.
    Movie IDs      → https://myapp.com/movies/{ID_MOVIE}
    Series IDs     → https://myapp.com/series/{ID_SERIE}
    Person IDs     → https://myapp.com/persons/{ID_PERSON}
    Collection IDs → https://myapp.com/collections/{ID_T2S_COLLECTION}
    Topic IDs      → https://myapp.com/topics/{ID_TOPIC}
    List IDs       → https://myapp.com/lists/{ID_T2S_LIST}
    Movement IDs   → https://myapp.com/movements/{ID_MOVEMENT}
    Genre IDs      → https://myapp.com/genres/{ID_GENRE}
    Group IDs      → https://myapp.com/groups/{ID_GROUP}
    Death IDs      → https://myapp.com/deaths/{ID_DEATH}
    Award IDs      → https://myapp.com/awards/{ID_AWARD}
    Nomination IDs → https://myapp.com/nominations/{ID_NOMINATION}
    Company IDs    → https://myapp.com/companies/{ID_COMPANY}
    Network IDs    → https://myapp.com/networks/{ID_NETWORK}
    Location IDs   → https://myapp.com/locations/{ID_WIKIDATA} (Wikidata ID, e.g. Q90)
    """
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{MCP_INTERNAL_BASE_URL}/search/text2sql",
                json={
                    "question": question,
                    "ui_language": normalize_ui_language(ui_language),
                    "llm_model_entity_extraction": llm_model_entity_extraction,
                    "llm_model_text2sql": llm_model_text2sql,
                    "llm_model_complex": llm_model_complex,
                },
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})


async def _mcp_get(path: str, ui_language: str = "en", collection: Optional[str] = None,
                   page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT,
                   sample_set: Optional[str] = None) -> str:
    """Shared MCP helper: GET an internal entity endpoint and return its raw JSON text.

    Forwards the normalized ``ui_language`` (en/fr, English fallback) so every
    localized entity tool honors the requested language. Embedded related-entity
    lists are paginated: by default every list is capped to its first page (with a
    ``pagination`` block carrying per-list totals); passing ``collection`` (plus
    optional ``page`` / ``rows_per_page``) returns a lean payload with just that
    one list's requested page. Pagination params are only forwarded when a
    ``collection`` is targeted, so the default call is unchanged.
    """
    params = {"ui_language": normalize_ui_language(ui_language)}
    if collection:
        params["collection"] = collection
        params["page"] = page
        params["rows_per_page"] = rows_per_page
    if sample_set is not None:
        params["set"] = sample_set
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}{path}",
                params=params,
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(name="get_movie")
async def _mcp_get_movie(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a movie (title, release date, runtime, budget, revenue, ratings,
    plot, IMDb/Wikidata IDs, color/B&W/silent flags) plus embedded relations:
    cast, crew, genre codes, production companies, production countries, spoken languages,
    topics, lists, collections, movements, technicals, awards, and nominations, plus similar
    and recommendations (grounded TMDb neighbour movies, each with ID_MOVIE, localized
    MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, and POSTER_PATH, ordered by
    DISPLAY_ORDER; similar is content-based, recommendations is behaviour-based).
    collection_name and collection_movies give the movie's T2S collection name and all its
    members in chronological order. A T2S collection is cross-type (holds both movies AND
    series, e.g. Star Trek): each item carries ENTITY_TYPE ('movie' | 'serie') with
    ID_MOVIE/MOVIE_TITLE or ID_SERIE/SERIE_TITLE, plus IS_CURRENT on this movie ([] when
    standalone). collection_previous and collection_next are the adjacent members (null at
    the ends) and may be a series; collection_next is forced to the #1 spot of similar only
    when it is a movie (same-type), flagged IS_COLLECTION_NEXT.
    Each related company, topic, list, collection, and movement carries its own POSTER_PATH
    (LOGO_PATH for companies), WIKIPEDIA_IMAGE_PATH (when applicable),
    IMDB_RATING_WEIGHTED, and POPULARITY. Technicals (sound systems, color/film/sound
    technologies, film formats, and aspect ratios from T_WC_T2S_TECHNICAL) expose
    ID_TECHNICAL, DESCRIPTION (localized to ui_language), TECHNICAL_TYPE (one of: sound_system,
    color_technology, film_technology, sound_technology, film_format, medium_format,
    aspect_ratio), WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, and POPULARITY. Also
    returns top-level posters and backdrops (all poster / backdrop images from
    T_WC_T2S_MOVIE_IMAGE), wikipedia_images
    (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)), wikipedia_content (Wikipedia section in the requested ui_language,
    title/content pairs from T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA,
    and a unified videos list merging TMDb-sourced videos (T_WC_TMDB_MOVIE_VIDEO)
    and Wikidata-sourced videos (T_WC_WIKIDATA_MEDIA_RESOURCE, RESOURCE_KIND='video');
    each video exposes SOURCE, VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE, LANG,
    OFFICIAL, DAT_PUBLISHED, DURATION_SECONDS, and WATCH_URL/EMBED_URL/FILE_URL/
    THUMBNAIL_URL.
    id = TMDb ID_MOVIE.

    Embedded related lists (cast, crew, companies, topics, lists, collections,
    movements, technicals, awards, nominations, similar, recommendations) are paginated: by default each is
    capped to its first 50 rows and a top-level `pagination` block reports each
    list's total. To fetch more of one list, set `collection` to its name (e.g.
    'cast') with `page` / `rows_per_page`; the response then contains just that
    list's requested page."""
    return await _mcp_get(f"/movies/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_series")
async def _mcp_get_series(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a TV series (title, first/last air date, number of seasons and
    episodes, ratings, status, Wikidata/IMDb IDs) plus embedded relations: cast, crew,
    genre codes, companies, networks, production countries, spoken languages, topics, lists,
    collections, movements, awards, nominations, similar and recommendations (grounded
    TMDb neighbour series, each with ID_SERIE, localized SERIE_TITLE, DAT_FIRST_AIR,
    IMDB_RATING_WEIGHTED, and POSTER_PATH, ordered by DISPLAY_ORDER; similar is
    content-based, recommendations is behaviour-based), and seasons (every season from
    T_WC_TMDB_SEASON with SEASON_NUMBER, TITLE, DAT_AIR, POSTER_PATH, EPISODE_COUNT,
    VOTE_AVERAGE, and IMDb/Wikidata/TVDB IDs). collection_name and collection_movies give
    the series' T2S collection and all its members in chronological order; a T2S collection
    is cross-type (holds both series AND movies, e.g. Star Trek), each item carrying
    ENTITY_TYPE ('movie' | 'serie') with ID_SERIE/SERIE_TITLE or ID_MOVIE/MOVIE_TITLE, plus
    IS_CURRENT ([] when standalone); collection_previous/collection_next are the adjacent
    members (null at the ends, may be a movie), and a same-type next is forced to the #1
    spot of similar and flagged IS_COLLECTION_NEXT. Each related company, topic, list,
    collection, and movement carries its own POSTER_PATH (LOGO_PATH for companies and
    networks), WIKIPEDIA_IMAGE_PATH (when applicable), IMDB_RATING_WEIGHTED, and
    POPULARITY. Also returns top-level posters and backdrops (all poster / backdrop
    images from T_WC_T2S_SERIE_IMAGE), wikipedia_images (ui_language-specific Wikipedia image
    metadata), wikipedia_content (Wikipedia section title/content pairs in the requested ui_language from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA, and a unified videos
    list merging TMDb-sourced videos (T_WC_TMDB_SERIE_VIDEO) and Wikidata-sourced
    videos (T_WC_WIKIDATA_MEDIA_RESOURCE, RESOURCE_KIND='video'); each video exposes
    SOURCE, VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE, LANG, OFFICIAL,
    DAT_PUBLISHED, DURATION_SECONDS, and WATCH_URL/EMBED_URL/FILE_URL/THUMBNAIL_URL.
    id = TMDb ID_SERIE.

    Embedded related lists (cast, crew, companies, networks, topics, lists,
    collections, movements, awards, nominations, seasons, similar, recommendations) are paginated: by default
    each is capped to its first 50 rows and a top-level `pagination` block reports
    each list's total. To fetch more of one list, set `collection` to its name with
    `page` / `rows_per_page`; the response then contains just that list's page."""
    return await _mcp_get(f"/series/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_person")
async def _mcp_get_person(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a person (name, biography, birth/death dates, gender, country of
    birth, known-for department, IMDb/Wikidata IDs, popularity) plus embedded filmography
    split by role: movie_cast, movie_crew, series_cast, series_crew, groups, deaths,
    awards, and nominations. Also returns top-level wikipedia_images (ui_language-specific Wikipedia
    image metadata), wikipedia_content (Wikipedia section in the requested ui_language, title/content pairs
    from T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA, and a videos list
    sourced from Wikidata media resources (T_WC_WIKIDATA_MEDIA_RESOURCE,
    RESOURCE_KIND='video'; TMDb does not store person-level videos); each video
    exposes SOURCE='wikidata', VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE, LANG,
    DURATION_SECONDS, and WATCH_URL/EMBED_URL/FILE_URL/THUMBNAIL_URL. id = TMDb ID_PERSON.

    Embedded related lists (movie_cast, movie_crew, series_cast, series_crew, groups,
    deaths, awards, nominations) are paginated: by default each is capped to its
    first 50 rows and a top-level `pagination` block reports each list's total. A
    prolific person can have thousands of credits — to fetch more of one list, set
    `collection` to its name (e.g. 'movie_cast') with `page` / `rows_per_page`; the
    response then contains just that list's requested page."""
    return await _mcp_get(f"/persons/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_collection")
async def _mcp_get_collection(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a named collection (trilogy, saga, universe, franchise) plus member
    movies and TV series ordered by their position in the collection. The collection itself
    includes POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, and POPULARITY.
    Also returns top-level wikipedia_images (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)) and
    wikipedia_content (Wikipedia section title/content pairs in the requested ui_language from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA. id = ID_T2S_COLLECTION."""
    return await _mcp_get(f"/collections/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_topic")
async def _mcp_get_topic(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a topic (theme, keyword, recurring-character collection) plus linked
    movies and TV series ordered by their position in the topic. The topic itself includes
    POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, and POPULARITY.
    Also returns top-level wikipedia_images (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)) and
    wikipedia_content (Wikipedia section title/content pairs in the requested ui_language from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA. id = ID_TOPIC."""
    return await _mcp_get(f"/topics/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_list")
async def _mcp_get_list(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a named curated list (e.g. AFI Top 100, Criterion Collection)
    plus member movies and TV series ordered by their position. The list itself includes
    POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, and POPULARITY.
    Also returns top-level wikipedia_images (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)) and
    wikipedia_content (Wikipedia section title/content pairs in the requested ui_language from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA. id = ID_T2S_LIST."""
    return await _mcp_get(f"/lists/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_movement")
async def _mcp_get_movement(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a film movement or style (e.g. French New Wave, Neo-Noir) plus
    associated movies and TV series ordered by their position. The movement itself includes
    POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, and POPULARITY.
    Also returns top-level wikipedia_images (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)) and
    wikipedia_content (Wikipedia section title/content pairs in the requested ui_language from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA. id = ID_MOVEMENT."""
    return await _mcp_get(f"/movements/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_technical")
async def _mcp_get_technical(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a technical format (sound system, color/film/sound technology,
    or film format — e.g. Dolby, Technicolor, 70mm, IMAX, Cinemascope) plus associated
    movies and sibling technicals sharing the same TECHNICAL_TYPE. The technical itself
    includes WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, and POPULARITY. Each sibling
    carries MOVIE_COUNT for ranking. Also returns top-level wikipedia_images (ui_language-specific
    Wikipedia image metadata) and wikipedia_content (Wikipedia section in the requested ui_language,
    title/content pairs from T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA.
    id = ID_TECHNICAL."""
    return await _mcp_get(f"/technicals/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_genre")
async def _mcp_get_genre(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get a movie / TV genre from the closed vocabulary (T_WC_TMDB_GENRE) plus its
    member movies and TV series ordered best-rated first. The genre itself carries
    ID_GENRE, GENRE_NAME (localized to ui_language), and the APPLIES_TO_MOVIE /
    APPLIES_TO_SERIE flags. id = ID_GENRE, the TMDb genre code (e.g. 28 = Action,
    878 = Science Fiction, 18 = Drama). No Wikipedia block (genres have no ID_WIKIDATA)."""
    return await _mcp_get(f"/genres/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_group")
async def _mcp_get_group(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a person group (organization, club, musical group) plus
    associated persons ordered by their position. Also returns top-level
    wikipedia_images (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)) and wikipedia_content (en
    Wikipedia section title/content pairs from T_WC_WIKIPEDIA_PAGE_LANG_SECTION)
    keyed off ID_WIKIDATA. id = ID_GROUP."""
    return await _mcp_get(f"/groups/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_death")
async def _mcp_get_death(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a cause or circumstance of death plus associated persons
    ordered by their position. Also returns top-level wikipedia_images (ui_language-specific
    Wikipedia image metadata) and wikipedia_content (Wikipedia section in the requested ui_language,
    title/content pairs from T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA.
    id = ID_DEATH."""
    return await _mcp_get(f"/deaths/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_award")
async def _mcp_get_award(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for an award plus associated movies, TV series, and persons.
    Also returns top-level wikipedia_images (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)) and
    wikipedia_content (Wikipedia section title/content pairs in the requested ui_language from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA. id = ID_AWARD."""
    return await _mcp_get(f"/awards/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_nomination")
async def _mcp_get_nomination(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for an award nomination plus associated movies, TV series, and persons.
    Also returns top-level wikipedia_images (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)) and
    wikipedia_content (Wikipedia section title/content pairs in the requested ui_language from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off ID_WIKIDATA. id = ID_NOMINATION."""
    return await _mcp_get(f"/nominations/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_company")
async def _mcp_get_company(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a production company plus associated movies and TV series. The
    company itself includes LOGO_PATH, MOVIE_COUNT, SERIE_COUNT, IMDB_RATING_WEIGHTED,
    and POPULARITY. id = ID_COMPANY."""
    return await _mcp_get(f"/companies/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_network")
async def _mcp_get_network(id: int, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a TV network plus associated TV series. id = ID_NETWORK."""
    return await _mcp_get(f"/networks/{id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="get_location")
async def _mcp_get_location(wikidata_id: str, ui_language: str = "en", collection: Optional[str] = None, page: int = 1, rows_per_page: int = COLLECTION_ROWS_PER_PAGE_DEFAULT) -> str:
    """Get all fields for a location by Wikidata ID (e.g. 'Q90' for Paris) plus movies
    and series where it is a narrative location (P840) or filming location (P915).
    Also returns top-level wikipedia_images (Wikipedia image metadata in the requested ui_language (en/fr, English fallback)) and
    wikipedia_content (Wikipedia section title/content pairs in the requested ui_language from
    T_WC_WIKIPEDIA_PAGE_LANG_SECTION) keyed off the route's Wikidata ID."""
    return await _mcp_get(f"/locations/{wikidata_id}", ui_language, collection, page, rows_per_page)


@mcp.tool(name="list_samples")
async def _mcp_list_samples(ui_language: str = "en", set: str = "sample") -> str:
    """List the curated tree of suggested sample questions for the cinema/TV database.

    Returns a nested structure of categories (each with DESCRIPTION localized to
    ui_language) whose leaves are sample questions (QUESTION, localized) suitable for
    feeding to sql_search. Each sample also carries an `assertion` (ground-truth spec)
    and a `simulated_result` previewing the expected answer — entity rows hydrated with
    title/poster, a scalar value, or a count/bound expectation — without running the
    pipeline. Categories with no question anywhere in their subtree are omitted.

    ``set`` selects which curated set to return: "sample" (default — IS_SAMPLE = 1) or
    "showcase" (IS_SHOWCASE = 1 — the advisor home-screen picks). Each sample also
    carries IS_SHOWCASE. Supported ui_language values are "en" (default) and "fr";
    any other value falls back to English."""
    return await _mcp_get("/samples", ui_language, sample_set=set)


@mcp.resource("context://database-scope")
async def _mcp_database_scope() -> str:
    return """
    # Cinema & TV Database \u2014 Entity Reference

    ## Movie (T_WC_T2S_MOVIE)
    ID_MOVIE (TMDb ID), MOVIE_TITLE, DAT_RELEASE, RELEASE_YEAR, RELEASE_MONTH, RELEASE_DAY,
    RUNTIME (minutes), VOTE_AVERAGE (0-10), VOTE_COUNT, IMDB_RATING, IMDB_RATING_WEIGHTED,
    REVENUE (USD, 0 when unknown), BUDGET (USD, 0 when unknown), ORIGINAL_LANGUAGE (2-letter),
    STATUS (Released / Post Production / In Production / Planned / Rumored / Canceled),
    TAGLINE, POSTER_PATH, BACKDROP_PATH, VIDEO (1 if video release),
    IS_MOVIE (1/0), IS_DOCUMENTARY (1/0), IS_SHORT_FILM (1/0),
    IS_COLOR (1/0), IS_BLACK_AND_WHITE (1/0), IS_SILENT (1/0),
    ID_IMDB (tt...), ID_WIKIDATA (Q...), ID_CRITERION, ID_CRITERION_SPINE,
    ALIASES
    (Aspect ratios are not filtered on the movie row; they live as rows in
    T_WC_T2S_TECHNICAL with TECHNICAL_TYPE='aspect_ratio' and are linked
    many-to-many through T_WC_T2S_MOVIE_TECHNICAL, matching how all other
    technical attributes are modeled.)

    ## TV Series (T_WC_T2S_SERIE)
    ID_SERIE (TMDb ID), SERIE_TITLE, DAT_FIRST_AIR, DAT_LAST_AIR,
    FIRST_AIR_YEAR, LAST_AIR_YEAR, NUMBER_OF_SEASONS, NUMBER_OF_EPISODES,
    VOTE_AVERAGE, VOTE_COUNT, IMDB_RATING, IMDB_RATING_WEIGHTED,
    ORIGINAL_LANGUAGE, STATUS, TAGLINE,
    SERIE_TYPE (Scripted / Miniseries / Documentary / Reality / News / Talk Show / Video),
    ID_IMDB, ID_WIKIDATA, ALIASES, PLEX_MEDIA_KEY

    ## Person (T_WC_T2S_PERSON)
    ID_PERSON (TMDb ID), PERSON_NAME, BIOGRAPHY,
    BIRTH_YEAR, BIRTH_MONTH, BIRTH_DAY, DEATH_YEAR, DEATH_MONTH, DEATH_DAY,
    GENDER (1=female, 2=male), COUNTRY_OF_BIRTH (2-letter lowercase),
    KNOWN_FOR_DEPARTMENT (Acting / Directing / Writing / Production / ...),
    POPULARITY, PROFILE_PATH, ID_IMDB (nm...), ID_WIKIDATA, ALIASES

    ## Relationships \u2014 Movie
    - Cast/Crew: PERSON \u2194 MOVIE via T_WC_T2S_PERSON_MOVIE
        CREDIT_TYPE = 'cast' \u2192 CAST_CHARACTER, DISPLAY_ORDER
        CREDIT_TYPE = 'crew' \u2192 CREW_DEPARTMENT, DISPLAY_ORDER
        CREW_DEPARTMENT values: Art, Camera, Costume & Make-Up, Crew, Directing,
          Editing, Lighting, Production, Sound, Visual Effects, Writing
    - Genres: T_WC_T2S_MOVIE_GENRE.ID_GENRE (INT) -> T_WC_TMDB_GENRE (id, name)
        28 Action, 12 Adventure, 16 Animation, 35 Comedy, 80 Crime,
        18 Drama, 10751 Family, 14 Fantasy, 36 History, 27 Horror,
        10402 Music, 9648 Mystery, 10749 Romance, 878 Sci-Fi,
        53 Thriller, 10752 War, 37 Western, 10770 TV Movie, 99 Documentary
        A genre is itself a listable entity (result_entity = genre, get_genre,
        /genres/{ID_GENRE}) — used when the genres ARE the answer ("what are the
        movie genres?"). When a genre only scopes the query ("Sci-Fi movies") it is
        a FILTER, not the result.
    - Companies: T_WC_T2S_MOVIE_COMPANY \u2192 T_WC_T2S_COMPANY
    - Production countries: T_WC_T2S_MOVIE_PRODUCTION_COUNTRY (COUNTRY_CODE 2-letter upper)
    - Spoken languages: T_WC_T2S_MOVIE_SPOKEN_LANGUAGE (SPOKEN_LANGUAGE 2-letter lower)
    - Technical specs: T_WC_T2S_MOVIE_TECHNICAL (ID_TECHNICAL 1-56, see prompt for codes)
    - Topics: T_WC_T2S_MOVIE_TOPIC \u2192 T_WC_T2S_TOPIC (DISPLAY_ORDER)
    - Collections: T_WC_T2S_MOVIE_COLLECTION \u2192 T_WC_T2S_COLLECTION (DISPLAY_ORDER)
    - Movements: T_WC_T2S_MOVIE_MOVEMENT \u2192 T_WC_T2S_MOVEMENT (DISPLAY_ORDER)
    - Lists: T_WC_T2S_MOVIE_LIST \u2192 T_WC_T2S_LIST (DISPLAY_ORDER)
    - Awards: T_WC_T2S_MOVIE_AWARD \u2192 T_WC_T2S_AWARD (DISPLAY_ORDER)
    - Nominations: T_WC_T2S_MOVIE_NOMINATION \u2192 T_WC_T2S_NOMINATION (DISPLAY_ORDER)
    - Locations: MOVIE.ID_WIKIDATA \u2192 T_WC_WIKIDATA_ITEM_PROPERTY
        ID_PROPERTY = 'P840' (narrative location) or 'P915' (filming location)
        \u2192 T_WC_T2S_ITEM (ID_WIKIDATA, ITEM_LABEL, DESCRIPTION)

    ## Relationships \u2014 TV Series
    Same structure as movies with T_WC_T2S_SERIE_* equivalents for all join tables.
    Additional: T_WC_T2S_SERIE_NETWORK \u2192 T_WC_T2S_NETWORK
    Additional CREW_DEPARTMENT for series: Creator

    ## Relationships \u2014 Person
    - Movie credits: T_WC_T2S_PERSON_MOVIE (CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT)
    - Series credits: T_WC_T2S_PERSON_SERIE (CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB)
    - Groups: T_WC_T2S_PERSON_GROUP \u2192 T_WC_T2S_GROUP
    - Causes of death: T_WC_T2S_PERSON_DEATH \u2192 T_WC_T2S_DEATH
    - Awards: T_WC_T2S_PERSON_AWARD \u2192 T_WC_T2S_AWARD
    - Nominations: T_WC_T2S_PERSON_NOMINATION \u2192 T_WC_T2S_NOMINATION

    ## Other Entities
    - T_WC_T2S_COLLECTION: COLLECTION_NAME, OVERVIEW, MOVIE_COUNT, SERIE_COUNT,
        POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING, IMDB_RATING_WEIGHTED, POPULARITY
        Holds trilogies and named series of works (e.g., Dollars Trilogy, James Bond
        Collection, Kill Bill - Saga) AND universes/franchises (e.g., Star Wars, Marvel
        Cinematic Universe, DC Extended Universe, Batman universe, Middle-Earth, Harry
        Potter movies, James Bond films).
    - T_WC_T2S_TOPIC: TOPIC_NAME, TOPIC_TYPE, TOPIC_SOURCE, LANG, MOVIE_COUNT, SERIE_COUNT,
        POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING, IMDB_RATING_WEIGHTED, POPULARITY
        Holds themes (e.g., World War II, Christmas) and recurring-character collections
        (e.g., Philip Marlowe, Sherlock Holmes). Universes and franchises are NOT here —
        they live in T_WC_T2S_COLLECTION.
    - T_WC_T2S_LIST: LIST_NAME, OVERVIEW, LIST_TYPE, MOVIE_COUNT, SERIE_COUNT,
        POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING, IMDB_RATING_WEIGHTED, POPULARITY
        Holds curated rankings/canons/registries (e.g., Sight and Sound, IMDb Top 250,
        AFI Top 100). Universes and franchises are NOT here — they live in
        T_WC_T2S_COLLECTION.
    - T_WC_T2S_MOVEMENT: MOVEMENT_NAME, OVERVIEW, MOVIE_COUNT, SERIE_COUNT,
        POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING, IMDB_RATING_WEIGHTED, POPULARITY
    - T_WC_T2S_GROUP: GROUP_NAME, GROUP_TYPE, OVERVIEW, PERSON_COUNT, POPULARITY
    - T_WC_T2S_DEATH: DEATH_NAME, DEATH_TYPE, OVERVIEW, PERSON_COUNT, POPULARITY
    - T_WC_T2S_AWARD: AWARD_NAME, AWARD_TYPE, MOVIE_COUNT, SERIE_COUNT, PERSON_COUNT,
        IMDB_RATING, IMDB_RATING_WEIGHTED, POPULARITY
    - T_WC_T2S_NOMINATION: NOMINATION_NAME, NOMINATION_TYPE, MOVIE_COUNT, SERIE_COUNT,
        PERSON_COUNT, IMDB_RATING, IMDB_RATING_WEIGHTED, POPULARITY
    - T_WC_T2S_COMPANY: COMPANY_NAME, HEADQUARTERS, ORIGIN_COUNTRY, LOGO_PATH,
        MOVIE_COUNT, SERIE_COUNT, IMDB_RATING_WEIGHTED, POPULARITY
    - T_WC_T2S_NETWORK: NETWORK_NAME, ORIGIN_COUNTRY, LOGO_PATH
    - T_WC_T2S_ITEM: ID_WIKIDATA, ITEM_LABEL, DESCRIPTION, INSTANCE_OF

    ## Useful value ranges
    - VOTE_AVERAGE: 0 to 10, meaningful above VOTE_COUNT > 200
    - IMDB_RATING: 0 to 10 raw; IMDB_RATING_WEIGHTED is the weighted adjusted score
    - DAT_RELEASE / DAT_FIRST_AIR: from 1870 to early 2024
    - REVENUE / BUDGET: in USD, 0 when unknown
    - RUNTIME: in minutes
    - GENDER: 1 = female, 2 = male
    - COUNTRY_OF_BIRTH: 2-letter lowercase ISO code
    - ORIGIN_COUNTRY / COUNTRY_CODE: 2-letter uppercase ISO code

    ## Coverage
    ~620k movies, ~88k TV series, ~890k persons
    """


async def _verify_mcp_bearer(request: Request, call_next):
    if request.url.path.startswith("/mcp"):
        if MCP_API_KEY:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {MCP_API_KEY}":
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)


app.add_middleware(BaseHTTPMiddleware, dispatch=_verify_mcp_bearer)
# FastAPI mount: app.mount("/mcp", ...) → app.mount("", ...) (avoid double /mcp/mcp path)
app.mount("", mcp_app)

if __name__ == "__main__":
    import uvicorn
    
    # Determine port based on version: even = API_PORT_BLUE, odd = API_PORT_GREEN
    version_parts = strapiversion.split('.')
    patch_version = int(version_parts[2])  # Use patch version (last number)
    api_port = API_PORT_BLUE if patch_version % 2 == 0 else API_PORT_GREEN
    
    result = {"message": f"Text2SQL API start version {strapiversion} on port {api_port}"}
    logs.log_usage("start", result, strapiversion)
    print(f"Starting API version {strapiversion} on port {api_port} (patch version {patch_version} is {'even' if patch_version % 2 == 0 else 'odd'})")
    uvicorn.run(app, host="0.0.0.0", port=api_port)
