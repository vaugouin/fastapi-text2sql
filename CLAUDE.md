# CLAUDE.md - AI Assistant Guide for FastAPI Text2SQL

## Project Overview

This is a FastAPI-based REST API that converts natural language questions into SQL queries using LLM provider SDKs (OpenAI, Anthropic, Google). The system specializes in querying a large-scale entertainment database (620k+ movies, 88k+ TV series, 890k+ persons). It also exposes an MCP (Model Context Protocol) server so Claude clients can use the API as a remote tool.

**Primary Technology Stack:**
- **Framework**: FastAPI (Python 3.8+)
- **LLM**: OpenAI GPT-4o (default), Anthropic Claude, Google Gemini — via native provider SDKs
- **Vector DB**: ChromaDB (for embeddings and similarity search)
- **SQL DB**: MariaDB/MySQL
- **MCP**: FastMCP 2.x (remote tool server for Claude clients)
- **Deployment**: Docker with Blue/Green deployment strategy

**Current Version**: 1.1.15 (see `strapiversion` in main.py)

## Architecture & Design Patterns

### Core Architecture Components

1. **Multi-Tier Caching System** (Performance Optimization)
   - **Tier 1**: Exact question cache (SQL database `T_WC_T2S_CACHE`)
   - **Tier 2**: Anonymized question cache (SQL database `T_WC_T2S_CACHE`)
   - **Tier 3**: Vector embeddings cache (ChromaDB `anonymizedqueries` collection)

2. **Entity Extraction Pipeline**
   - Entities are extracted from natural language using GPT-4o
   - Questions are anonymized with placeholders (e.g., `{{PERSON_NAME}}`, `{{MOVIE_TITLE}}`, `{{Release_year1}}`)
   - Enables query pattern reuse across different entity values
   - Entity types: Person names, Movie titles, Series titles, Company names, Network names, Character names, Location names, Topics
   - If the user provides a disambiguation pattern like `<movie_title> (YYYY)`, entity extraction can also return a release year placeholder (e.g., `{{Release_year1}}`) in addition to the movie title.

3. **Vector Search Integration**
   - ChromaDB collections for entity matching:
     - `persons`: Actor/director/crew embeddings
     - `movies`: Movie title embeddings (multi-language)
     - `series`: TV series title embeddings
     - `companies`: Production company embeddings
     - `networks`: TV network embeddings
     - `topics`: Genre/theme embeddings
     - `anonymizedqueries`: Cached anonymized question patterns
   - Similarity threshold: 0.15 (configurable via `similarity_threshold` in main.py:236)
   - Embedding model: OpenAI `text-embedding-3-large`

4. **Blue/Green Deployment**
   - Version-based port selection: even patch versions → port 8000 (Blue), odd → port 8001 (Green)
   - Controlled by `strapiversion` variable in main.py:46
   - Restart scripts: `restart-blue.sh` and `restart-green.sh`

5. **Automatic Cache Cleanup** (Refactored in v1.1.13)
   - Cleanup functions moved to separate `cleanup.py` module for better code organization
   - Runs on application startup (main.py:141, 187)
   - `cleanup.cleanup_anonymized_queries_collection()`: Cleans ChromaDB embeddings cache
   - `cleanup.cleanup_sql_cache()`: Cleans SQL cache table matching current API version
   - Ensures old cached queries from previous versions are removed automatically

### Request Processing Pipeline

The API follows a sophisticated 10-step pipeline:

1. **Exact Question Cache Lookup** (SQL)
2. **Entity Extraction & Anonymization** (GPT-4o)
3. **Anonymized Question Cache Lookup** (SQL)
4. **Embeddings Cache Search** (ChromaDB)
5. **Entity Validation & Resolution** (ChromaDB + SQL)
6. **Text-to-SQL Generation** (GPT-4o, if no cache hit)
7. **Query De-anonymization** (Replace placeholders with actual values)
8. **SQL Query Execution** (MariaDB)
9. **Cache Population** (All 3 tiers)
10. **Result Return** (with comprehensive metrics)

## Key Files and Their Roles

### Core Application Files

**main.py**
- FastAPI application setup and endpoint definitions
- ChromaDB initialization and collection management
- Database connection pooling (`get_db_connection()`)
- Version management utilities: `format_api_version()` and `compare_versions()`
- Automatic cache cleanup functions
- Main `/search/text2sql` endpoint implementation
- 14 entity detail endpoints (`/movies/{id}`, `/series/{id}`, `/persons/{id}`, etc.)
- Caching logic for all 3 tiers
- Entity replacement in SQL queries
- Pagination logic
- Blue/Green deployment port selection
- MCP server: tools, resource, bearer-token middleware, and mount

**text2sql.py**
- Core text-to-SQL conversion logic (`f_text2sql()`)
- `_call_chat_llm()` — unified LLM dispatch: OpenAI (native SDK), Anthropic (native `anthropic` SDK), Google Gemini (`google-generativeai`)
- Prompt template loading via `data_watcher.py` hot-reload
- Memory monitoring (using psutil)
- Current prompt templates (hot-reloaded `.md` files in `data/`):
  - `text_to_sql.md`
  - `complex_question.md`

**cleanup.py** (103 lines) - New in v1.1.13
- `format_api_version()`: Converts version string to XXX.YYY.ZZZ format
- `cleanup_anonymized_queries_collection()`: Cleans ChromaDB embeddings cache
- `cleanup_sql_cache()`: Cleans SQL cache table matching current API version
- Processes documents in batches of 1000 for efficient cleanup
- Includes fix to delete specific problematic query IDs

**auth.py**
- API key authentication middleware
- Supports multiple API keys via `API_KEYS` env var (comma-separated) with legacy `API_KEY` fallback
- FastAPI Security dependency injection
- Constant-time comparison for security (`secrets.compare_digest()`)
- X-API-Key header validation

### Configuration Files

**logs.py**
- `log_usage(endpoint, content, strapiversion)` — writes JSON log files to `logs/` folder
- Filename format: `YYYYMMDD-HHMMSS_{endpoint}_{version}_{md5hash}.json`
- Used by all endpoints (hello, text2sql, entity detail endpoints, start)

**data_watcher.py**
- File-system watcher for hot-reloading `data/` files (prompt templates, entity resolution config)
- `register(filename, callback)` — registers a file for watching
- Changes are picked up automatically without restarting the API

**language_family.py**
- `guess_language_family()` — detects Latin vs non-Latin script for person name resolution routing

**.env.example**
- Template for environment variables
- Required variables: `API_KEYS` (or legacy `API_KEY`), `OPENAI_API_KEY`, `DB_*`, `CHROMADB_*`, `API_PORT_*`
- Optional LLM keys: `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`
- MCP variables: `MCP_API_KEY`, `MCP_INTERNAL_API_KEY`, `MCP_INTERNAL_BASE_URL`

**requirements.txt**
- Core dependencies: FastAPI, uvicorn, OpenAI, ChromaDB, pymysql, pandas, numpy, rapidfuzz
- LLM provider SDKs: anthropic, google-generativeai
- MCP integration: fastmcp, httpx

**Dockerfile**
- Python 3.12-slim-bookworm base image
- Custom SQLite 3.40.1 installation (required for ChromaDB compatibility)
- Multi-stage build for optimization

### Data Files

**data/** directory
- Contains prompt templates for GPT-4o
- Version-controlled templates (naming: `*-chatgpt-4o-{version}-{date}.txt`)
- Entity extraction and text-to-SQL prompts
- Templates include comprehensive database schema for movie/series data

### Deployment Scripts

**restart-blue.sh / restart-green.sh**
- Docker container lifecycle management
- Automated deployment for blue/green deployments
- Volume mounting for live code updates

## Development Workflow

### Version Management

**CRITICAL**: When updating prompt templates:
1. Update `strapiversion` in main.py:47
2. Create new prompt template files in `data/` with new version number and date
3. Update template filenames in text2sql.py:26 and text2sql.py:30
4. Version format: `X.Y.Z` (Major.Minor.Patch)
5. Patch version determines deployment port (even = Blue, odd = Green)
6. On startup, cleanup functions automatically remove old cached queries from previous versions

**Version Utility Functions** (main.py:26-44):
- `format_api_version(version: str) -> str`: Converts version "X.Y.Z" to "XXX.YYY.ZZZ" format for comparison
- `compare_versions(version1: str, version2: str) -> int`: Compares two version strings (-1, 0, or 1)
- Note: `format_api_version()` is also available in `cleanup.py` for use during startup cleanup

### Database Schema

The system expects these SQL tables:
- `T_WC_T2S_CACHE`: Cache storage (exact and anonymized questions)
  - Fields: `QUESTION`, `QUESTION_HASHED`, `SQL_QUERY`, `SQL_PROCESSED`, `JUSTIFICATION`, `API_VERSION`, timing metrics, etc.
  - Important: `IS_ANONYMIZED` flag distinguishes anonymized vs exact questions
  - `JUSTIFICATION` field stores the LLM's reasoning for the SQL query (added in v1.1.13)
- `T_WC_T2S_MOVIE`: Movie data with `MOVIE_TITLE`, `MOVIE_TITLE_FR`, `ORIGINAL_TITLE`
- `T_WC_T2S_SERIE`: Series data with similar multi-language title fields
- `T_WC_T2S_PERSON`: Person data (actors, directors, crew)
- `T_WC_T2S_COMPANY`: Production companies
- `T_WC_T2S_NETWORK`: TV networks
- `T_WC_T2S_TOPIC`: Genres and topics

### API Endpoints

**GET /**
- Health check endpoint
- Returns "hello world" message
- Requires API key authentication
- Logs via `logs.log_usage("hello", ...)`

**POST /search/text2sql**
- Main text-to-SQL conversion endpoint
- Request body: `Text2SQLRequest` (Pydantic model)
- Response: `Text2SQLResponse` (Pydantic model)
- Supports pagination via `page` parameter
- Supports page size control via `rows_per_page` parameter (default: 50)
- Can use `question_hashed` for subsequent pages (avoids re-processing)
- Cache control via `retrieve_from_cache` and `store_to_cache` flags
- `complex_question_processing` (bool, default `false`): when `true`, enables stronger-model retry
- Logs via `logs.log_usage("text2sql_post", ...)`

**Entity Detail Endpoints** (14 endpoints)
- `GET /movies/{id}`, `GET /series/{id}`, `GET /persons/{id}`
- `GET /companies/{id}`, `GET /networks/{id}`, `GET /collections/{id}`
- `GET /topics/{id}`, `GET /lists/{id}`, `GET /movements/{id}`
- `GET /groups/{id}`, `GET /deaths/{id}`, `GET /awards/{id}`
- `GET /nominations/{id}`, `GET /locations/{wikidata_id}`
- Each returns all fields for the entity plus embedded relations (cast, crew, filmography, etc.)
- Each logs the request via `logs.log_usage()` before returning
- Require API key authentication

**MCP Endpoint** (`/mcp`)
- Model Context Protocol server mounted at root (`""`) via FastMCP
- Nginx routes `/mcp` → FastAPI; FastMCP handles the MCP protocol
- Protected by bearer-token middleware (`MCP_API_KEY`)
- Exposes 15 MCP tools (1 search + 14 entity tools) and 1 resource (`context://database-scope`)
- See `MCP.md` for full integration guide

### Response Fields

Every response includes:
- **Core**: `question`, `question_hashed`, `sql_query`, `sql_query_anonymized`, `justification`, `error`, `result`
- **Entity Extraction** (New in v1.1.13):
  - `entity_extraction`: Full entity extraction dictionary from LLM
  - `question_anonymized`: The anonymized version of the question with placeholders
- **Performance Metrics**:
  - `entity_extraction_processing_time`
  - `text2sql_processing_time`
  - `embeddings_processing_time`
  - `embeddings_cache_search_time`
  - `query_execution_time`
  - `total_processing_time`
- **Pagination**: `page`, `limit`, `offset`, `rows_per_page`, `llm_defined_limit`, `llm_defined_offset`
- **Cache Indicators**: `cached_exact_question`, `cached_anonymized_question`, `cached_anonymized_question_embedding`
- **Messages**: Detailed processing steps in `messages` array (main.py:241)
- **Flags**: `ambiguous_question_for_text2sql` (indicates if SQL generation failed)

## Code Conventions

### Python Style

- **Naming Convention**: Hungarian notation for variables (legacy style)
  - `str` prefix for strings (e.g., `strtablename`)
  - `lng` prefix for integers (e.g., `lngpage`)
  - `dbl` prefix for floats (e.g., `dblavailableram`)
  - `arr` prefix for arrays/lists (e.g., `arrentities`)
  - `int` prefix for specific entity types (e.g., `intentity`)
- **Function Naming**: Prefix with `f_` (e.g., `f_text2sql`, `f_entity_extraction`, `f_hello_world`)
- **Docstrings**: Google-style docstrings for all functions (see main.py:134-145, text2sql.py:48-55)
- **Error Handling**: Try/except blocks with detailed logging to console
- **JSON Handling**: Custom `decimal_serializer()` for Decimal and datetime objects (main.py:250-259)

### SQL Query Handling

**CRITICAL SQL ESCAPING RULES**:
- Use `''` (double single quote) for SQL escaping, NOT `\'`
- Example: `O'Brien` → `O''Brien` in SQL
- Apply escaping when replacing entity placeholders (main.py:655)
- Pattern matching regex: `r"\s*=\s*'((?:[^']|'')*)'(?!')"`  (main.py:702)
- Always unescape when reading from database: `match.replace("''", "'")` (main.py:708)

**SQL Query Modification**:
- Remove LLM-generated LIMIT/OFFSET clauses (main.py:839-849)
- Add pagination: `LIMIT {limit}` or `LIMIT {limit} OFFSET {offset}`
- Strip trailing semicolons (text2sql.py:205-206)
- Replace `\n` with spaces (text2sql.py:209)

### Ambiguous Questions

When the LLM cannot generate a valid SQL query (updated in v1.1.13):
- The `error` response field contains the explanation from the LLM
- Set `ambiguous_question_for_text2sql = True`
- Skip query execution
- Return empty results with the error explanation
- Note: The previous `##AMBIGUOUS##` marker approach has been replaced with the `error` parameter

### Entity Extraction

**Entity Types** (main.py:750-752):
1. `PERSON_NAME` → `persons` collection, `T_WC_T2S_PERSON` table
2. `MOVIE_TITLE` → `movies` collection, `T_WC_T2S_MOVIE` table
3. `SERIE_TITLE` → `series` collection, `T_WC_T2S_SERIE` table
4. `COMPANY_NAME` → `companies` collection, `T_WC_T2S_COMPANY` table
5. `NETWORK_NAME` → `networks` collection, `T_WC_T2S_NETWORK` table
6. `TOPIC_NAME` → `topics` collection, `T_WC_T2S_TOPIC` table
7. `CHARACTER_NAME` → `characters` collection (new in v1.1.14) - movie/series characters (e.g., "James Bond", "Sherlock Holmes")
8. `LOCATION_NAME` → `locations` collection (new in v1.1.14) - narrative or filming locations (e.g., "New York City", "Gotham City")

**Release year disambiguation**:
- When a user writes a pattern like `<movie_title> (YYYY)`, entity extraction can return a `Release_year` variable (e.g., `{{Release_year1}}`).
- Downstream, this should be used together with the extracted movie title to narrow the SQL query (title equality + release year range filtering).

**Multi-Language Title Handling** (main.py:773-786):
- ChromaDB document IDs format: `{entity}_{id}_{lang}` (e.g., `movie_12345_en`)
- Language codes: `en` (English), `fr` (French), or original language
- Field mapping:
  - `en` → `MOVIE_TITLE` / `SERIE_TITLE`
  - `fr` → `MOVIE_TITLE_FR` / `SERIE_TITLE_FR`
  - Other → `ORIGINAL_TITLE`

**Entity Extraction Error Handling** (main.py:484-495):
- If extraction returns `{'error': ...}`, fall back to original question
- No entity replacement occurs
- Proceed with non-anonymized question

### ChromaDB Usage

**Collection Initialization** (main.py:74-143):
- Use `get_or_create_collection()` to ensure collections exist
- Provide custom `OpenAIEmbeddingFunction` instance
- Embedding function implements `__call__()` and `embed_query()` methods
- Collections: `persons`, `movies`, `series`, `companies`, `networks`, `topics`, `locations`, `characters`, `groups`, `anonymizedqueries`

**Query Pattern**:
```python
results = collection.query(
    query_texts=[search_text],
    n_results=1  # or more for filtering
)
# Access: results['documents'][0], results['ids'][0], results['distances'][0]
```

**Metadata Storage**:
- Store SQL query in `sql_query_anonymized` metadata field
- Store `justification` for the SQL query reasoning (added in v1.1.13)
- Store entity variables as comma-separated string
- Include timing metrics and API version

**Similarity Filtering** (main.py:566-623):
- Fetch multiple results (`n_results=10`)
- Filter by entity variable matching (all required variables must be present)
- Check distance threshold: `distance < similarity_threshold`
- Use first valid result

### Logging

**Log Structure** (implemented in `logs.py`):
- Log folder: `logs/` (auto-created)
- Filename format: `YYYYMMDD-HHMMSS_{endpoint}_{version}_{md5hash}.json`
- Content: JSON with request/response data
- Encoding: UTF-8 with `ensure_ascii=False` for international characters
- Only create file if it doesn't exist (prevents overwrites)

**Log Usage**:
- Call `logs.log_usage(endpoint, content, strapiversion)` after each request
- Logged endpoints: `"hello"`, `"text2sql_post"`, `"start"`, `"movies"`, `"series"`, `"persons"`, `"companies"`, `"networks"`, `"collections"`, `"topics"`, `"lists"`, `"movements"`, `"groups"`, `"deaths"`, `"awards"`, `"nominations"`, `"locations"`

### Messages Array (New Feature)

**Purpose**: Track processing steps for transparency (main.py:322-1023)
- Each message: `TextMessage(position=int, text=str)`
- Increment `position_counter` after each message
- Include in final response: `messages: List[TextMessage]`
- Examples:
  - "Stripped whitespace and carriage return characters from question."
  - "Exact question cache hit used for SQL query."
  - "Entity extraction successful; question anonymized."
  - "Executing SQL query: {sql_query}"

## Important Implementation Details

### Cache Key Matching

**Exact Cache** (main.py:362-430):
1. Try `question_hashed` lookup first (if provided)
2. Fall back to exact `question` text match
3. Filter by `API_VERSION = {strapiversionformatted}` (formatted as `XXX.YYY.ZZZ`)
4. Exclude deleted: `DELETED IS NULL OR DELETED = 0`
5. Order by `TIM_UPDATED DESC` (most recent first)
6. Use `SQL_PROCESSED` if available, otherwise `SQL_QUERY`

**Anonymized Cache** (main.py:497-540):
- Same query pattern as exact cache
- Uses anonymized question text with placeholders

**Embeddings Cache** (main.py:542-630):
- Query `anonymizedqueries` collection
- Fetch 10 results initially
- Extract entity variables from document using regex: `r'{{(\w+\d*)}}'`
- Filter results where all required entity variables are present
- Verify distance < threshold
- Extract SQL from `metadata['sql_query_anonymized']`

### Entity Replacement Logic

**Pattern Extraction** (main.py:700-709):
- Regex pattern: `{strfieldname}\s*=\s*'((?:[^']|'')*)'(?!')`
- Handles SQL-escaped single quotes (`''`)
- Finds all matches in SQL query
- Unescapes for vector search: `match.replace("''", "'")`

**Vector Search & Replacement** (main.py:710-821):
1. Check SQL database first (currently disabled in favor of always using embeddings)
2. Query ChromaDB with unescaped entity value
3. Extract document ID: `{entity}_{id}_{lang}`
4. Determine correct field name based on language
5. Fetch actual value from SQL database
6. Escape value: `value.replace("'", "''")`
7. Replace in SQL: `{original_field} = '{escaped_value}'` → `{new_field} = '{new_escaped_value}'`

### Pagination

**Page Calculation** (main.py:832-864):
- `limit = lngrowsperpage` (default: 50)
- `offset = (page - 1) * lngrowsperpage`
- Strip existing LLM LIMIT/OFFSET using regex: `r"\blimit\b\s+\d+(?:\s*,\s*\d+)?"`
- Append new pagination: `LIMIT {limit} OFFSET {offset}`
- Store LLM values in `llm_defined_limit` and `llm_defined_offset` for reference

**Hashed Pagination**:
- First request: provide `question`, get back `question_hashed`
- Subsequent pages: provide `question_hashed` + `page` number
- Avoids re-processing entity extraction and text-to-SQL

### Error Handling

**Entity Extraction Errors** (text2sql.py:122-146):
- Handle truncated/malformed JSON from OpenAI
- Strip markdown code fences: ````json` and ` ``` `
- Attempt to wrap bare JSON in braces
- Return `{"error": ...}` on failure with raw content

**Database Errors** (main.py:866-885):
- Catch exceptions during SQL execution
- Log error message
- Return empty results (not error to client)
- Add error to messages array

**Missing API Keys** (text2sql.py:58-60, main.py:37-38):
- Validate `OPENAI_API_KEY` at startup
- Raise `ValueError` if missing
- Return error message in conversion functions

## Testing & Deployment

### Local Development

1. **Setup Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with actual credentials
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Server**:
   ```bash
   python main.py
   # Starts on port 8000 (even version) or 8001 (odd version)
   ```

4. **Access Docs**:
   - Interactive: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

### Docker Deployment

**Build & Run**:
```bash
docker build -t fastapi-text2sql .
docker run -p 8000:8000 --env-file .env fastapi-text2sql
```

**Blue/Green Deployment**:
- Use `restart-blue.sh` for even versions (port 8000)
- Use `restart-green.sh` for odd versions (port 8001)
- Scripts handle container lifecycle automatically

### Version Updates

**When Updating Prompts**:
1. Increment `strapiversion` in main.py:47
2. Create new prompt files in `data/` with version suffix and date (format: `YYYYMMDD`)
3. Update filenames in text2sql.py:26 and text2sql.py:30
4. Test locally first
5. Deploy using appropriate restart script
6. On startup, cleanup functions will automatically remove old cached queries
7. Verify API version in response logs

**Version Format Conversion** (main.py:26-49, cleanup.py:5-8):
- Input: `"1.1.15"`
- Output: `"001.001.015"` (for SQL storage)
- Uses `format_api_version()` helper function for consistent formatting
- Function available in both main.py and cleanup.py

## Automatic Cache Cleanup

### Cleanup Module (Refactored in v1.1.13)

The cleanup functions have been refactored into a separate `cleanup.py` module for better code organization and maintainability.

**cleanup.cleanup_anonymized_queries_collection()** (cleanup.py:10-92):
- Runs automatically on application startup (main.py:141)
- Deletes old embeddings from ChromaDB `anonymizedqueries` collection
- Includes fix to delete specific problematic query IDs
- Processes documents in batches of 1000
- Removes all documents (currently configured to clean all, not just old versions)
- Provides detailed console output for monitoring

**cleanup.cleanup_sql_cache()** (cleanup.py:94-102):
- Runs automatically on application startup (main.py:187)
- Deletes SQL cache entries matching current API version
- Executes: `DELETE FROM T_WC_T2S_CACHE WHERE API_VERSION = {current_version}`
- Ensures fresh cache for new version deployments

**Important Notes**:
- Both functions run synchronously during startup
- Application startup may take longer due to cleanup operations
- Large cache cleanup may impact startup time
- Console output shows progress and deletion counts
- Import: `import cleanup` in main.py

## Common Patterns and Gotchas

### Gotcha #1: SQL Quote Escaping

**WRONG**:
```python
value = "O'Brien"
escaped = value.replace("'", "\\'")  # ❌ Wrong for SQL
```

**CORRECT**:
```python
value = "O'Brien"
escaped = value.replace("'", "''")  # ✅ Correct for SQL
sql = f"WHERE NAME = '{escaped}'"  # WHERE NAME = 'O''Brien'
```

### Gotcha #2: Entity Variable Matching

When searching embeddings cache, ensure ALL entity variables match:
```python
entity_variables = ['PERSON_NAME1', 'PERSON_NAME2']
doc_entity_vars = re.findall(r'{{(\w+\d*)}}', document)
# Must have ALL variables, not just some
if all(var in doc_entity_vars for var in entity_variables):
    # Valid match
```

### Gotcha #3: Cache API Version Filtering

Always filter by formatted API version:
```python
# ❌ WRONG: using strapiversion directly
cursor.execute("... WHERE API_VERSION = %s", (strapiversion,))

# ✅ CORRECT: using formatted version
cursor.execute("... WHERE API_VERSION = %s", (strapiversionformatted,))
```

### Gotcha #4: ChromaDB Document IDs

When parsing ChromaDB document IDs:
```python
doc_id = "movie_12345_fr"
parts = doc_id.split('_')
entity = parts[0]  # "movie"
id = parts[1]      # "12345"
lang = parts[2]    # "fr"

# Then map to correct SQL field
if lang == "fr":
    field = "MOVIE_TITLE_FR"  # Not MOVIE_TITLE!
```

### Gotcha #5: Messages Array

Always increment position counter:
```python
messages.append(TextMessage(position=position_counter, text="Step completed"))
position_counter += 1  # ❌ Don't forget this!
```

### Gotcha #6: Database Connection Lifecycle

Open connection once, use throughout request, close at end:
```python
connection = get_db_connection()  # Once at start
try:
    # Use connection.cursor() multiple times
    with connection.cursor() as cursor:
        # Query 1
    with connection.cursor() as cursor2:
        # Query 2
finally:
    connection.close()  # Once at end
```

### Gotcha #7: Embedding Function Interface

Custom embedding functions must implement both methods:
```python
class OpenAIEmbeddingFunction:
    def __call__(self, input):
        # For batch operations
        return [np.array(embedding) for embedding in embeddings]

    def embed_query(self, input):
        # For single queries (required by ChromaDB)
        return [np.array(embedding) for embedding in embeddings]
```

## Environment Variables

### Required Variables

```bash
# Authentication (comma-separated list; legacy API_KEY also accepted)
API_KEYS=key_for_app,key_for_mcp,key_for_scripts

# OpenAI Configuration
OPENAI_API_KEY=sk-...

# Database Configuration
DB_HOST=localhost
DB_PORT=3306
DB_USER=dbuser
DB_PASSWORD=dbpass
DB_NAME=moviesdb

# ChromaDB Configuration
CHROMADB_HOST=localhost
CHROMADB_PORT=8000

# Deployment Ports
API_PORT_BLUE=8000
API_PORT_GREEN=8001
```

### Optional Variables

```bash
# LLM provider keys (only needed if using non-OpenAI models)
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...

# MCP (Model Context Protocol)
MCP_API_KEY=your_mcp_bearer_token    # empty = /mcp route is open
MCP_INTERNAL_API_KEY=key_for_mcp     # defaults to first entry of API_KEYS
MCP_INTERNAL_BASE_URL=http://127.0.0.1:8010  # auto-detected from version parity
```

## Security Considerations

1. **API Key Authentication**: All endpoints require `X-API-Key` header; multiple keys supported via `API_KEYS`
2. **MCP Bearer Token**: `/mcp` route protected by `MCP_API_KEY` bearer token middleware (skipped when empty)
3. **Constant-Time Comparison**: Uses `secrets.compare_digest()` to prevent timing attacks
4. **Environment Variables**: All secrets stored in `.env` (not committed to git)
5. **SQL Injection**: Uses parameterized queries with `cursor.execute(query, params)`
6. **Input Sanitization**: Entity values are SQL-escaped before insertion

## Performance Optimization Tips

1. **Enable Caching**: Keep `retrieve_from_cache=true` and `store_to_cache=true` for best performance
2. **Pagination**: Use `question_hashed` for subsequent pages to avoid re-processing
3. **Similarity Threshold**: Adjust `similarity_threshold` (main.py:236) for cache hit rate vs. accuracy trade-off
4. **ChromaDB Fetch Size**: Increase `n_results` in embeddings search if entity variable matching fails often
5. **Database Indexing**: Ensure indexes on `QUESTION`, `QUESTION_HASHED`, `API_VERSION` in cache table

## Troubleshooting

### Issue: Cache Not Working

**Check**:
1. API version matches: query uses `strapiversionformatted`
2. Question text is identical (whitespace matters)
3. DELETED flag is NULL or 0
4. Check logs for cache lookup queries

### Issue: Entity Not Found

**Check**:
1. Entity exists in ChromaDB collection
2. Spelling/language matches vector database
3. Distance threshold not too strict
4. Document ID format: `{entity}_{id}_{lang}`

### Issue: SQL Execution Fails

**Check**:
1. Entity replacement completed correctly
2. SQL escaping applied (use `''` not `\'`)
3. LIMIT/OFFSET clause added correctly
4. Check logs for actual SQL executed

### Issue: Ambiguous Question

**Resolution**:
- LLM cannot generate SQL (too vague or out of scope)
- Check the `error` field in the response for the LLM's explanation
- The `ambiguous_question_for_text2sql` flag will be set to `True`
- Check prompt template for guidance on what queries are supported
- Refine question to be more specific

## Contributing Guidelines

1. **Version Increment**: Always increment `strapiversion` for prompt changes
2. **Commit Messages**: Use descriptive messages (see git log for examples)
3. **Documentation**: Update docstrings for new functions
4. **Testing**: Test locally before deployment
5. **Logging**: Add messages to processing pipeline for transparency
6. **Error Handling**: Wrap external API calls in try/except
7. **Code Style**: Follow existing Hungarian notation conventions

## Additional Resources

- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **OpenAI API**: https://platform.openai.com/docs/
- **Anthropic API**: https://docs.anthropic.com/
- **Google Gemini API**: https://ai.google.dev/docs
- **ChromaDB Documentation**: https://docs.trychroma.com/
- **FastMCP Documentation**: https://github.com/jlowin/fastmcp
- **MCP Integration Guide**: See `MCP.md` in this repository

---

**Last Updated**: 2026-04-13
**Current Version**: 1.1.15
**Maintainer**: See repository owner
