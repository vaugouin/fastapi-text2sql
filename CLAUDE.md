# CLAUDE.md - AI Assistant Guide for FastAPI Text2SQL

## Project Overview

This is a FastAPI-based REST API that converts natural language questions into SQL queries using OpenAI's GPT-4o model and LangChain. The system specializes in querying a large-scale entertainment database (620k+ movies, 88k+ TV series, 890k+ persons).

**Primary Technology Stack:**
- **Framework**: FastAPI (Python 3.8+)
- **LLM**: OpenAI GPT-4o
- **Vector DB**: ChromaDB (for embeddings and similarity search)
- **SQL DB**: MariaDB/MySQL
- **Orchestration**: LangChain
- **Deployment**: Docker with Blue/Green deployment strategy

**Current Version**: 1.1.9 (see `strapiversion` in main.py:25)

## Architecture & Design Patterns

### Core Architecture Components

1. **Multi-Tier Caching System** (Performance Optimization)
   - **Tier 1**: Exact question cache (SQL database `T_WC_T2S_CACHE`)
   - **Tier 2**: Anonymized question cache (SQL database)
   - **Tier 3**: Vector embeddings cache (ChromaDB `anonymizedqueries` collection)

2. **Entity Extraction Pipeline**
   - Entities are extracted from natural language using GPT-4o
   - Questions are anonymized with placeholders (e.g., `{{PERSON_NAME}}`, `{{MOVIE_TITLE}}`)
   - Enables query pattern reuse across different entity values
   - Entity types: Person names, Movie titles, Series titles, Company names, Network names, Topics

3. **Vector Search Integration**
   - ChromaDB collections for entity matching:
     - `persons`: Actor/director/crew embeddings
     - `movies`: Movie title embeddings (multi-language)
     - `series`: TV series title embeddings
     - `companies`: Production company embeddings
     - `networks`: TV network embeddings
     - `topics`: Genre/theme embeddings
     - `anonymizedqueries`: Cached anonymized question patterns
   - Similarity threshold: 0.15 (configurable via `similarity_threshold` in main.py:130)
   - Embedding model: OpenAI `text-embedding-3-large`

4. **Blue/Green Deployment**
   - Version-based port selection: even patch versions → port 8000 (Blue), odd → port 8001 (Green)
   - Controlled by `strapiversion` variable in main.py:25
   - Restart scripts: `restart-blue.sh` and `restart-green.sh`

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

**main.py** (1073 lines)
- FastAPI application setup and endpoint definitions
- ChromaDB initialization and collection management
- Database connection pooling (`get_db_connection()`)
- Main `/search/text2sql` endpoint implementation (main.py:290-1059)
- Caching logic for all 3 tiers
- Entity replacement in SQL queries
- Pagination logic
- Logging infrastructure (`log_usage()`, main.py:236-266)
- Blue/Green deployment port selection (main.py:1061-1072)

**text2sql.py** (221 lines)
- Core text-to-SQL conversion logic (`f_text2sql()`, text2sql.py:152-219)
- Entity extraction logic (`f_entity_extraction()`, text2sql.py:47-150)
- Prompt template loading from `data/` folder
- OpenAI API client management
- Memory monitoring (using psutil)
- Current prompt templates:
  - `text-to-sql-prompt-chatgpt-4o-1-1-9-20251212.txt`
  - `entity-extraction-prompt-chatgpt-4o-1-1-9-20251212.txt`

**auth.py** (40 lines)
- API key authentication middleware
- FastAPI Security dependency injection
- Constant-time comparison for security (`secrets.compare_digest()`)
- X-API-Key header validation

### Configuration Files

**.env.example**
- Template for environment variables
- Required variables: `API_KEY`, `OPENAI_API_KEY`, `DB_*`, `CHROMADB_*`, `API_PORT_*`

**requirements.txt**
- Core dependencies: FastAPI, uvicorn, OpenAI, ChromaDB, pymysql, pandas, numpy
- LangChain components: langchain-core, langchain-openai

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
1. Update `strapiversion` in main.py:25
2. Create new prompt template files in `data/` with new version number
3. Update template filenames in text2sql.py:25-28
4. Version format: `X.Y.Z` (Major.Minor.Patch)
5. Patch version determines deployment port (even = Blue, odd = Green)

### Database Schema

The system expects these SQL tables:
- `T_WC_T2S_CACHE`: Cache storage (exact and anonymized questions)
  - Fields: `QUESTION`, `QUESTION_HASHED`, `SQL_QUERY`, `SQL_PROCESSED`, `API_VERSION`, timing metrics, etc.
  - Important: `IS_ANONYMIZED` flag distinguishes anonymized vs exact questions
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
- Logs to `logs/` folder

**POST /search/text2sql**
- Main text-to-SQL conversion endpoint
- Request body: `Text2SQLRequest` (Pydantic model, main.py:168-180)
- Response: `Text2SQLResponse` (Pydantic model, main.py:186-209)
- Supports pagination via `page` parameter
- Can use `question_hashed` for subsequent pages (avoids re-processing)
- Cache control via `retrieve_from_cache` and `store_to_cache` flags

### Response Fields

Every response includes:
- **Core**: `question`, `question_hashed`, `sql_query`, `result`
- **Performance Metrics**:
  - `entity_extraction_processing_time`
  - `text2sql_processing_time`
  - `embeddings_processing_time`
  - `embeddings_cache_search_time`
  - `query_execution_time`
  - `total_processing_time`
- **Pagination**: `page`, `limit`, `offset`, `rows_per_page`, `llm_defined_limit`, `llm_defined_offset`
- **Cache Indicators**: `cached_exact_question`, `cached_anonymized_question`, `cached_anonymized_question_embedding`
- **Messages**: Detailed processing steps in `messages` array (main.py:208)
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

When the LLM cannot generate a valid SQL query:
- SQL query contains `##AMBIGUOUS##` marker
- Set `ambiguous_question_for_text2sql = 1` (main.py:644)
- Skip query execution (main.py:828-892)
- Return empty results with explanation

### Entity Extraction

**Entity Types** (main.py:664):
1. `PERSON_NAME` → `persons` collection, `T_WC_T2S_PERSON` table
2. `MOVIE_TITLE` → `movies` collection, `T_WC_T2S_MOVIE` table
3. `SERIE_TITLE` → `series` collection, `T_WC_T2S_SERIE` table
4. `COMPANY_NAME` → `companies` collection, `T_WC_T2S_COMPANY` table
5. `NETWORK_NAME` → `networks` collection, `T_WC_T2S_NETWORK` table
6. `TOPIC_NAME` → `topics` collection, `T_WC_T2S_TOPIC` table

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

**Collection Initialization** (main.py:74-118):
- Use `get_or_create_collection()` to ensure collections exist
- Provide custom `OpenAIEmbeddingFunction` instance
- Embedding function implements `__call__()` and `embed_query()` methods

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
- Store entity variables as comma-separated string
- Include timing metrics and API version

**Similarity Filtering** (main.py:566-623):
- Fetch multiple results (`n_results=10`)
- Filter by entity variable matching (all required variables must be present)
- Check distance threshold: `distance < similarity_threshold`
- Use first valid result

### Logging

**Log Structure**:
- Log folder: `logs/` (auto-created)
- Filename format: `YYYYMMDD-HHMMSS_{endpoint}_{version}_{md5hash}.json`
- Content: JSON with `request` and `response` objects
- Encoding: UTF-8 with `ensure_ascii=False` for international characters
- Only create file if it doesn't exist (prevents overwrites)

**Log Usage** (main.py:214-266):
- Call `log_usage(endpoint, content)` after each request
- Endpoints: `"hello"`, `"text2sql_post"`, `"start"`

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
- `limit = lngrowsperpage` (default: 50, main.py:121)
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
1. Increment `strapiversion` in main.py:25
2. Create new prompt files in `data/` with version suffix
3. Update filenames in text2sql.py:25-28
4. Test locally first
5. Deploy using appropriate restart script
6. Verify API version in response logs

**Version Format Conversion** (main.py:26-28):
- Input: `"1.1.9"`
- Output: `"001.001.009"` (for SQL storage)

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
# Authentication
API_KEY=your_secret_api_key

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

None currently defined. All variables in `.env.example` are required.

## Security Considerations

1. **API Key Authentication**: All endpoints (except `/`) require `X-API-Key` header
2. **Constant-Time Comparison**: Uses `secrets.compare_digest()` to prevent timing attacks
3. **Environment Variables**: All secrets stored in `.env` (not committed to git)
4. **SQL Injection**: Uses parameterized queries with `cursor.execute(query, params)`
5. **Input Sanitization**: Entity values are SQL-escaped before insertion

## Performance Optimization Tips

1. **Enable Caching**: Keep `retrieve_from_cache=true` and `store_to_cache=true` for best performance
2. **Pagination**: Use `question_hashed` for subsequent pages to avoid re-processing
3. **Similarity Threshold**: Adjust `similarity_threshold` (main.py:130) for cache hit rate vs. accuracy trade-off
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
- Returns `##AMBIGUOUS##` marker
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
- **ChromaDB Documentation**: https://docs.trychroma.com/
- **LangChain Documentation**: https://python.langchain.com/docs/

---

**Last Updated**: 2026-01-10
**Current Version**: 1.1.9
**Maintainer**: See repository owner
