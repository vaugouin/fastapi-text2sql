# MCP Integration Guide — Text-to-SQL FastAPI

## Overview

This document describes how to expose a FastAPI text-to-SQL API as a remote MCP (Model Context Protocol) server, making it available across all Claude clients (web, desktop, mobile) without any local installation.

The architecture relies on two layers:
- A **search endpoint** that accepts natural language questions and returns a result set
- **Entity endpoints** that return full details for a specific entity by ID

Claude acts as the orchestrator: it calls `sql_search` to find matching entities, then calls entity-specific tools to fetch full details when needed.

---

## 1. Add a Remote MCP Endpoint to Your Existing FastAPI App

Since your FastAPI is already served over HTTPS via Nginx on your VPS, you only need to mount an MCP endpoint on your existing app. No new Docker container, no new Nginx config, no new port.

Install the MCP SDK:

```bash
pip install fastmcp httpx
```

Mount the MCP server on your existing FastAPI app:

```python
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from fastmcp import FastMCP
import httpx
import json
import os

# 1. Instantiate MCP — stateless_http is passed to http_app(), not to the constructor
mcp = FastMCP("text2sql")
mcp_app = mcp.http_app(stateless_http=True)

# 2. Pass mcp_app.lifespan to FastAPI so FastMCP lifecycle hooks run correctly
app = FastAPI(lifespan=mcp_app.lifespan)

MCP_API_KEY           = os.getenv("MCP_API_KEY", "")            # empty → /mcp is open
MCP_INTERNAL_API_KEY  = os.getenv("MCP_INTERNAL_API_KEY",
                            os.getenv("API_KEYS", "").split(",")[0].strip())
MCP_INTERNAL_BASE_URL = os.getenv("MCP_INTERNAL_BASE_URL", "http://127.0.0.1:8000")

# --- MCP Tools ---

@mcp.tool()
async def sql_search(question: str) -> str:
    """
    Query the cinema and TV database in natural language.

    Covers movies, TV series, persons (actors, directors, writers, crew),
    production companies, TV networks, topics (universes, franchises, themes),
    curated lists, collections (trilogies, sagas), film movements, person groups,
    causes of death, awards, nominations, and locations (narrative or filming).

    The result returns rows with entity IDs and key fields (title, release date,
    IMDb rating, poster path). Use the entity tools below to fetch full details.

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
                json={"question": question},
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_movie(id: int) -> str:
    """Get all fields for a movie (title, release date, runtime, budget, revenue, ratings,
    plot, IMDb/Wikidata IDs, aspect ratio, color/B&W/silent flags) plus embedded relations:
    cast, crew, genre codes, production companies, production countries, spoken languages,
    topics, collections, movements, awards, and nominations. id = TMDb ID_MOVIE."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/movies/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_series(id: int) -> str:
    """Get all fields for a TV series (title, first/last air date, number of seasons and
    episodes, ratings, status, Wikidata/IMDb IDs) plus embedded relations: cast, crew,
    genre codes, companies, networks, production countries, spoken languages, topics,
    collections, movements, awards, and nominations. id = TMDb ID_SERIE."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/series/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_person(id: int) -> str:
    """Get all fields for a person (name, biography, birth/death dates, gender, country of
    birth, known-for department, IMDb/Wikidata IDs, popularity) plus embedded filmography
    split by role: movie_cast, movie_crew, series_cast, series_crew, groups, deaths,
    awards, and nominations. id = TMDb ID_PERSON."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/persons/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_collection(id: int) -> str:
    """Get all fields for a named collection (trilogy, saga, franchise) plus member movies
    and TV series ordered by their position in the collection. id = ID_T2S_COLLECTION."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/collections/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_topic(id: int) -> str:
    """Get all fields for a topic (universe, franchise, theme, keyword) plus linked movies
    and TV series ordered by their position in the topic. id = ID_TOPIC."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/topics/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_list(id: int) -> str:
    """Get all fields for a named curated list (e.g. AFI Top 100, Criterion Collection)
    plus member movies and TV series ordered by their position. id = ID_T2S_LIST."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/lists/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_movement(id: int) -> str:
    """Get all fields for a film movement or style (e.g. French New Wave, Neo-Noir) plus
    associated movies and TV series ordered by their position. id = ID_MOVEMENT."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/movements/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_group(id: int) -> str:
    """Get all fields for a person group (organization, club, musical group) plus
    associated persons ordered by their position. id = ID_GROUP."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/groups/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_death(id: int) -> str:
    """Get all fields for a cause or circumstance of death plus associated persons
    ordered by their position. id = ID_DEATH."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/deaths/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_award(id: int) -> str:
    """Get all fields for an award plus associated movies, TV series, and persons.
    id = ID_AWARD."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/awards/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_nomination(id: int) -> str:
    """Get all fields for an award nomination plus associated movies, TV series, and persons.
    id = ID_NOMINATION."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/nominations/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_company(id: int) -> str:
    """Get all fields for a production company plus associated movies and TV series.
    id = ID_COMPANY."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/companies/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_network(id: int) -> str:
    """Get all fields for a TV network plus associated TV series. id = ID_NETWORK."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/networks/{id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
async def get_location(wikidata_id: str) -> str:
    """Get all fields for a location by Wikidata ID (e.g. 'Q90' for Paris) plus movies
    and series where it is a narrative location (P840) or filming location (P915)."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{MCP_INTERNAL_BASE_URL}/locations/{wikidata_id}",
                headers={"X-API-Key": MCP_INTERNAL_API_KEY},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})

# --- Bearer-token middleware and mount ---

async def _verify_mcp_bearer(request: Request, call_next):
    if request.url.path.startswith("/mcp"):
        if MCP_API_KEY:                        # skip check when key is not set
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {MCP_API_KEY}":
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)

app.add_middleware(BaseHTTPMiddleware, dispatch=_verify_mcp_bearer)

# Mount at "" (not "/mcp") to avoid double /mcp/mcp path
# Nginx proxies /mcp → FastAPI; FastAPI sees /mcp/… paths; FastMCP handles them
app.mount("", mcp_app)
```

Your MCP server is then reachable at:

```
https://yourdomain.com/mcp
```

---

## 2. Entity Endpoints

Each entity endpoint returns all properties for a given entity ID, including embedded relations (cast, crew, filmography). Join tables such as casting and crew are never exposed as standalone endpoints — they are embedded in their parent entity response.

### Endpoint map

| Endpoint | Returns |
|---|---|
| `GET /movies/{id}` | All movie fields + cast, crew, genres, companies, topics, collections, movements, awards, nominations |
| `GET /series/{id}` | All series fields + cast, crew, genres, companies, networks, topics, collections, movements, awards, nominations |
| `GET /persons/{id}` | All person fields + movie_cast, movie_crew, series_cast, series_crew, groups, deaths, awards, nominations |
| `GET /collections/{id}` | Collection fields + member movies and series ordered by position |
| `GET /topics/{id}` | Topic fields + linked movies and series ordered by position |
| `GET /lists/{id}` | List fields + member movies and series ordered by position |
| `GET /movements/{id}` | Movement fields + associated movies and series |
| `GET /groups/{id}` | Group fields + associated persons |
| `GET /deaths/{id}` | Death/cause fields + associated persons |
| `GET /awards/{id}` | Award fields + associated movies, series, and persons |
| `GET /nominations/{id}` | Nomination fields + associated movies, series, and persons |
| `GET /companies/{id}` | Company fields + associated movies and series |
| `GET /networks/{id}` | Network fields + associated TV series |
| `GET /locations/{wikidata_id}` | Item fields + movies and series by narrative (P840) or filming (P915) location |

The guiding principle: **one tool call should answer one user intent**. If Claude needs two tool calls to answer a simple question, the entity design is too granular.

---

## 3. Sample JSON Responses

### sql_search — result set

The response from `POST /search/text2sql` contains the full pipeline trace alongside the result rows.

```json
{
  "question": "best Scorsese films",
  "question_hashed": "a9f3b2d4e5c6...",
  "sql_query": "SELECT DISTINCT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.MOVIE_TITLE, T_WC_T2S_MOVIE.DAT_RELEASE, T_WC_T2S_MOVIE.ID_IMDB, T_WC_T2S_MOVIE.IMDB_RATING, T_WC_T2S_MOVIE.IMDB_RATING_ADJUSTED, T_WC_T2S_MOVIE.POSTER_PATH FROM T_WC_T2S_MOVIE JOIN T_WC_T2S_PERSON_MOVIE ON T_WC_T2S_PERSON_MOVIE.ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE JOIN T_WC_T2S_PERSON ON T_WC_T2S_PERSON_MOVIE.ID_PERSON = T_WC_T2S_PERSON.ID_PERSON WHERE T_WC_T2S_PERSON.PERSON_NAME = 'Martin Scorsese' AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'crew' ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_ADJUSTED DESC",
  "sql_query_anonymized": "SELECT DISTINCT T_WC_T2S_MOVIE.ID_MOVIE, ... WHERE T_WC_T2S_PERSON.PERSON_NAME = '{{Person_name1}}' AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'crew' ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_ADJUSTED DESC",
  "justification": "Searching for movies with {{Person_name1}} as a crew member, ordered by adjusted IMDb rating.",
  "justification_anonymized": "Searching for movies with {{Person_name1}} as a crew member, ordered by adjusted IMDb rating.",
  "error": "",
  "entity_extraction": { "Person_name1": "Martin Scorsese" },
  "question_anonymized": "best {{Person_name1}} films",
  "entity_extraction_processing_time": 0.42,
  "text2sql_processing_time": 1.85,
  "embeddings_processing_time": 0.0,
  "embeddings_cache_search_time": 0.0,
  "query_execution_time": 0.08,
  "total_processing_time": 2.41,
  "page": 1,
  "llm_defined_limit": null,
  "llm_defined_offset": null,
  "limit": 50,
  "offset": 0,
  "rows_per_page": 50,
  "cached_exact_question": false,
  "cached_anonymized_question": false,
  "cached_anonymized_question_embedding": false,
  "ambiguous_question_for_text2sql": false,
  "llm_model_entity_extraction": "gpt-4o",
  "llm_model_text2sql": "gpt-4o",
  "llm_model_complex": "gpt-4o",
  "api_version": "1.1.15",
  "messages": [
    { "position": 1, "text": "Attempting to retrieve exact question from cache." },
    { "position": 2, "text": "Exact question not found in cache." },
    { "position": 3, "text": "Calling entity extraction." }
  ],
  "result": [
    { "index": 0, "data": { "ID_MOVIE": 769, "MOVIE_TITLE": "GoodFellas", "DAT_RELEASE": "1990-09-12", "ID_IMDB": "tt0099685", "IMDB_RATING": 8.7, "IMDB_RATING_ADJUSTED": 8.5, "POSTER_PATH": "/aKuFiU82s5ISJpGZp7YkIr3kCUd.jpg" } },
    { "index": 1, "data": { "ID_MOVIE": 423, "MOVIE_TITLE": "The Departed", "DAT_RELEASE": "2006-10-05", "ID_IMDB": "tt0407887", "IMDB_RATING": 8.5, "IMDB_RATING_ADJUSTED": 8.2, "POSTER_PATH": "/nT97ifVT2J1yMQmeq20Qblg61T.jpg" } }
  ]
}
```

### get_movie — full entity with embedded relations

```json
{
  "ID_MOVIE": 27205,
  "MOVIE_TITLE": "Inception",
  "DAT_RELEASE": "2010-07-16",
  "RELEASE_YEAR": 2010,
  "RELEASE_MONTH": 7,
  "RELEASE_DAY": 16,
  "ID_IMDB": "tt1375666",
  "ID_WIKIDATA": "Q25188",
  "POSTER_PATH": "/9gk7adHYeDvHkCSEqAvQNLV5Uge.jpg",
  "BACKDROP_PATH": "/s3TBrRGB1iav7gFOCNx3H31MoES.jpg",
  "POPULARITY": 58.3,
  "ORIGINAL_LANGUAGE": "en",
  "STATUS": "Released",
  "BUDGET": 160000000,
  "RUNTIME": 148,
  "REVENUE": 836848102,
  "TAGLINE": "Your mind is the scene of the crime.",
  "VIDEO": 0,
  "VOTE_AVERAGE": 8.4,
  "VOTE_COUNT": 35789,
  "IS_COLOR": 1,
  "IS_BLACK_AND_WHITE": 0,
  "IS_SILENT": 0,
  "ASPECT_RATIO": "2.35",
  "IS_MOVIE": 1,
  "IS_DOCUMENTARY": 0,
  "IS_SHORT_FILM": 0,
  "IMDB_RATING": 8.8,
  "IMDB_RATING_ADJUSTED": 8.7,
  "WIKIDATA_TITLE": "Inception",
  "ALIASES": null,
  "PLEX_MEDIA_KEY": null,
  "ID_CRITERION": null,
  "ID_CRITERION_SPINE": null,
  "INSTANCE_OF": "film",
  "PLOT": "Dom Cobb is a skilled thief who specialises in stealing secrets from within dreams...",
  "CAST": null,
  "PRODUCTION": "Nolan began developing the screenplay in the early 2000s...",
  "RECEPTION": "Inception received widespread critical acclaim upon release...",
  "SOUNDTRACK": null,
  "cast": [
    { "ID_PERSON": 6193, "PERSON_NAME": "Leonardo DiCaprio", "CREDIT_TYPE": "cast", "CAST_CHARACTER": "Cobb", "CREW_DEPARTMENT": null, "DISPLAY_ORDER": 1 },
    { "ID_PERSON": 24045, "PERSON_NAME": "Joseph Gordon-Levitt", "CREDIT_TYPE": "cast", "CAST_CHARACTER": "Arthur", "CREW_DEPARTMENT": null, "DISPLAY_ORDER": 2 }
  ],
  "crew": [
    { "ID_PERSON": 525, "PERSON_NAME": "Christopher Nolan", "CREDIT_TYPE": "crew", "CAST_CHARACTER": null, "CREW_DEPARTMENT": "Directing", "DISPLAY_ORDER": 1 },
    { "ID_PERSON": 749, "PERSON_NAME": "Hans Zimmer", "CREDIT_TYPE": "crew", "CAST_CHARACTER": null, "CREW_DEPARTMENT": "Sound", "DISPLAY_ORDER": 2 }
  ],
  "genres": [28, 878, 12],
  "companies": [
    { "ID_COMPANY": 9996, "COMPANY_NAME": "Syncopy" },
    { "ID_COMPANY": 174, "COMPANY_NAME": "Warner Bros. Pictures" }
  ],
  "production_countries": ["US", "GB"],
  "spoken_languages": ["en", "ja", "fr"],
  "topics": [],
  "collections": [],
  "movements": [],
  "awards": [],
  "nominations": []
}
```

### get_person — biography + filmography by role

```json
{
  "ID_PERSON": 525,
  "PERSON_NAME": "Christopher Nolan",
  "ID_IMDB": "nm0634240",
  "ID_WIKIDATA": "Q25191",
  "BIOGRAPHY": "Christopher Edward Nolan CBE is a British-American filmmaker...",
  "BIRTH_YEAR": 1970,
  "BIRTH_MONTH": 7,
  "BIRTH_DAY": 30,
  "DEATH_YEAR": null,
  "DEATH_MONTH": null,
  "DEATH_DAY": null,
  "GENDER": 2,
  "PROFILE_PATH": "/xuAIuYSmsUzKlUMBFGVZaWsY3DZ.jpg",
  "COUNTRY_OF_BIRTH": "gb",
  "POPULARITY": 28.4,
  "KNOWN_FOR_DEPARTMENT": "Directing",
  "WIKIDATA_NAME": "Christopher Nolan",
  "ALIASES": null,
  "INSTANCE_OF": "human",
  "movie_cast": [],
  "movie_crew": [
    { "ID_MOVIE": 27205, "MOVIE_TITLE": "Inception", "DAT_RELEASE": "2010-07-16", "IMDB_RATING_ADJUSTED": 8.7, "CREDIT_TYPE": "crew", "CAST_CHARACTER": null, "CREW_DEPARTMENT": "Directing", "DISPLAY_ORDER": 1 },
    { "ID_MOVIE": 157336, "MOVIE_TITLE": "Interstellar", "DAT_RELEASE": "2014-11-05", "IMDB_RATING_ADJUSTED": 8.4, "CREDIT_TYPE": "crew", "CAST_CHARACTER": null, "CREW_DEPARTMENT": "Directing", "DISPLAY_ORDER": 1 }
  ],
  "series_cast": [],
  "series_crew": [],
  "groups": [],
  "deaths": [],
  "awards": [],
  "nominations": []
}
```

---

## 4. Tool Documentation — Layer 1 (Docstrings) and Layer 2 (Resources)

Claude determines whether to call a tool based solely on its docstring. The docstring is the primary documentation layer — it is always loaded at the start of every conversation.

### Layer 1 — Tool docstrings

Each docstring should include:

- **What entities are covered** — so Claude knows what is queryable
- **Example question types** — reduces ambiguity on edge cases
- **Explicit exclusions** — prevents wasted calls on out-of-scope questions
- **Data coverage and cutoff date** — Claude won't assume real-time data
- **Output format hints** — Claude formats responses correctly
- **URL patterns for IDs** — Claude builds correct hyperlinks
- **Pointer to the resource** — Claude knows where to get deeper context

### Layer 2 — MCP Resource (semantic schema)

The resource is not loaded automatically. Claude reads it when the docstring points to it or when the user asks a complex question requiring precise field knowledge. It should contain a semantic description of entities and their properties — not the raw SQL DDL.

```python
@mcp.resource("context://database-scope")
async def database_scope() -> str:
    return """
    # Cinema & TV Database — Entity Reference

    ## Movie (T_WC_T2S_MOVIE)
    ID_MOVIE (TMDb ID), MOVIE_TITLE, DAT_RELEASE, RELEASE_YEAR, RELEASE_MONTH, RELEASE_DAY,
    RUNTIME (minutes), VOTE_AVERAGE (0-10), VOTE_COUNT, IMDB_RATING, IMDB_RATING_ADJUSTED,
    REVENUE (USD, 0 when unknown), BUDGET (USD, 0 when unknown), ORIGINAL_LANGUAGE (2-letter),
    STATUS (Released / Post Production / In Production / Planned / Rumored / Canceled),
    TAGLINE, POSTER_PATH, BACKDROP_PATH, VIDEO (1 if video release),
    IS_MOVIE (1/0), IS_DOCUMENTARY (1/0), IS_SHORT_FILM (1/0),
    IS_COLOR (1/0), IS_BLACK_AND_WHITE (1/0), IS_SILENT (1/0), ASPECT_RATIO,
    ID_IMDB (tt...), ID_WIKIDATA (Q...), ID_CRITERION, ID_CRITERION_SPINE,
    ALIASES, PLOT, CAST (text, use dedicated tables for structured queries),
    PRODUCTION, RECEPTION, SOUNDTRACK

    ## TV Series (T_WC_T2S_SERIE)
    ID_SERIE (TMDb ID), SERIE_TITLE, DAT_FIRST_AIR, DAT_LAST_AIR,
    FIRST_AIR_YEAR, LAST_AIR_YEAR, NUMBER_OF_SEASONS, NUMBER_OF_EPISODES,
    VOTE_AVERAGE, VOTE_COUNT, IMDB_RATING, IMDB_RATING_ADJUSTED,
    ORIGINAL_LANGUAGE, STATUS, TAGLINE,
    SERIE_TYPE (Scripted / Miniseries / Documentary / Reality / News / Talk Show / Video),
    ID_IMDB, ID_WIKIDATA, ALIASES, PLEX_MEDIA_KEY

    ## Person (T_WC_T2S_PERSON)
    ID_PERSON (TMDb ID), PERSON_NAME, BIOGRAPHY,
    BIRTH_YEAR, BIRTH_MONTH, BIRTH_DAY, DEATH_YEAR, DEATH_MONTH, DEATH_DAY,
    GENDER (1=female, 2=male), COUNTRY_OF_BIRTH (2-letter lowercase),
    KNOWN_FOR_DEPARTMENT (Acting / Directing / Writing / Production / ...),
    POPULARITY, PROFILE_PATH, ID_IMDB (nm...), ID_WIKIDATA, ALIASES

    ## Relationships — Movie
    - Cast/Crew: PERSON ↔ MOVIE via T_WC_T2S_PERSON_MOVIE
        CREDIT_TYPE = 'cast' → CAST_CHARACTER, DISPLAY_ORDER
        CREDIT_TYPE = 'crew' → CREW_DEPARTMENT, DISPLAY_ORDER
        CREW_DEPARTMENT values: Art, Camera, Costume & Make-Up, Crew, Directing,
          Editing, Lighting, Production, Sound, Visual Effects, Writing
    - Genres: T_WC_T2S_MOVIE_GENRE.ID_GENRE (INT)
        28 Action, 12 Adventure, 16 Animation, 35 Comedy, 80 Crime,
        18 Drama, 10751 Family, 14 Fantasy, 36 History, 27 Horror,
        10402 Music, 9648 Mystery, 10749 Romance, 878 Sci-Fi,
        53 Thriller, 10752 War, 37 Western, 10770 TV Movie, 99 Documentary
    - Companies: T_WC_T2S_MOVIE_COMPANY → T_WC_T2S_COMPANY
    - Production countries: T_WC_T2S_MOVIE_PRODUCTION_COUNTRY (COUNTRY_CODE 2-letter upper)
    - Spoken languages: T_WC_T2S_MOVIE_SPOKEN_LANGUAGE (SPOKEN_LANGUAGE 2-letter lower)
    - Technical specs: T_WC_T2S_MOVIE_TECHNICAL (ID_TECHNICAL 1-56, see prompt for codes)
    - Topics: T_WC_T2S_MOVIE_TOPIC → T_WC_T2S_TOPIC (DISPLAY_ORDER)
    - Collections: T_WC_T2S_MOVIE_COLLECTION → T_WC_T2S_COLLECTION (DISPLAY_ORDER)
    - Movements: T_WC_T2S_MOVIE_MOVEMENT → T_WC_T2S_MOVEMENT (DISPLAY_ORDER)
    - Lists: T_WC_T2S_MOVIE_LIST → T_WC_T2S_LIST (DISPLAY_ORDER)
    - Awards: T_WC_T2S_MOVIE_AWARD → T_WC_T2S_AWARD (DISPLAY_ORDER)
    - Nominations: T_WC_T2S_MOVIE_NOMINATION → T_WC_T2S_NOMINATION (DISPLAY_ORDER)
    - Locations: MOVIE.ID_WIKIDATA → T_WC_WIKIDATA_ITEM_PROPERTY
        ID_PROPERTY = 'P840' (narrative location) or 'P915' (filming location)
        → T_WC_T2S_ITEM (ID_WIKIDATA, ITEM_LABEL, DESCRIPTION)

    ## Relationships — TV Series
    Same structure as movies with T_WC_T2S_SERIE_* equivalents for all join tables.
    Additional: T_WC_T2S_SERIE_NETWORK → T_WC_T2S_NETWORK
    Additional CREW_DEPARTMENT for series: Creator

    ## Relationships — Person
    - Movie credits: T_WC_T2S_PERSON_MOVIE (CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT)
    - Series credits: T_WC_T2S_PERSON_SERIE (CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB)
    - Groups: T_WC_T2S_PERSON_GROUP → T_WC_T2S_GROUP
    - Causes of death: T_WC_T2S_PERSON_DEATH → T_WC_T2S_DEATH
    - Awards: T_WC_T2S_PERSON_AWARD → T_WC_T2S_AWARD
    - Nominations: T_WC_T2S_PERSON_NOMINATION → T_WC_T2S_NOMINATION

    ## Other Entities
    - T_WC_T2S_COLLECTION: COLLECTION_NAME, OVERVIEW, MOVIE_COUNT, SERIE_COUNT,
        IMDB_RATING, IMDB_RATING_ADJUSTED, POSTER_PATH
    - T_WC_T2S_TOPIC: TOPIC_NAME, TOPIC_TYPE, TOPIC_SOURCE, LANG,
        IMDB_RATING, IMDB_RATING_ADJUSTED, POSTER_PATH
    - T_WC_T2S_LIST: LIST_NAME, OVERVIEW, LIST_TYPE, MOVIE_COUNT, SERIE_COUNT,
        IMDB_RATING, IMDB_RATING_ADJUSTED, POSTER_PATH
    - T_WC_T2S_MOVEMENT: MOVEMENT_NAME, OVERVIEW, MOVIE_COUNT, SERIE_COUNT,
        IMDB_RATING, IMDB_RATING_ADJUSTED, POSTER_PATH
    - T_WC_T2S_GROUP: GROUP_NAME, GROUP_TYPE, OVERVIEW, PERSON_COUNT, POPULARITY
    - T_WC_T2S_DEATH: DEATH_NAME, DEATH_TYPE, OVERVIEW, PERSON_COUNT, POPULARITY
    - T_WC_T2S_AWARD: AWARD_NAME, AWARD_TYPE, MOVIE_COUNT, SERIE_COUNT, PERSON_COUNT,
        IMDB_RATING, IMDB_RATING_ADJUSTED, POPULARITY
    - T_WC_T2S_NOMINATION: NOMINATION_NAME, NOMINATION_TYPE, MOVIE_COUNT, SERIE_COUNT,
        PERSON_COUNT, IMDB_RATING, IMDB_RATING_ADJUSTED, POPULARITY
    - T_WC_T2S_COMPANY: COMPANY_NAME, HEADQUARTERS, ORIGIN_COUNTRY, LOGO_PATH
    - T_WC_T2S_NETWORK: NETWORK_NAME, ORIGIN_COUNTRY, LOGO_PATH
    - T_WC_T2S_ITEM: ID_WIKIDATA, ITEM_LABEL, DESCRIPTION, INSTANCE_OF

    ## Useful value ranges
    - VOTE_AVERAGE: 0 to 10, meaningful above VOTE_COUNT > 200
    - IMDB_RATING: 0 to 10 raw; IMDB_RATING_ADJUSTED is the weighted adjusted score
    - DAT_RELEASE / DAT_FIRST_AIR: from 1870 to early 2024
    - REVENUE / BUDGET: in USD, 0 when unknown
    - RUNTIME: in minutes
    - GENDER: 1 = female, 2 = male
    - COUNTRY_OF_BIRTH: 2-letter lowercase ISO code
    - ORIGIN_COUNTRY / COUNTRY_CODE: 2-letter uppercase ISO code

    ## Coverage
    ~620k movies, ~88k TV series, ~890k persons
    """
```

---

## 5. Deploying and Using the MCP Endpoint in Claude Apps

### Availability by client

| Client | Local MCP (stdio) | Remote MCP (HTTPS) |
|---|---|---|
| Claude Code CLI (terminal) | ✅ | ✅ |
| VSCode + Claude Code extension | ⚠️ Known issues | ✅ |
| Claude.ai web | ❌ | ✅ |
| Claude Desktop | ✅ | ✅ |
| Claude iPhone / Android | ❌ | ✅ (configured via claude.ai) |

Since your FastAPI is already served over HTTPS, a remote MCP is the right approach — it works across all clients without any local installation.

### Registering the connector on Claude.ai

1. Go to **Settings → Connectors → Add Custom Connector**
2. Name: `text2sql`
3. URL: `https://yourdomain.com/mcp`
4. Click **Add**

> **Note:** The current Claude.ai connector UI only supports OAuth — it has no Bearer Token field.
> Leave `MCP_API_KEY` empty in your `.env` so the middleware skips the bearer check.
> Security relies on HTTPS transport. To enforce a static bearer token, use Claude Code CLI (see below).

The connector automatically syncs to Claude Desktop, Claude web, and Claude mobile (iOS/Android). Mobile users cannot add connectors directly from the app — they must be configured via claude.ai first.

### Note on Claude Code CLI

If you also want to use the MCP from Claude Code CLI (local terminal), register it separately:

```bash
claude mcp add text2sql --url https://yourdomain.com/mcp --header "Authorization: Bearer your-secret-key"
```

---

## 6. API Key Authentication for the MCP Route

The MCP route is locked with a bearer token. All other routes on your FastAPI app are unaffected.

### VPS — middleware

```python
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
import os

MCP_API_KEY = os.getenv("MCP_API_KEY", "")   # empty → /mcp route is open

async def _verify_mcp_bearer(request: Request, call_next):
    if request.url.path.startswith("/mcp"):
        if MCP_API_KEY:                        # skip check when key is not configured
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {MCP_API_KEY}":
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)

app.add_middleware(BaseHTTPMiddleware, dispatch=_verify_mcp_bearer)
```

Store the key in your environment:

```bash
# .env or Docker environment config
MCP_API_KEY=your-secret-key
```

Generate a strong key:

```bash
openssl rand -hex 32
```

### Claude.ai — connector configuration

The current Claude.ai connector UI only supports OAuth, not static bearer tokens. Leave `MCP_API_KEY` empty in your `.env` for the Claude.ai web connector — the middleware skips the bearer check when the value is empty, and HTTPS is the sole protection layer. To enforce a static bearer token, use the Claude Code CLI with `--header "Authorization: Bearer <key>"` which fully supports static tokens.

---

## 7. End-to-End Query Flow

This section describes how a user question travels from a Claude client through the MCP route to your API and back.

### Simple search query

```
User
  │
  │  "What are the best Christopher Nolan films?"
  ▼
Claude (claude.ai / Desktop / iPhone)
  │
  │  Reads sql_search docstring → decides tool is relevant
  │  Calls sql_search("best Christopher Nolan films")
  ▼
Anthropic cloud infrastructure
  │
  │  Injects Authorization: Bearer <key>
  │  POST https://yourdomain.com/mcp
  ▼
Your VPS — Nginx
  │
  │  Forwards to FastAPI
  ▼
FastAPI MCP middleware
  │
  │  Validates bearer token
  │  Routes to sql_search tool handler
  ▼
Your internal text-to-SQL API (POST /search/text2sql)
  │
  │  LangChain + LLM generates SQL
  │  Executes against MariaDB
  │  Returns JSON result set
  ▼
Claude
  │
  │  Reads result set (ids, titles, ratings)
  │  Formats response in natural language with Markdown links
  ▼
User
     "Here are the top Nolan films: [Inception](https://myapp.com/movies/27205) (8.4)..."
```

### Drill-down query (two-step)

```
User
  │
  │  "Tell me more about Inception"
  ▼
Claude
  │
  │  Has movie_id 27205 from previous result
  │  Calls get_movie(27205)
  ▼
Your API — GET /movies/27205
  │
  │  Returns full entity: cast, crew, genres, keywords
  ▼
Claude
  │
  │  Formats full detail response with cast list, crew, ratings
  ▼
User
     "Inception (2010) directed by Christopher Nolan...
      Cast: Leonardo DiCaprio as Cobb, Joseph Gordon-Levitt as Arthur..."
```

### Complex query using the resource

```
User
  │
  │  "Who are directors who also acted in their own films?"
  ▼
Claude
  │
  │  Recognises this needs precise field knowledge
  │  Reads resource context://database-scope
  │  Sees: crew table has job=Director, cast table has character
  │  Formulates precise question for sql_search
  │
  │  Calls sql_search("persons who appear in movie_crew as Director
  │                    and in movie_cast as actor,
  │                    ranked by number of films")
  ▼
Your API
  │
  │  Internal LLM generates correct JOIN query
  │  Returns ranked result set
  ▼
Claude → formats and presents results to user
```

---

## Summary

| Component | Role |
|---|---|
| FastAPI `POST /search/text2sql` | Accepts natural language question, converts to SQL, executes, and returns full result set with pipeline trace |
| FastAPI `/movies/{id}` etc. | Returns full entity detail with embedded relations |
| FastMCP mounted at `""` (root); Nginx routes `/mcp` → FastAPI | Exposes tools and resources over HTTPS |
| Bearer token middleware | Guards `/mcp` paths; skipped when `MCP_API_KEY` is empty |
| Tool docstrings (Layer 1) | Always loaded — scope, exclusions, URL patterns, resource pointer |
| MCP Resource (Layer 2) | Loaded on demand — semantic entity and property reference |
| Claude.ai Connectors | Registers the remote MCP, syncs to all Claude clients |
| Claude | Orchestrates tool calls, formats results, builds hyperlinks |
