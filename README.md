# FastAPI Text2SQL API

A powerful FastAPI-based REST API that converts natural language questions into SQL queries using LLM provider SDKs (OpenAI, Anthropic, Google Gemini). The API also exposes an MCP (Model Context Protocol) server so Claude clients can use it as a remote tool.

## 🚀 Features

### Core Capabilities
- **Natural Language to SQL**: Convert plain English questions into SQL queries using OpenAI GPT-4o (default), Anthropic Claude, or Google Gemini
- **FastAPI Framework**: High-performance, modern Python web framework with automatic API documentation
- **API Key Authentication**: Secure access with API key validation using constant-time comparison
- **ChromaDB Vector Search**: Advanced similarity search for entity matching and query optimization
- **Entity Extraction & Anonymization**: Intelligent extraction of entities (persons, movies, series, companies, networks, characters, locations, topics, lists, awards, nominations, collections, movements, groups, deaths, genres, technical formats, statuses, series types, release/birth/death years, IMDb / Wikidata / TMDb / Criterion identifiers) with placeholder replacement
- **Config-driven Entity Resolution**: Entity resolution is configured via `data/entity_resolution.json` (embeddings and RapidFuzz strategies), plus a closed-vocabulary layer (`closed_vocab.py` + `data/closed_vocabularies.json`) for `Movie_genre`, `Serie_genre`, `Technical_format` (including aspect ratios), `Status_name`, `Serie_type`, and `Department_name`, and a regex-validated layer in `entity.py` for years and ID-style placeholders
- **DB-driven Canonicals with Hot-Reloaded Aliases**: `Movie_genre`, `Serie_genre`, and `Technical_format` canonicals load at startup from reference tables (`T_WC_TMDB_GENRE` + `T_WC_TMDB_GENRE_LANG`, filtered by `APPLIES_TO_MOVIE` / `APPLIES_TO_SERIE` flags; `T_WC_T2S_TECHNICAL`); `Status_name`, `Serie_type`, and `Department_name` load via DISTINCT queries; format / typo / multilingual aliases live in `data/closed_vocabularies.json` and hot-reload within ~5 seconds
- **Hot-Reloaded `data/` Files**: Prompt templates and entity-resolution configuration under `data/` are reloaded automatically when they change
- **RapidFuzz Person Matching (language-family aware)**: Person resolution uses `guess_language_family()` to route Latin names to `T_WC_T2S_PERSON` and non-Latin names to `T_WC_TMDB_PERSON_ALSO_KNOWN_AS`, while keeping SQL replacement canonical when needed
- **Multi-Level Caching**: Sophisticated three-tier caching system (exact questions, anonymized questions, vector embeddings)
- **Comprehensive Logging**: Automatic logging of all API requests and responses with detailed timing metrics
- **Memory Monitoring**: Built-in system memory usage tracking and reporting
- **Pagination Support**: Built-in pagination with configurable page sizes and question hashing
- **Robust Error Handling**: Enhanced error handling for malformed responses and SQL escaping issues
- **Docker Support**: Containerized deployment with Blue/Green deployment strategy
- **UTF-8 Support**: Proper handling of Unicode characters in queries and logs
- **MCP Server**: Remote MCP endpoint for Claude clients (web, desktop, mobile) via FastMCP 2.x
- **Entity Detail Endpoints**: 14 REST endpoints returning full entity data with embedded relations and usage logging
- **Multi-API Key Support**: Comma-separated `API_KEYS` env var with legacy `API_KEY` fallback

### Advanced Features
- **Localized User-Oriented Answers (`ui_language`)**: Each response includes a plain-language `answer` field describing what the query returns, written in the language specified by `ui_language` (default `"en"`). The answer preserves entity placeholders during generation and is de-anonymized alongside the SQL and justification. `ui_language` is part of the cache key so that the same question cached in different languages gets separate entries.
- **Multi-Language Support**: Handles English, French, and original language titles for movies and series
- **Processing Transparency**: Detailed messages array showing each processing step
- **Configurable LLM Models**: Separate model selection for entity extraction, text-to-SQL conversion, and complex-question escalation
- **Complex Question Escalation (Stronger Model)**: Optional one-time retry using a stronger model to simplify complex questions
- **Retry Model Visibility**: Retry messages explicitly display the selected complex-question model used during reasoning escalation
- **No-Results Escalation**: If SQL executes successfully but returns 0 rows (page 1), the question can be escalated to the stronger model and retried once
- **Automatic Cache Cleanup**: On-startup cache cleanup to remove outdated entries from previous versions
- **Blue/Green Deployment**: Version-based automatic port selection (even versions: port 8000, odd: port 8001)
- **Ambiguous Question Handling**: Best-effort SQL generation even for vague or ambiguous questions — the model always makes a choice rather than requesting clarification
- **Question Hashing**: SHA256 hashing for efficient pagination and cache lookup
- **Fuzzy Entity Matching**: Vector similarity search handles misspellings and variations in entity names
- **SQL Query Optimization**: Automatic removal and replacement of LLM-generated LIMIT/OFFSET clauses
- **Video Search Support**: Search for movie and series videos, trailers, and clips
- **Topic Extraction**: Intelligent genre and theme extraction for content categorization
- **Version Management**: Utility functions for version comparison and formatting

## 📊 Database Scale

The API operates on a comprehensive entertainment database containing (2026-04-12):
- **Movies**: More than 662,000 entries
- **Series**: More than 95,000 entries
- **Persons**: More than 324,000 entries (actors, directors, crew members)

## 🔄 Query Processing Pipeline

The API implements a sophisticated multi-stage pipeline to efficiently convert natural language questions into SQL queries. The pipeline leverages multiple caching layers and entity extraction to maximize performance and accuracy:

### Pipeline Steps

1. **Exact Question Cache Lookup (SQL Database)**
   - Search for the exact user question in the SQL cache (`T_WC_T2S_CACHE` table)
   - If found, return the cached SQL query immediately
   - SQL cache lookup and write operations are centralized in `sql_cache.py`
   - This cache is also used for efficient pagination through result pages

2. **Entity Extraction & Anonymization**
   - If not found in exact cache, extract and anonymize entities from the user question using GPT-4o
   - Entity extraction logic is implemented in `entity.py`
   - Entities extracted include:
     - **Person names** (actors, directors, crew) — placeholder `{{Person_nameN}}`
     - **Movie titles** (English, French, and original language) — placeholder `{{Movie_titleN}}`
     - **TV series titles** (multi-language support) — placeholder `{{Serie_titleN}}`
     - **Company names** (production companies, studios) — placeholder `{{Company_nameN}}`
     - **Network names** (TV networks, streaming platforms) — placeholder `{{Network_nameN}}`
     - **Character names** (e.g., "James Bond", "Sherlock Holmes", "R2-D2") — placeholder `{{Character_nameN}}` *(extracted; resolution falls through to raw fallback substitution)*
     - **Location names** (narrative or filming locations, Wikidata-backed; e.g., "New York City", "Gotham City") — placeholder `{{Location_nameN}}`
     - **Topic names** (themes and recurring-character collections like "World War II", "Christmas", "Philip Marlowe") — placeholder `{{Topic_nameN}}`
     - **List names** (curated rankings/canons such as "Sight and Sound greatest films", "IMDb top 250 tv shows") — placeholder `{{List_nameN}}`
     - **Award names** (e.g., "Palme d'Or", "Academy Award for Best Picture", "Primetime Emmy Award") — placeholder `{{Award_nameN}}`
     - **Nomination names** (the same set, but referenced as a nomination rather than a win) — placeholder `{{Nomination_nameN}}`
     - **Collection names** (trilogies, named series of works, universes, and franchises, e.g., "Dollars Trilogy", "James Bond Collection", "Kill Bill - Saga", "Star Wars", "Marvel Cinematic Universe", "Middle-Earth", "Harry Potter movies") — placeholder `{{Collection_nameN}}`
     - **Movement names** (film movements / stylistic schools, e.g., "Film Noir", "French New Wave", "New Hollywood") — placeholder `{{Movement_nameN}}`
     - **Group names** (organizations, publications, musical/comedy groups associated with persons, e.g., "The Beatles", "Les Cahiers du Cinéma") — placeholder `{{Group_nameN}}`
     - **Death names** (medical or legal cause/circumstance of a person's death, e.g., "liver cirrhosis", "car collision", "homicide") — placeholder `{{Death_nameN}}`
     - **Movie genres** (closed vocabulary backed by `T_WC_TMDB_GENRE` filtered by `APPLIES_TO_MOVIE = 1` + matching multilingual aliases in `T_WC_TMDB_GENRE_LANG`) — placeholder `{{Movie_genreN}}`
     - **Series genres** (closed vocabulary backed by `T_WC_TMDB_GENRE` filtered by `APPLIES_TO_SERIE = 1` + matching multilingual aliases in `T_WC_TMDB_GENRE_LANG`) — placeholder `{{Serie_genreN}}`
     - **Technical formats** (sound systems, color/film/sound technologies, film formats, movie classifications, and **aspect ratios** — closed vocabulary backed by `T_WC_T2S_TECHNICAL`, e.g. `IMAX`, `Technicolor`, `35mm`, `Dolby`, `1.85`, `Academy ratio`, `widescreen`, `4:3`, `16:9`) — placeholder `{{Technical_formatN}}`
     - **Status name** (`Canceled`, `In Production`, `Planned`, `Post Production`, `Released`, `Rumored` — closed vocabulary loaded from `T_WC_T2S_MOVIE.STATUS` ∪ `T_WC_T2S_SERIE.STATUS`) — placeholder `{{Status_nameN}}`
     - **Serie type** (`Documentary`, `Miniseries`, `News`, `Reality`, `Scripted`, `Talk Show`, `Video` — closed vocabulary loaded from `T_WC_T2S_SERIE.SERIE_TYPE`, only with explicit series context) — placeholder `{{Serie_typeN}}`
     - **Department name** (`Art`, `Camera`, `Costume & Make-Up`, `Creator`, `Crew`, `Directing`, `Editing`, `Lighting`, `Production`, `Sound`, `Visual Effects`, `Writing` — **crew-only** closed vocabulary loaded from `CREW_DEPARTMENT` ∪ `KNOWN_FOR_DEPARTMENT` over `T_WC_T2S_PERSON_MOVIE`, `T_WC_T2S_PERSON_SERIE`, `T_WC_T2S_PERSON`, with `'Actors'` / `'Acting'` excluded; cast / actor queries never produce this placeholder — they route via `CREDIT_TYPE = 'cast'` directly) — placeholder `{{Department_nameN}}`
     - **Release year** (extracted alongside a movie title when the user writes `Title (YYYY)`) — placeholder `{{Release_yearN}}`
     - **Birth year / Death year** (4-digit years for person filtering, e.g. "actors born in 1962", "directors who died in 1980") — placeholders `{{Birth_yearN}}` / `{{Death_yearN}}`
     - **Identifiers** (regex-validated, with malformed values rejected): `IMDb_ID` (`tt\d+`), `IMDb_person_ID` (`nm\d+`), `Wikidata_ID` (`Q\d+`), `Wikidata_property_ID` (`P\d+`), `TMDb_ID` (`\d+`), `Criterion_spine_ID` (`\d+`)
   - Replace entities with typed, numbered placeholders (e.g., `{{Person_name1}}`, `{{Movie_title1}}`, `{{Award_name1}}`, `{{Group_name1}}`, `{{Release_year1}}`, `{{Technical_format1}}`)
   - **Documentary disambiguation**: "documentary" is deliberately *not* extracted as a genre or serie type unless the question explicitly mentions series/TV context; the text-to-SQL step handles it directly via `IS_DOCUMENTARY = 1`

3. **Anonymized Question Cache Lookup (SQL Database)**
   - Search for the anonymized question pattern in the SQL cache
   - Enables reuse of SQL logic across similar questions with different entity values
   - Example: "Movies with Brad Pitt" and "Movies with Tom Cruise" share the same anonymized pattern

4. **Embeddings Cache Search (ChromaDB)**
   - If not found in SQL caches, search for similar anonymized questions in the vector embeddings cache
   - Uses semantic similarity matching with OpenAI's `text-embedding-3-large` model
   - **Similarity threshold**: Distance < 0.15 (configurable)
   - Returns cached SQL query if a sufficiently similar question is found

5. **Entity Validation & Resolution**
   - Entity resolution logic is implemented in `entity.py` (with `closed_vocab.py` for the closed-vocabulary layer); `main.py` remains focused on request orchestration.
   - Each placeholder is dispatched to one of four resolver categories:
     - **Embeddings (ChromaDB)** — vector similarity lookup against a per-entity collection (config-driven via `data/entity_resolution.json`).
     - **RapidFuzz (DB lexical)** — normalized + key-prefix + FULLTEXT/LIKE matching against generated SQL columns (config-driven via `data/entity_resolution.json`); strategies can be gated by language family and may include a `resolve_to_canonical` step that maps from an AKA table back to the primary entity table.
     - **Closed vocabulary** ([closed_vocab.py](closed_vocab.py)) — RapidFuzz-backed in-memory lookup against canonical maps loaded from the database at startup, layered with hot-reloaded aliases from [data/closed_vocabularies.json](data/closed_vocabularies.json). `score_cutoff = 85`, `margin = 5`.
     - **Regex-validated** ([entity.py](entity.py) `_REGEX_PLACEHOLDER_RULES`) — patterns matched in order; the value is rejected (placeholder left unresolved → marks question ambiguous) on a regex mismatch. Numeric rules substitute as bare integers (INT columns); string rules substitute as quoted SQL string literals (VARCHAR columns).
   - Per-placeholder strategies (current):
     - **Person names** (`{{Person_nameN}}`): RapidFuzz, language-family aware.
       - Latin scripts → `T_WC_T2S_PERSON` (canonical names) using `PERSON_NAME_NORM` / `PERSON_NAME_KEY` / `POPULARITY`.
       - Non-Latin scripts → `T_WC_TMDB_PERSON_ALSO_KNOWN_AS` (AKA table), then resolved to canonical `T_WC_T2S_PERSON.PERSON_NAME`.
       - SQL substitution always uses the canonical value; justification is formatted as `<aka_name> (<canonical_name>)` only when the AKA differs from the canonical name.
     - **Movie titles** (`{{Movie_titleN}}`): embeddings on `movies` collection, language-routed columns (`en` → `MOVIE_TITLE`, `fr` → `MOVIE_TITLE_FR`, `*` → `ORIGINAL_TITLE`) on `T_WC_T2S_MOVIE`.
     - **TV series titles** (`{{Serie_titleN}}`): embeddings on `series` collection, same `en` / `fr` / `*` routing on `T_WC_T2S_SERIE`.
     - **Company names** (`{{Company_nameN}}`): embeddings on `companies` collection, `T_WC_T2S_COMPANY.COMPANY_NAME`.
     - **Network names** (`{{Network_nameN}}`): embeddings on `networks` collection, `T_WC_T2S_NETWORK.NETWORK_NAME`.
     - **Topic names** (`{{Topic_nameN}}`): embeddings on `topics` collection, `T_WC_T2S_TOPIC.TOPIC_NAME` / `TOPIC_NAME_FR`.
     - **List names** (`{{List_nameN}}`): embeddings on `lists` collection, `T_WC_T2S_LIST.LIST_NAME` / `LIST_NAME_FR`.
     - **Award names** (`{{Award_nameN}}`): embeddings on `awards` collection, `T_WC_T2S_AWARD.AWARD_NAME` / `AWARD_NAME_FR`.
     - **Nomination names** (`{{Nomination_nameN}}`): embeddings on `nominations` collection, `T_WC_T2S_NOMINATION.NOMINATION_NAME` / `NOMINATION_NAME_FR`.
     - **Collection names** (`{{Collection_nameN}}`): embeddings on `collections` collection, `T_WC_T2S_COLLECTION.COLLECTION_NAME` / `COLLECTION_NAME_FR`.
     - **Movement names** (`{{Movement_nameN}}`): embeddings on `movements` collection, `T_WC_T2S_MOVEMENT.MOVEMENT_NAME` / `MOVEMENT_NAME_FR`.
     - **Group names** (`{{Group_nameN}}`): embeddings on `groups` collection, `T_WC_T2S_GROUP.GROUP_NAME` / `GROUP_NAME_FR`.
     - **Death names** (`{{Death_nameN}}`): embeddings on `deaths` collection, `T_WC_T2S_DEATH.DEATH_NAME` / `DEATH_NAME_FR`.
     - **Location names** (`{{Location_nameN}}`): embeddings on `locations` collection, `T_WC_T2S_ITEM.ITEM_LABEL` / `ITEM_LABEL_FR` (Wikidata-backed; locations are linked to movies/series via `T_WC_WIKIDATA_ITEM_PROPERTY` with `ID_PROPERTY IN ('P840', 'P915')`).
     - **Character names** (`{{Character_nameN}}`): currently extracted by the LLM but **not yet wired in `entity_resolution.json`** — the value falls through to the SQL-escaped raw fallback. The `characters` ChromaDB collection is provisioned in [main.py:135](main.py#L135) for upcoming use.
     - **Movie genres** (`{{Movie_genreN}}`) and **Series genres** (`{{Serie_genreN}}`): closed-vocabulary lookup mapping name → integer `ID_GENRE`. Canonicals from `T_WC_TMDB_GENRE`, with each loader filtered by `APPLIES_TO_MOVIE = 1` or `APPLIES_TO_SERIE = 1` so the movie placeholder cannot resolve to a TV-only genre (`Reality`, `Sci-Fi & Fantasy`, `Talk`, …) and the series placeholder cannot resolve to a movie-only genre (`Action`, `Thriller`, `TV Movie`, …); 8 IDs overlap on both sides (Animation, Comedy, Crime, Documentary, Drama, Family, Mystery, Western). Multilingual aliases from `T_WC_TMDB_GENRE_LANG` (currently French; auto-extends to any LANG inserted) joined against the same flag, layered with JSON aliases keyed under `Movie_genre` / `Serie_genre`.
     - **Technical formats** (`{{Technical_formatN}}`): closed-vocabulary lookup mapping name → integer `ID_TECHNICAL`. Canonicals from `T_WC_T2S_TECHNICAL` (sound systems, color/film/sound technologies, film formats, movie classifications, aspect ratios — grouped by `TECHNICAL_TYPE`); aliases from `data/closed_vocabularies.json` only (no `_LANG` companion table yet). Aspect-ratio surface forms (`Academy`, `widescreen`, `flat`, `fullscreen`, `4:3`, `16:9`, `2.35:1`, `2,35` with French comma decimal, dot-decimals like `1.85`) all resolve through this placeholder to the matching aspect-ratio `ID_TECHNICAL`.
     - **Status name** (`{{Status_nameN}}`): closed-vocabulary string substitution for `STATUS` (e.g. `Released`, `Canceled`). Canonicals from `DISTINCT STATUS` over `T_WC_T2S_MOVIE` ∪ `T_WC_T2S_SERIE`.
     - **Serie type** (`{{Serie_typeN}}`): closed-vocabulary string substitution for `SERIE_TYPE` (e.g. `Documentary`, `Miniseries`). Canonicals from `DISTINCT SERIE_TYPE` over `T_WC_T2S_SERIE`.
     - **Department name** (`{{Department_nameN}}`): **crew-only** closed-vocabulary string substitution for `CREW_DEPARTMENT` / `KNOWN_FOR_DEPARTMENT` (e.g. `Directing`, `Camera`, `Visual Effects`). Canonicals from a UNION over `T_WC_T2S_PERSON_MOVIE.CREW_DEPARTMENT`, `T_WC_T2S_PERSON_SERIE.CREW_DEPARTMENT`, and `T_WC_T2S_PERSON.KNOWN_FOR_DEPARTMENT`, with `'Actors'` / `'Acting'` explicitly excluded. The text-to-SQL prompt picks the column based on question intent (person-search → `KNOWN_FOR_DEPARTMENT`, crew-of-content → `CREW_DEPARTMENT`); when `CREW_DEPARTMENT` is filtered via the placeholder, the prompt also enforces `CREDIT_TYPE = 'crew'`. Cast / actor queries (`actors in X`, `actresses born in 1962`) never produce this placeholder — they route via `CREDIT_TYPE = 'cast'` (film context) or `KNOWN_FOR_DEPARTMENT = 'Acting'` (person-search) inline.
     - **Release / Birth / Death years** (`{{Release_yearN}}`, `{{Birth_yearN}}`, `{{Death_yearN}}`): regex `\d{4}`, bare numeric substitution into INT columns.
     - **TMDb / Criterion identifiers** (`{{TMDb_IDN}}`, `{{Criterion_spine_IDN}}`): regex `\d+`, bare numeric substitution into INT primary keys.
     - **IMDb identifiers** (`{{IMDb_IDN}}`, `{{IMDb_person_IDN}}`): regex `tt\d+` / `nm\d+`, quoted SQL string substitution into VARCHAR `ID_IMDB` columns.
     - **Wikidata identifiers** (`{{Wikidata_IDN}}`, `{{Wikidata_property_IDN}}`): regex `Q\d+` / `P\d+`, quoted SQL string substitution into VARCHAR `ID_WIKIDATA` / `ID_PROPERTY` columns.
   - Vector similarity matching ensures fuzzy matching for misspellings and variations
   - Similarity threshold of 0.15 for robust entity matching

   - Safety:
     - If unresolved placeholders remain in the SQL query after entity resolution, the API skips execution to avoid running a broken query.
     - If an embeddings result references an ID that no longer exists in the underlying table, the API emits a diagnostic message indicating the embeddings collection may be out of sync.
     - Closed-vocabulary lookups that fall below the RapidFuzz threshold are rejected (placeholder left unresolved → ambiguous).
     - Regex-validated values that fail the pattern are rejected (placeholder left unresolved → ambiguous), tightening defense against LLM hallucinations on identifier-style entities.

6. **Text-to-SQL Generation (LLM)**
   - If no cache hit occurs, process the anonymized question through the LLM model
   - Uses the prompt template from `data/` folder with comprehensive database schema
   - Files in `data/` are hot-reloaded, so prompt/config edits are picked up automatically without restarting the API
   - GPT-4o generates a SQL query based on the anonymized question pattern
   - **Best-effort interpretation**: The model always produces a SQL query even when the question is ambiguous; it never returns an error solely because of ambiguity
   - This is the core text-to-SQL task

7. **Query De-anonymization**
   - Replace placeholders in the generated SQL query, justification, and answer with actual validated entity values
   - Apply parameters from the entity extraction step (person names, movie titles, etc.)
   - Produce the complete, executable SQL query with proper SQL escaping
   - The `answer` field undergoes the same de-anonymization as `justification`

8. **SQL Execution & Retry Strategy**
   - Execute the SQL query against MariaDB with pagination support
   - Three conditions can trigger a one-time **full pipeline retry** using the stronger model (`llm_model_complex`), **but only when `complex_question_processing: true`**:
     - The text-to-SQL model returns an error instead of a SQL query
     - The generated SQL raises a MariaDB execution error
     - The generated SQL runs successfully but returns 0 rows on page 1
   - **Zero-count direct answer**: If the SQL returns a single row with a single column whose value is 0 (e.g., an incorrect `COUNT`), the stronger model is asked to directly provide the correct scalar value — no full pipeline retry. A synthetic SQL is built (e.g., `SELECT 4 AS 'How many Academy awards did Katharine Hepburn win?' FROM DUAL`), **executed** against MariaDB, and its result is returned. The synthetic SQL is then cached so subsequent calls return the answer directly without invoking the stronger model again. This execute-then-cache approach ensures **consistency** (the result always comes from SQL execution, same as every other query) and **validation** (the synthetic SQL is confirmed to be well-formed before being persisted to the cache).
   - When `complex_question_processing: false` (default), none of the above triggers fire; the raw failure or empty result is returned immediately.
   - Retry messages in the `messages` array include the selected `llm_model_complex` value so clients can see which stronger model handled the escalation.
   - For complex-question resolution, `o1*` and `o3*` models use a compatible temperature of `1`, while the other supported model families continue using `0`.

9. **Cache Population**
   - **Exact question cache**: Save the original question and SQL query to `T_WC_T2S_CACHE` (if applicable)
   - **Anonymized question cache**: Save the anonymized question and SQL pattern to SQL cache (if applicable)
   - **Embeddings cache**: Save the anonymized question embedding and SQL query to ChromaDB for future semantic searches
   - **Escalated complex-question cache**: After a successful stronger-model retry, the original complex question is also saved to SQL cache with the final SQL returned by the retried pipeline
   - Cache entries include the `ANSWER` field and `UI_LANGUAGE`; cache lookups filter by `UI_LANGUAGE` so different languages get separate entries

10. **Result Return**
    - Return the result set to the client with comprehensive metadata:
      - Generated SQL query
      - Query results (paginated)
      - User-oriented `answer` in the requested `ui_language`
      - Performance metrics (entity extraction time, text2SQL time, embeddings time, query execution time)
      - Cache hit indicators
      - Pagination information
      - If a stronger-model retry happened, the final `justification` can be taken from the stronger model.

### Pipeline Benefits

- **Performance**: Multi-tier caching dramatically reduces LLM API calls and processing time
- **Accuracy**: Entity validation ensures correct matching even with misspellings
- **Reusability**: Anonymization enables query pattern reuse across different entity values
- **Scalability**: Vector embeddings enable semantic search across millions of questions
- **Transparency**: Detailed timing metrics and cache indicators in every response

## 📋 Requirements

- Python 3.8+
- OpenAI API key
- ChromaDB server (for vector search functionality)
- MariaDB/MySQL database
- Dependencies listed in `requirements.txt`

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/vaugouin/FastAPI-Text2SQL.git
   cd FastAPI-Text2SQL
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   
   Create a `.env` file in the project root (you can copy from `.env.example`):
   ```env
   # API keys for authentication (comma-separated list)
   API_KEYS=key_for_app,key_for_mcp,key_for_scripts
   # OpenAI API Key for Text2SQL conversion
   OPENAI_API_KEY=your_openai_api_key_here
   
   # Optional LLM provider keys (only needed if using non-OpenAI models)
   ANTHROPIC_API_KEY=your_anthropic_api_key_here
   GOOGLE_API_KEY=your_google_api_key_here
   OPENROUTER_API_KEY=your_openrouter_api_key_here
   
   # Database Configuration
   DB_HOST=localhost
   DB_PORT=3306
   DB_USER=your_db_user
   DB_PASSWORD=your_db_password
   DB_NAME=your_database_name
   
   # ChromaDB Configuration
   CHROMADB_HOST=localhost
   CHROMADB_PORT=8000
   
   # API Port Configuration (Blue/Green deployment)
   API_PORT_BLUE=8000
   API_PORT_GREEN=8001
   
   # MCP (Model Context Protocol) — Claude connector at /mcp
   MCP_API_KEY=your_mcp_bearer_token_here
   MCP_INTERNAL_API_KEY=key_for_mcp
   ```

   Provider key usage:
   - `OPENAI_API_KEY` is required for `gpt-*`, `o1*`, and `o3*` models.
   - `ANTHROPIC_API_KEY` is required for `claude-*` models.
   - `GOOGLE_API_KEY` is required for `gemini-*` and `gemma-4-google`.
   - `OPENROUTER_API_KEY` is required for `gemma-4`.

## 🚀 Usage

### Starting the Server

```bash
python main.py
```

The API will be available at `http://localhost:8000`

### API Documentation

Once the server is running, visit:
- **Interactive API docs**: `http://localhost:8000/docs`
- **ReDoc documentation**: `http://localhost:8000/redoc`

### API Endpoints

#### 1. Health Check
```http
GET /
```
Returns a simple "Hello World" message to verify the API is running.

#### 2. Text to SQL Conversion
```http
POST /search/text2sql
```

**Headers Required:**
```
X-API-Key: your_api_key
Content-Type: application/json
```

**Request Body:**
```json
{
  "question": "List all color movies with Humphrey Bogart",
  "page": 1,
  "rows_per_page": 50,
  "retrieve_from_cache": true,
  "store_to_cache": true,
  "llm_model_entity_extraction": "default",
  "llm_model_text2sql": "default",
  "llm_model_complex": "default",
  "complex_question_processing": false,
  "ui_language": "en"
}
```

**Request Parameters:**
- `question` (optional, str): Natural language question to convert to SQL
- `question_hashed` (optional, str): SHA256 hash of a previously processed question for pagination
- `page` (optional, int, default: 1): Page number for pagination
- `rows_per_page` (optional, int, default: 50): Number of rows per page (used to compute `limit` and `offset`)
- `retrieve_from_cache` (optional, bool, default: true): Whether to check cache for existing results
- `store_to_cache` (optional, bool, default: true): Whether to store results in cache
- `llm_model_entity_extraction` (optional, str, default: "default"): LLM model to use for entity extraction
- `llm_model_text2sql` (optional, str, default: "default"): LLM model to use for text-to-SQL conversion
- `llm_model_complex` (optional, str, default: "default"): LLM model to use for complex-question resolution / stronger-model retry
- `ui_language` (optional, str, default: `"en"`): Language code for the user-oriented `answer` field in the response. Only `"en"` (English) and `"fr"` (French) are supported; the value is normalized (case-insensitive, region/script subtags stripped, so `"fr-FR"` → `"fr"`) and any missing, empty, or unsupported value falls back to `"en"`. The answer is a plain-language sentence describing what the query returns, written in the specified language, with no table/column names or SQL details. This value is also used as part of the cache key, so the same question submitted with different `ui_language` values produces separate cache entries.
- `complex_question_processing` (optional, bool, default: `false`): Controls whether the API is allowed to escalate to the stronger model when the primary pipeline fails. When `false` (the default), the API returns the raw error or empty result set directly to the caller without retrying. When `true`, the three automatic retry triggers are active:
  - The text-to-SQL model cannot produce a SQL query and returns an error
  - The generated SQL raises an execution error on the database
  - The generated SQL executes successfully but returns an empty result set

  Set to `false` when calling from an agent or MCP tool so that the agent itself handles error conditions and decides whether to rephrase or escalate the question.

**Supported LLM Values for the 3 model parameters:**

- `default`
  - Uses the module default for the corresponding stage
  - Current defaults:
    - `llm_model_entity_extraction` → `gpt-4o`
    - `llm_model_text2sql` → `gpt-4o`
    - `llm_model_complex` → `gpt-4o`

- OpenAI models
  - Supported when the value is:
    - exactly `gpt-4o`
    - any model starting with `gpt-`
    - any model starting with `o1`
    - any model starting with `o3`
  - Examples:
    - `gpt-4o`
    - `gpt-4.1`
    - `gpt-4.1-mini`
    - `o1`
    - `o1-mini`
    - `o3`
    - `o3-mini`

- Anthropic models
  - Supported when the value starts with `claude-`
  - Examples:
    - `claude-3-5-sonnet`
    - `claude-3-7-sonnet`
    - `claude-sonnet-4`
    - `claude-haiku-4-5-20251001`

- Google Gemini models
  - Supported when the value starts with `gemini-`
  - Examples:
    - `gemini-2.5-flash`
    - `gemini-1.5-pro`
    - `gemini-1.5-flash`
    - `gemini-1.0-pro`
  - Gemini requests may also try fallback aliases such as `-latest` and a small set of known Gemini variants when the requested model name is not found.

- Google Gemma 4 direct
  - Supported when the value is exactly `gemma-4-google`
  - Routed directly to Google using the official `google-genai` SDK
  - Current mapped Google model:
    - `gemma-4-26b-a4b-it`
  - Requires `GOOGLE_API_KEY`

- OpenRouter Gemma 4
  - Supported when the value is exactly `gemma-4`
  - Routed through OpenRouter
  - Current mapped OpenRouter model:
    - `google/gemma-4-26b-a4b-it:free`
  - Requires `OPENROUTER_API_KEY`

**Notes:**

- The same model families are accepted for:
  - `llm_model_entity_extraction`
  - `llm_model_text2sql`
  - `llm_model_complex`
- `gemma-4-google` is intended for direct Google Gemma 4 access on entity extraction and text-to-SQL.
- `gemma-4` is available through OpenRouter and is useful if you prefer the OpenRouter route for Gemma 4.
- For `llm_model_complex`, if the selected stronger model is unavailable and it is not already `gpt-4o`, the application may retry once with `gpt-4o`.
- For `llm_model_complex`, `o1*` and `o3*` models are called with `temperature=1` for compatibility, while the other supported model families use `temperature=0` in the complex-question flow.
- The project now uses Google's current `google-genai` SDK for Google-hosted Gemini and Gemma requests.

**Note:** Either `question` or `question_hashed` must be provided.

**Example:**
```bash
curl -X POST "http://localhost:8000/search/text2sql" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "List all color movies with Humphrey Bogart",
       "page": 1,
       "rows_per_page": 50,
       "retrieve_from_cache": true,
       "store_to_cache": true
     }'
```

**Response:**
```json
{
  "question": "List all color movies with Humphrey Bogart",
  "question_hashed": "a1b2c3d4e5f6...",
  "sql_query": "SELECT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.TITLE... LIMIT 50",
  "sql_query_anonymized": "SELECT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.TITLE... WHERE p.PERSON_NAME = '{{Person_name1}}'",
  "justification": "Filters movies whose color status is non-B&W and joins with Humphrey Bogart's filmography.",
  "justification_anonymized": "Filters movies whose color status is non-B&W and joins with {{Person_name1}}'s filmography.",
  "answer": "Here are all the color movies featuring Humphrey Bogart.",
  "answer_anonymized": "Here are all the color movies featuring {{Person_name1}}.",
  "ui_language": "en",
  "error": "",
  "error_code": null,
  "is_retryable": false,
  "retry_after_seconds": null,
  "provider": null,
  "entity_extraction": {
    "question": "List all color movies with {{Person_name1}}",
    "Person_name1": "Humphrey Bogart"
  },
  "question_anonymized": "List all color movies with {{Person_name1}}",
  "entity_extraction_processing_time": 0.45,
  "text2sql_processing_time": 1.23,
  "embeddings_processing_time": 0.12,
  "embeddings_cache_search_time": 0.05,
  "query_execution_time": 0.08,
  "total_processing_time": 1.93,
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
  "complex_model_used": false,
  "api_version": "1.1.16",
  "messages": [
    {
      "position": 1,
      "text": "Stripped whitespace and carriage return characters from question."
    },
    {
      "position": 2,
      "text": "Entity extraction successful; question anonymized."
    },
    {
      "position": 3,
      "text": "Executing SQL query: SELECT..."
    }
  ],
  "result": [
    {
      "index": 0,
      "data": {
        "ID_MOVIE": 488,
        "TITLE": "The African Queen",
        "RELEASE_YEAR": 1952,
        "...": "..."
      }
    }
  ]
}
```

**Response Fields:**

**Core Fields:**
- `question` (str): The original or retrieved natural language question
- `question_hashed` (str, optional): SHA256 hash of the question for pagination/caching
- `sql_query` (str): The generated and optimized SQL query (with entities resolved)
- `sql_query_anonymized` (str): The same SQL with entity values replaced by typed placeholders (e.g. `{{Person_name1}}`); useful for cache pattern matching and debugging
- `justification` (str): Explanation or reasoning for the SQL query (if provided by the LLM), with entities resolved
- `justification_anonymized` (str): The `justification` before entity de-anonymization (with placeholders)
- `answer` (str): User-oriented plain-language description of what the query returns, written in the language specified by `ui_language`. Contains no table/column names or SQL details. Intended to be displayed above query results.
- `answer_anonymized` (str): The `answer` before entity de-anonymization (with placeholders)
- `entity_extraction` (dict, optional): Full LLM entity extraction output, including the anonymized `question` key plus one key per extracted placeholder (e.g., `Person_name1`, `Movie_title1`)
- `question_anonymized` (str, optional): The user question with entities replaced by typed placeholders
- `error` (str): Error message if query processing failed (e.g., the LLM's explanation when the question is ambiguous)
- `error_code` (str, optional): Structured API error code when the failure can be classified. Currently `"429"` is used for retryable provider quota / rate-limit failures.
- `is_retryable` (bool): Indicates whether the client should treat the failure as retryable.
- `retry_after_seconds` (float, optional): Suggested wait time before retrying the request. When available, this is extracted from the underlying provider response.
- `provider` (str, optional): Provider associated with the failure when it can be inferred, such as `google`, `openrouter`, `openai`, or `anthropic`.
- `result` (list): Array of query results, each with `index` (int) and `data` (dict)

**Performance Metrics:**
- `entity_extraction_processing_time` (float): Time for entity extraction in seconds
- `text2sql_processing_time` (float): Time for SQL generation in seconds
- `embeddings_processing_time` (float): Time for vector search operations in seconds
- `embeddings_cache_search_time` (float): Time for embeddings cache lookup in seconds
- `query_execution_time` (float): Time for SQL execution in seconds
- `total_processing_time` (float): Total request processing time in seconds

**Pagination:**
- `page` (int, optional): Current page number
- `llm_defined_limit` (int, optional): LLM-specified limit if any
- `llm_defined_offset` (int, optional): LLM-specified offset if any
- `limit` (int, optional): Records per page
- `offset` (int, optional): Current offset
- `rows_per_page` (int, optional): Configured page size (default: 50)

**Cache Indicators:**
- `cached_exact_question` (bool): Whether exact question was found in cache
- `cached_anonymized_question` (bool): Whether anonymized question was cached
- `cached_anonymized_question_embedding` (bool): Whether similar question found via embeddings

**Configuration & Status:**
- `ambiguous_question_for_text2sql` (bool): Whether question was too ambiguous for SQL generation, or entity resolution left unresolved placeholders
- `llm_model_entity_extraction` (str): LLM model actually used for entity extraction (resolved value, never `"default"`)
- `llm_model_text2sql` (str): LLM model actually used for text-to-SQL conversion
- `llm_model_complex` (str): LLM model **configured** for complex-question resolution / stronger-model retry — exposed even when the retry path was not taken
- `complex_model_used` (bool, default `false`): **Whether the stronger model was actually invoked** during the request — set to `true` when any of the four complex-retry code paths fired (text2sql error, SQL execution error, zero-row result on page 1, or single-cell zero-count direct answer). Use this rather than `llm_model_complex` to know whether the extra LLM call happened.
- `ui_language` (str): Normalized language code used for the `answer` field and the cache key — either `"en"` or `"fr"` (any other requested value falls back to `"en"`)
- `api_version` (str): Current API version
- `messages` (list): Array of processing step messages, each with `position` (int) and `text` (str). On a stronger-model retry, the messages from the outer and inner runs are merged and renumbered.

#### 3. Entity Detail Endpoints

All entity detail endpoints require the same API key header as `/search/text2sql`:

```http
X-API-Key: your_api_key
```

Each endpoint returns `404` when the requested entity is not found. Successful responses include every column selected with `SELECT *` from the endpoint's primary `T_WC_T2S_*` table, plus the embedded relation arrays documented below.

| Method | Endpoint | Identifier | Primary table | Purpose |
|---|---|---|---|---|
| `GET` | `/movies/{id}` | `ID_MOVIE` | `T_WC_T2S_MOVIE` | Movie detail |
| `GET` | `/series/{id}` | `ID_SERIE` | `T_WC_T2S_SERIE` | TV series detail |
| `GET` | `/seasons/{id_serie}/{season_number}` | `(ID_SERIE, SEASON_NUMBER)` | `T_WC_TMDB_SEASON` (TMDb source — no T2S equivalent yet) | TV series season detail |
| `GET` | `/episodes/{id_serie}/{season_number}/{episode_number}` | `(ID_SERIE, SEASON_NUMBER, EPISODE_NUMBER)` | `T_WC_TMDB_EPISODE` (TMDb source — no T2S equivalent yet) | TV series episode detail |
| `GET` | `/persons/{id}` | `ID_PERSON` | `T_WC_T2S_PERSON` | Person detail |
| `GET` | `/companies/{id}` | `ID_COMPANY` | `T_WC_T2S_COMPANY` | Production company detail |
| `GET` | `/networks/{id}` | `ID_NETWORK` | `T_WC_T2S_NETWORK` | TV network detail |
| `GET` | `/collections/{id}` | `ID_T2S_COLLECTION` | `T_WC_T2S_COLLECTION` | Collection, franchise, or universe detail |
| `GET` | `/topics/{id}` | `ID_TOPIC` | `T_WC_T2S_TOPIC` | Topic detail |
| `GET` | `/lists/{id}` | `ID_T2S_LIST` | `T_WC_T2S_LIST` | Curated list detail |
| `GET` | `/movements/{id}` | `ID_MOVEMENT` | `T_WC_T2S_MOVEMENT` | Film movement or style detail |
| `GET` | `/technicals/{id}` | `ID_TECHNICAL` | `T_WC_T2S_TECHNICAL` | Technical format detail (sound system, color/film/sound technology, film format) |
| `GET` | `/groups/{id}` | `ID_GROUP` | `T_WC_T2S_GROUP` | Person group detail |
| `GET` | `/deaths/{id}` | `ID_DEATH` | `T_WC_T2S_DEATH` | Cause or circumstance of death detail |
| `GET` | `/awards/{id}` | `ID_AWARD` | `T_WC_T2S_AWARD` | Award detail |
| `GET` | `/nominations/{id}` | `ID_NOMINATION` | `T_WC_T2S_NOMINATION` | Award nomination detail |
| `GET` | `/locations/{wikidata_id}` | `ID_WIKIDATA`, e.g. `Q90` | `T_WC_T2S_ITEM` | Location detail |

##### `GET /movies/{id}`

Returns all `T_WC_T2S_MOVIE` fields for the TMDb movie ID `ID_MOVIE`, plus the embedded arrays below. Key order mirrors the "Default Sorting" section of [data/text_to_sql.md](data/text_to_sql.md):

| Field | Shape |
|---|---|
| `genres` | Array of `ID_GENRE` integers |
| `companies` | Array of `{ ID_COMPANY, COMPANY_NAME, LOGO_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `ID_COMPANY` |
| `production_countries` | Array of `COUNTRY_CODE` strings |
| `spoken_languages` | Array of `SPOKEN_LANGUAGE` strings |
| `topics` | Array of `{ ID_TOPIC, TOPIC_NAME, TOPIC_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `lists` | Array of `{ ID_T2S_LIST, LIST_NAME, LIST_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `collections` | Array of `{ ID_T2S_COLLECTION, COLLECTION_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `movements` | Array of `{ ID_MOVEMENT, MOVEMENT_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `technicals` | Array of `{ ID_TECHNICAL, DESCRIPTION, DESCRIPTION_FR, TECHNICAL_TYPE, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }` from `T_WC_T2S_MOVIE_TECHNICAL` joined to `T_WC_T2S_TECHNICAL`, ordered by `DISPLAY_ORDER`. `TECHNICAL_TYPE` is one of `sound_system`, `color_technology`, `film_technology`, `sound_technology`, `film_format` |
| `awards` | Array of `{ ID_AWARD, AWARD_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `nominations` | Array of `{ ID_NOMINATION, NOMINATION_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `cast` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER`. For non-documentary movies (`IS_DOCUMENTARY != 1`), rows whose `CAST_CHARACTER` is one of `Self`, `Himself`, `Herself`, `(archive footage)`, `Self (archive footage)`, `Self (archive footage) (uncredited)`, or `Self (uncredited)` are excluded |
| `crew` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `DISPLAY_ORDER` |
| `posters` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_MOVIE_IMAGE` where `TYPE_IMAGE = 'poster'`, ordered by `DISPLAY_ORDER` |
| `backdrops` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_MOVIE_IMAGE` where `TYPE_IMAGE = 'backdrop'`, ordered by `DISPLAY_ORDER` |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the movie's `ID_WIKIDATA`, filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the movie's `ID_WIKIDATA`, filtered to `LANG = 'en'` and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT`. Empty when `ID_WIKIDATA` is NULL |
| `videos` | Array of `{ SOURCE, VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE, LANG, OFFICIAL, DAT_PUBLISHED, DURATION_SECONDS, WATCH_URL, EMBED_URL, FILE_URL, THUMBNAIL_URL, DISPLAY_ORDER }` merging TMDb-sourced videos (`T_WC_TMDB_MOVIE_VIDEO`, `SOURCE='tmdb'`) and Wikidata-sourced videos (`T_WC_WIKIDATA_MEDIA_RESOURCE` joined to `T_WC_WIKIDATA_MEDIA_RESOURCE_URL`, `SOURCE='wikidata'`, filtered to `RESOURCE_KIND='video'`, `IS_ACTIVE=1`, `DELETED=0`). TMDb rows are listed first (`OFFICIAL DESC, DISPLAY_ORDER ASC`), then Wikidata rows (`IS_PREFERRED_RESOURCE DESC, SOURCE_PRIORITY ASC`). For TMDb rows, `WATCH_URL`/`EMBED_URL`/`THUMBNAIL_URL` are synthesized from `VIDEO_SITE` + `VIDEO_KEY` (YouTube and Vimeo); `FILE_URL` is null. For Wikidata rows, URLs are pivoted from `T_WC_WIKIDATA_MEDIA_RESOURCE_URL` by `URL_TYPE` ('watch', 'embed', 'file', 'thumbnail'); `OFFICIAL` and `DAT_PUBLISHED` are null, `DISPLAY_ORDER` is null. Empty when neither source has video rows for the movie |

Base movie fields currently include `ID_MOVIE`, `MOVIE_TITLE`, `DAT_RELEASE`, `RELEASE_YEAR`, `RELEASE_MONTH`, `RELEASE_DAY`, `ID_IMDB`, `ID_WIKIDATA`, `POSTER_PATH`, `POPULARITY`, `ORIGINAL_LANGUAGE`, `STATUS`, `BUDGET`, `RUNTIME`, `BACKDROP_PATH`, `REVENUE`, `TAGLINE`, `VIDEO`, `VOTE_AVERAGE`, `VOTE_COUNT`, `IS_COLOR`, `IS_BLACK_AND_WHITE`, `IS_SILENT`, `IS_MOVIE`, `IS_DOCUMENTARY`, `IS_SHORT_FILM`, `DAT_CREAT`, `TIM_UPDATED`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `WIKIDATA_TITLE`, `ALIASES`, `PLEX_MEDIA_KEY`, `ID_CRITERION`, `ID_CRITERION_SPINE` and `INSTANCE_OF`.

##### `GET /series/{id}`

Returns all `T_WC_T2S_SERIE` fields for the TMDb series ID `ID_SERIE`, plus the embedded arrays below. Key order mirrors the "Default Sorting" section of [data/text_to_sql.md](data/text_to_sql.md):

| Field | Shape |
|---|---|
| `genres` | Array of `ID_GENRE` integers |
| `companies` | Array of `{ ID_COMPANY, COMPANY_NAME, LOGO_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `ID_COMPANY` |
| `networks` | Array of `{ ID_NETWORK, NETWORK_NAME, LOGO_PATH }`, ordered by `ID_NETWORK` |
| `production_countries` | Array of `COUNTRY_CODE` strings |
| `spoken_languages` | Array of `SPOKEN_LANGUAGE` strings |
| `topics` | Array of `{ ID_TOPIC, TOPIC_NAME, TOPIC_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `lists` | Array of `{ ID_T2S_LIST, LIST_NAME, LIST_TYPE, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `collections` | Array of `{ ID_T2S_COLLECTION, COLLECTION_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `movements` | Array of `{ ID_MOVEMENT, MOVEMENT_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `awards` | Array of `{ ID_AWARD, AWARD_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `nominations` | Array of `{ ID_NOMINATION, NOMINATION_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `cast` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER`. No self-appearance filter is applied on the series side (text-to-SQL behavior is symmetric) |
| `crew` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `DISPLAY_ORDER` |
| `posters` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_SERIE_IMAGE` where `TYPE_IMAGE = 'poster'`, ordered by `DISPLAY_ORDER` |
| `backdrops` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_SERIE_IMAGE` where `TYPE_IMAGE = 'backdrop'`, ordered by `DISPLAY_ORDER` |
| `seasons` | Array of `{ ID_SEASON, SEASON_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, POSTER_PATH, EPISODE_COUNT, VOTE_AVERAGE, ID_IMDB, ID_WIKIDATA, ID_TVDB }` from `T_WC_TMDB_SEASON` (the TMDb source table — no `T_WC_T2S_SEASON` read-model table exists), ordered by `SEASON_NUMBER ASC`. Season 0 (specials) is included when present |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the series's `ID_WIKIDATA`, filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the series's `ID_WIKIDATA`, filtered to `LANG = 'en'` and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT`. Empty when `ID_WIKIDATA` is NULL |
| `videos` | Array of `{ SOURCE, VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE, LANG, OFFICIAL, DAT_PUBLISHED, DURATION_SECONDS, WATCH_URL, EMBED_URL, FILE_URL, THUMBNAIL_URL, DISPLAY_ORDER }` merging TMDb-sourced videos (`T_WC_TMDB_SERIE_VIDEO`, `SOURCE='tmdb'`) and Wikidata-sourced videos (`T_WC_WIKIDATA_MEDIA_RESOURCE`, `SOURCE='wikidata'`, filtered to `RESOURCE_KIND='video'`). Ordering and field semantics match the `/movies/{id}` `videos` row |

Base series fields currently include `ID_SERIE`, `SERIE_TITLE`, `DAT_FIRST_AIR`, `FIRST_AIR_YEAR`, `FIRST_AIR_MONTH`, `FIRST_AIR_DAY`, `DAT_LAST_AIR`, `LAST_AIR_YEAR`, `LAST_AIR_MONTH`, `LAST_AIR_DAY`, `ID_IMDB`, `ID_WIKIDATA`, `POSTER_PATH`, `POPULARITY`, `ORIGINAL_LANGUAGE`, `STATUS`, `BACKDROP_PATH`, `TAGLINE`, `VOTE_AVERAGE`, `VOTE_COUNT`, `NUMBER_OF_EPISODES`, `NUMBER_OF_SEASONS`, `SERIE_TYPE`, `DAT_CREAT`, `TIM_UPDATED`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `WIKIDATA_TITLE`, `ALIASES`, `PLEX_MEDIA_KEY`, and `INSTANCE_OF`.

##### `GET /seasons/{id_serie}/{season_number}`

Returns all `T_WC_TMDB_SEASON` fields for a single season of a TV series, identified by the composite key `(ID_SERIE, SEASON_NUMBER)`. Season `0` is the specials season when present. Returns `404` when the season does not exist for the given series.

Example: `GET /seasons/1396/5` returns season 5 of *Breaking Bad* (ID_SERIE 1396).

The endpoint currently reads from the TMDb source tables `T_WC_TMDB_SEASON`, `T_WC_TMDB_PERSON_SEASON`, and `T_WC_TMDB_SEASON_IMAGE` because the `T_WC_T2S_SEASON` read-model table does not yet exist. Field set will broaden (and field names may shift slightly) once the T2S equivalent is created — see [SEASONS_AND_EPISODES.md](SEASONS_AND_EPISODES.md) §6.1.

| Field | Shape |
|---|---|
| `cast` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, TOTAL_EPISODE_COUNT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER`. `TOTAL_EPISODE_COUNT` is the number of episodes the person appeared in across the season |
| `crew` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, TOTAL_EPISODE_COUNT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `DISPLAY_ORDER` |
| `posters` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_TMDB_SEASON_IMAGE` where `TYPE_IMAGE = 'poster'`, ordered by `DISPLAY_ORDER` |
| `backdrops` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_TMDB_SEASON_IMAGE` where `TYPE_IMAGE = 'backdrop'`, ordered by `DISPLAY_ORDER`. Most TMDb seasons only have posters, so this list is frequently empty |
| `series` | Object `{ ID_SERIE, SERIE_TITLE, POSTER_PATH }` for the parent series — navigation stub so the frontend can render breadcrumbs without a second `/series/{id}` round trip |
| `episodes` | Array of `{ ID_EPISODE, EPISODE_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, RUNTIME, EPISODE_TYPE, STILL_PATH, VOTE_AVERAGE, VOTE_COUNT, ID_IMDB, ID_WIKIDATA, ID_TVDB }` from `T_WC_TMDB_EPISODE`, ordered by `EPISODE_NUMBER ASC`. Length matches the season's `EPISODE_COUNT`. Each row is a **summary**: episode cast/crew, additional stills, and Wikipedia payloads live on `/episodes/{id_serie}/{season_number}/{episode_number}` and are not duplicated here to keep the season payload bounded. To open a specific episode, call `/episodes/{id_serie}/{season_number}/{EPISODE_NUMBER}` (the path key is `EPISODE_NUMBER`, not the surrogate `ID_EPISODE`) |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the season's `ID_WIKIDATA`, filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL — common for seasons |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the season's `ID_WIKIDATA`, filtered to `LANG = 'en'` and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL |
| `videos` | Array of TMDb-sourced videos (`SOURCE='tmdb'`) for this season from `T_WC_TMDB_SEASON_VIDEO`, ordered by `OFFICIAL DESC, DISPLAY_ORDER ASC`. Wikidata media is not modeled at the season level. Field shape matches the `/movies/{id}` `videos` row (Wikidata-only fields like `DURATION_SECONDS` are always null here) |

Base season fields currently include `ID_SEASON`, `ID_SERIE`, `SEASON_NUMBER`, `TITLE`, `OVERVIEW`, `AIR_YEAR`, `AIR_MONTH`, `AIR_DAY`, `DAT_AIR`, `POSTER_PATH`, `EPISODE_COUNT`, `VOTE_AVERAGE`, `ID_IMDB`, `ID_WIKIDATA`, `ID_TVDB`, `DELETED`, `DISPLAY_ORDER`, plus the standard TMDb provenance/timestamp columns (`DAT_CREAT`, `TIM_UPDATED`, `TIM_CREDITS_COMPLETED`, `TIM_IMAGES_COMPLETED`, `TIM_VIDEOS_COMPLETED`, `TIM_TRANSLATIONS_COMPLETED`, `TIM_EPISODES_COMPLETED`, `TIM_WIKIDATA_COMPLETED`).

##### `GET /episodes/{id_serie}/{season_number}/{episode_number}`

Returns all `T_WC_TMDB_EPISODE` fields for a single episode, identified by the composite key `(ID_SERIE, SEASON_NUMBER, EPISODE_NUMBER)`. Returns `404` when the episode does not exist for the given series and season.

Example: `GET /episodes/1396/5/14` returns "Ozymandias" — *Breaking Bad* season 5, episode 14.

The endpoint currently reads from the TMDb source tables `T_WC_TMDB_EPISODE`, `T_WC_TMDB_PERSON_EPISODE`, and `T_WC_TMDB_EPISODE_IMAGE` because the `T_WC_T2S_EPISODE` read-model table does not yet exist. Field set will broaden (and field names may shift slightly) once the T2S equivalent is created — see [SEASONS_AND_EPISODES.md](SEASONS_AND_EPISODES.md) §6.1.

| Field | Shape |
|---|---|
| `cast` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER` |
| `crew` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `DISPLAY_ORDER` |
| `stills` | Array of `{ ID_ROW, TYPE_IMAGE, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_TMDB_EPISODE_IMAGE`, ordered by `DISPLAY_ORDER`. TMDb episodes typically only carry still frames; any other `TYPE_IMAGE` rows stored upstream are surfaced as-is and can be filtered client-side. The episode's canonical frame is available directly on the base row as `STILL_PATH` |
| `season` | Object `{ ID_SEASON, SEASON_NUMBER, TITLE, POSTER_PATH }` for the parent season — navigation stub so the frontend can render breadcrumbs without a second `/seasons/{id_serie}/{season_number}` round trip |
| `series` | Object `{ ID_SERIE, SERIE_TITLE, POSTER_PATH }` for the parent series — second-level navigation stub |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the episode's `ID_WIKIDATA`. Almost always empty — very few TMDb episodes have a Wikidata mapping |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the episode's `ID_WIKIDATA`. Almost always empty for the same reason |
| `videos` | Array of TMDb-sourced videos (`SOURCE='tmdb'`) for this episode from `T_WC_TMDB_EPISODE_VIDEO`, ordered by `OFFICIAL DESC, DISPLAY_ORDER ASC`. Wikidata media is not modeled at the episode level. Field shape matches the `/movies/{id}` `videos` row |

Base episode fields currently include `ID_EPISODE`, `ID_SERIE`, `ID_SEASON`, `SEASON_NUMBER`, `EPISODE_NUMBER`, `TITLE`, `OVERVIEW`, `AIR_YEAR`, `AIR_MONTH`, `AIR_DAY`, `DAT_AIR`, `RUNTIME`, `PRODUCTION_CODE`, `EPISODE_TYPE` (e.g. `standard`, `pilot`, `finale`, `mid_season`), `STILL_PATH`, `VOTE_AVERAGE`, `VOTE_COUNT`, `ID_IMDB`, `ID_WIKIDATA`, `ID_TVDB`, `DELETED`, `DISPLAY_ORDER`, plus the standard TMDb provenance/timestamp columns (`DAT_CREAT`, `TIM_UPDATED`, `TIM_CREDITS_COMPLETED`, `TIM_IMAGES_COMPLETED`, `TIM_VIDEOS_COMPLETED`, `TIM_TRANSLATIONS_COMPLETED`, `TIM_WIKIDATA_COMPLETED`).

**Drill-down pattern**: `/series/{id}` exposes a `seasons[]` summary (each row carries `ID_SEASON`, `SEASON_NUMBER`) → click into `/seasons/{id_serie}/{season_number}` for the full season cast/crew/posters → click into `/episodes/{id_serie}/{season_number}/{episode_number}` for the full episode payload with its own cast/crew/stills. Each level fetches only what it needs; long shows (400+ episodes) do not bloat the `/series` payload.

##### `GET /persons/{id}`

Returns all `T_WC_T2S_PERSON` fields for the TMDb person ID `ID_PERSON`, plus:

| Field | Shape |
|---|---|
| `movie_cast` | Array of `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH, IS_DOCUMENTARY, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `IMDB_RATING_WEIGHTED DESC`. Rows whose host movie is non-documentary (`IS_DOCUMENTARY != 1`) and whose `CAST_CHARACTER` is one of `Self`, `Himself`, `Herself`, `(archive footage)`, `Self (archive footage)`, `Self (archive footage) (uncredited)`, or `Self (uncredited)` are excluded |
| `movie_crew` | Array of `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH, IS_DOCUMENTARY, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `IMDB_RATING_WEIGHTED DESC` |
| `series_cast` | Array of `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `IMDB_RATING_WEIGHTED DESC` (no self-appearance filter on the series side — text-to-SQL behavior is symmetric) |
| `series_crew` | Array of `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `IMDB_RATING_WEIGHTED DESC` |
| `groups` | Array of `{ ID_GROUP, GROUP_NAME, GROUP_TYPE, PROFILE_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `deaths` | Array of `{ ID_DEATH, DEATH_NAME, DEATH_TYPE, PROFILE_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `awards` | Array of `{ ID_AWARD, AWARD_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `nominations` | Array of `{ ID_NOMINATION, NOMINATION_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `portraits` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_PERSON_IMAGE` where `TYPE_IMAGE = 'profile'`, ordered by `DISPLAY_ORDER` |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the person's `ID_WIKIDATA`, filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the person's `ID_WIKIDATA`, filtered to `LANG = 'en'` and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT`. Empty when `ID_WIKIDATA` is NULL |
| `videos` | Array of Wikidata-sourced videos (`SOURCE='wikidata'`) for this person from `T_WC_WIKIDATA_MEDIA_RESOURCE` joined to `T_WC_WIKIDATA_MEDIA_RESOURCE_URL`, filtered to `RESOURCE_KIND='video'`, `IS_ACTIVE=1`, `DELETED=0`. TMDb does not store person-level videos. Ordered by `IS_PREFERRED_RESOURCE DESC, SOURCE_PRIORITY ASC`. Field shape matches the `/movies/{id}` `videos` row (TMDb-only fields like `OFFICIAL` / `DAT_PUBLISHED` / `DISPLAY_ORDER` are always null here) |

Base person fields currently include `ID_PERSON`, `PERSON_NAME`, `ID_IMDB`, `ID_WIKIDATA`, `BIOGRAPHY`, `BIRTH_YEAR`, `BIRTH_MONTH`, `BIRTH_DAY`, `DEATH_YEAR`, `DEATH_MONTH`, `DEATH_DAY`, `GENDER`, `PROFILE_PATH`, `COUNTRY_OF_BIRTH`, `POPULARITY`, `KNOWN_FOR_DEPARTMENT`, `TIM_CREDITS_DOWNLOADED`, `DAT_CREAT`, `TIM_UPDATED`, `WIKIDATA_NAME`, `ALIASES`, and `INSTANCE_OF`.

##### `GET /companies/{id}`

Returns all `T_WC_T2S_COMPANY` fields for `ID_COMPANY`, plus:

| Field | Shape |
|---|---|
| `movies` | Array of `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH }`, ordered by `IMDB_RATING_WEIGHTED DESC` |
| `series` | Array of `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH }`, ordered by `IMDB_RATING_WEIGHTED DESC` |

Base company fields currently include `ID_COMPANY`, `COMPANY_NAME`, `DESCRIPTION`, `LOGO_PATH`, `HEADQUARTERS`, `ORIGIN_COUNTRY`, `ID_PARENT`, `TIM_CREDITS_DOWNLOADED`, `DAT_CREAT`, `TIM_UPDATED`, `MOVIE_COUNT`, `SERIE_COUNT`, `IMDB_RATING_WEIGHTED`, and `POPULARITY`.

##### `GET /networks/{id}`

Returns all `T_WC_T2S_NETWORK` fields for `ID_NETWORK`, plus:

| Field | Shape |
|---|---|
| `series` | Array of `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH }`, ordered by `IMDB_RATING_WEIGHTED DESC` |

Base network fields currently include `ID_NETWORK`, `NETWORK_NAME`, `LOGO_PATH`, `ORIGIN_COUNTRY`, `TIM_CREDITS_DOWNLOADED`, `DAT_CREAT`, and `TIM_UPDATED`.

##### `GET /collections/{id}`, `/topics/{id}`, `/lists/{id}`, and `/movements/{id}`

These endpoints return all fields from their primary entity table, plus member movies and series:

| Endpoint | Primary fields include | Embedded arrays |
|---|---|---|
| `/collections/{id}` | `ID_T2S_COLLECTION`, `ID_RECORD`, `COLLECTION_NAME`, `COLLECTION_NAME_FR`, `OVERVIEW`, `COLLECTION_SOURCE`, `COLLECTION_TYPE`, `MOVIE_COUNT`, `SERIE_COUNT`, `POSTER_PATH`, `WIKIPEDIA_IMAGE_PATH`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `POPULARITY` | `movies` and `series` arrays of `{ ID_MOVIE/ID_SERIE, MOVIE_TITLE/SERIE_TITLE, DAT_RELEASE/DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }`, ordered by `DISPLAY_ORDER` |
| `/topics/{id}` | `ID_TOPIC`, `TOPIC_NAME`, `TOPIC_TYPE`, `TOPIC_SOURCE`, `LANG`, `ID_RECORD`, `MOVIE_COUNT`, `SERIE_COUNT`, `POSTER_PATH`, `WIKIPEDIA_IMAGE_PATH`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `POPULARITY` | `movies` and `series` arrays of `{ ID_MOVIE/ID_SERIE, MOVIE_TITLE/SERIE_TITLE, DAT_RELEASE/DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }`, ordered by `DISPLAY_ORDER` |
| `/lists/{id}` | `ID_T2S_LIST`, `ID_RECORD`, `LIST_NAME`, `LIST_NAME_FR`, `OVERVIEW`, `LIST_SOURCE`, `LIST_TYPE`, `MOVIE_COUNT`, `SERIE_COUNT`, `POSTER_PATH`, `WIKIPEDIA_IMAGE_PATH`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `POPULARITY` | `movies` and `series` arrays of `{ ID_MOVIE/ID_SERIE, MOVIE_TITLE/SERIE_TITLE, DAT_RELEASE/DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }`, ordered by `DISPLAY_ORDER` |
| `/movements/{id}` | `ID_MOVEMENT`, `ID_RECORD`, `MOVEMENT_NAME`, `MOVEMENT_NAME_FR`, `OVERVIEW`, `MOVEMENT_SOURCE`, `MOVEMENT_TYPE`, `MOVIE_COUNT`, `SERIE_COUNT`, `POSTER_PATH`, `WIKIPEDIA_IMAGE_PATH`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `POPULARITY` | `movies` and `series` arrays of `{ ID_MOVIE/ID_SERIE, MOVIE_TITLE/SERIE_TITLE, DAT_RELEASE/DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }`, ordered by `DISPLAY_ORDER` |

All four endpoints also return `wikipedia_images` and `wikipedia_content` arrays — see the `/movies/{id}` table for their full row shapes.

##### `GET /technicals/{id}`

Returns all `T_WC_T2S_TECHNICAL` fields for `ID_TECHNICAL`, plus:

| Field | Shape |
|---|---|
| `movies` | Array of `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }` from `T_WC_T2S_MOVIE_TECHNICAL` joined to `T_WC_T2S_MOVIE`, ordered by `DISPLAY_ORDER ASC, IMDB_RATING_WEIGHTED DESC` (junction `DISPLAY_ORDER` is mostly NULL for auto-ingested technical attributes, so the rating tiebreaker effectively rules — best-rated movies surface first) |
| `siblings` | Array of `{ ID_TECHNICAL, DESCRIPTION, DESCRIPTION_FR, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY, MOVIE_COUNT }` of other technicals sharing the same `TECHNICAL_TYPE`, ordered by `MOVIE_COUNT DESC`. Enables navigation between related technical formats (e.g. from `technicolor` to the other `color_technology` rows like `deluxe`, `eastmancolor`, `metrocolor`) |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the technical's `ID_WIKIDATA`, filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the technical's `ID_WIKIDATA`, filtered to `LANG = 'en'` and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT`. Empty when `ID_WIKIDATA` is NULL |

Base technical fields currently include `ID_TECHNICAL`, `ID_RECORD`, `ID_WIKIDATA`, `DESCRIPTION`, `DESCRIPTION_FR`, `OVERVIEW`, `TECHNICAL_TYPE` (one of `sound_system`, `color_technology`, `film_technology`, `sound_technology`, `film_format`), `MOVIE_COUNT`, `SERIE_COUNT`, `WIKIPEDIA_IMAGE_PATH`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, and `POPULARITY`. No `series` array is returned because `T_WC_T2S_SERIE_TECHNICAL` does not exist yet.

##### `GET /groups/{id}` and `/deaths/{id}`

These endpoints return all fields from their primary entity table, plus associated persons:

| Endpoint | Primary fields include | Embedded arrays |
|---|---|---|
| `/groups/{id}` | `ID_GROUP`, `ID_WIKIDATA`, `GROUP_NAME`, `GROUP_NAME_FR`, `OVERVIEW`, `GROUP_SOURCE`, `GROUP_TYPE`, `PERSON_COUNT`, `PROFILE_PATH`, `WIKIPEDIA_IMAGE_PATH`, `POPULARITY` | `persons`: array of `{ ID_PERSON, PERSON_NAME, POPULARITY, PROFILE_PATH, DISPLAY_ORDER }`, ordered by `DISPLAY_ORDER` |
| `/deaths/{id}` | `ID_DEATH`, `ID_WIKIDATA`, `DEATH_NAME`, `DEATH_NAME_FR`, `OVERVIEW`, `DEATH_SOURCE`, `DEATH_TYPE`, `PERSON_COUNT`, `PROFILE_PATH`, `WIKIPEDIA_IMAGE_PATH`, `POPULARITY` | `persons`: array of `{ ID_PERSON, PERSON_NAME, POPULARITY, PROFILE_PATH, DISPLAY_ORDER }`, ordered by `DISPLAY_ORDER` |

Both endpoints also return `wikipedia_images` and `wikipedia_content` arrays — see the `/movies/{id}` table for their full row shapes.

##### `GET /awards/{id}` and `/nominations/{id}`

These endpoints return all fields from their primary entity table, plus associated movies, series, and persons:

| Endpoint | Primary fields include | Embedded arrays |
|---|---|---|
| `/awards/{id}` | `ID_AWARD`, `ID_WIKIDATA`, `AWARD_NAME`, `AWARD_NAME_FR`, `OVERVIEW`, `AWARD_SOURCE`, `AWARD_TYPE`, `MOVIE_COUNT`, `SERIE_COUNT`, `PERSON_COUNT`, `POSTER_PATH`, `WIKIPEDIA_IMAGE_PATH`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `POPULARITY` | `movies`: `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }`; `series`: `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }`; `persons`: `{ ID_PERSON, PERSON_NAME, POPULARITY, PROFILE_PATH, DISPLAY_ORDER }`; all ordered by `DISPLAY_ORDER` |
| `/nominations/{id}` | `ID_NOMINATION`, `ID_WIKIDATA`, `NOMINATION_NAME`, `NOMINATION_NAME_FR`, `OVERVIEW`, `NOMINATION_SOURCE`, `NOMINATION_TYPE`, `MOVIE_COUNT`, `SERIE_COUNT`, `PERSON_COUNT`, `POSTER_PATH`, `WIKIPEDIA_IMAGE_PATH`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `POPULARITY` | `movies`: `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }`; `series`: `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, DISPLAY_ORDER }`; `persons`: `{ ID_PERSON, PERSON_NAME, POPULARITY, PROFILE_PATH, DISPLAY_ORDER }`; all ordered by `DISPLAY_ORDER` |

Both endpoints also return `wikipedia_images` and `wikipedia_content` arrays — see the `/movies/{id}` table for their full row shapes.

##### `GET /locations/{wikidata_id}`

Returns all `T_WC_T2S_ITEM` fields for the location `ID_WIKIDATA`, for example `Q90`, plus movies and series where the location is linked through Wikidata property `P840` (narrative location) or `P915` (filming location).

| Field | Shape |
|---|---|
| `movies` | Array of `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH, ID_PROPERTY }`, ordered by `IMDB_RATING_WEIGHTED DESC` |
| `series` | Array of `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, ID_PROPERTY }`, ordered by `IMDB_RATING_WEIGHTED DESC` |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on `ID_WIKIDATA` (the route parameter), filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC` |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on `ID_WIKIDATA` (the route parameter), filtered to `LANG = 'en'` and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT` |

Base location fields currently include `ID_WIKIDATA`, `ITEM_LABEL`, `DESCRIPTION`, `INSTANCE_OF`, and `WIKIPEDIA_IMAGE_PATH`.

### Client handling for quota / rate-limit errors

When an upstream LLM provider rejects a request because of quota exhaustion or temporary rate limiting, the API returns the failure in the normal JSON response and also exposes structured retry metadata.

Typical retryable response pattern:

```json
{
  "error": "LLM API call failed: 429 RESOURCE_EXHAUSTED ... Please retry in 27s.",
  "error_code": "429",
  "is_retryable": true,
  "retry_after_seconds": 27.0,
  "provider": "google"
}
```

Recommended client behavior:

- If `is_retryable` is `true`, do not immediately spam retries.
- If `retry_after_seconds` is present, wait at least that many seconds before retrying.
- Add a small safety buffer on top of `retry_after_seconds` because provider quota windows are often rolling.
- Retry the same request with the same payload after the wait period.
- Use a capped retry policy so clients do not loop forever.
- If `is_retryable` is `false`, treat the response as a normal failure and surface or handle `error` directly.

Practical notes:

- The API may still return HTTP 200 with a populated `error` field for provider-side LLM failures; clients should inspect the JSON body, not only the HTTP status code.
- `provider` helps clients log or route provider-specific retry policy decisions.
- For batch evaluators or agents, serializing requests and honoring `retry_after_seconds` is strongly recommended when using quota-constrained models such as direct Google Gemma 4.

### 🎬 Movie Queries
- "I would like all movies directed by William Friedkin"
- "List the movies from Yasujirō Ozu's Noriko trilogy"
- "Movies with Humphrey Bogart and Lauren Bacall"
- "The Big Lebowski"
- "List all color movies with Humphrey Bogart"
- "The Killer movie directed by John Woo"
- "50 most popular movies in Persian language"
- "List the 50 most popular movies from the 50s"
- "Best rated Finnish movies on IMDB"
- "Best rated Argentine movies"
- "Top 100 best movies according to IMDB"
- "Movies with Clint Eastwood directed by Sergio Leone"
- "Movies having a Philip Marlowe character"
- "Films dont un des personnages s'appelle Antoine Doinel"
- "Movies with costumes created by Edith Head" 
- "Movie adaptations of Charles Dickens books"
- "List all posters of the movie The Big Lebowski"
- "List all polish posters of the movie The Big Lebowski"
- "List all movies in Technicolor released in 1967"
- "List all movies in CinemaScope released in 1960"

### 👥 People & Cast Queries
- "I'm looking for all actors in The Big Lebowski movie"
- "I'm looking for all actors in The Big Lebowski movie in casting order"
- "Who are the actors in The Big Lebowski movie?"
- "50 most popular directors"
- "Quelles sont les actrices du film The Big Sleep de 1946"
- "Documentary movies about Sergio Leone"
- "List all pictures of Humphrey Bogart"

### 🏢 Companies & Collections
- "List all collections with exactly 3 movies"
- "What are the French production companies?"

### 🎭 Genre & Language Queries
- "French New Wave movies"
- "Movies in Persian language"
- "Finnish movies"
- "Argentine movies"
- "Documentary movies directed in 2024"
- "Quels sont tous les genres de films ?"

### 🏆 Special Collections
- "Criterion Collection movies"
- "Movies from [specific trilogy name] trilogy"
- "Classic film noir movies"

### 🔍 Advanced Filtering
- "Silent movies released after 1999"
- "Movies from the [specific decade]s"
- "Movies with IMDB rating above [rating]"
- "Movies by production country"
- "Movies by original language"

### 📊 Statistical Queries
- "Top 100 highest rated movies"
- "Most popular movies by decade"
- "Directors with the most movies"
- "Most prolific actors"

### 📺 TV Series Queries
- "TV series created by David Lynch"
- "Most popular Netflix original series"
- "British crime series from the 2010s"
- "Anime series with highest ratings"
- "Documentary series about nature"
- "Comedy series from the 90s"
- "Series starring Bryan Cranston"
- "List all posters of the serie Game of Thrones"

### 🎥 Video & Media Queries
- "List all trailers for The Big Lebowski"
- "Show me videos for the movie Inception"
- "Find clips from Breaking Bad series"
- "Videos and trailers for Dune"
- "Behind the scenes videos for The Dark Knight"

### 🎭 Character Queries (New in v1.1.14)
- "Movies featuring James Bond"
- "Films with Sherlock Holmes as a character"
- "Movies with R2-D2"
- "Series featuring Hamlet"
- "All movies with a Philip Marlowe character"

### 🌍 Location Queries (New in v1.1.14)
- "Movies set in New York City"
- "Films taking place in South America"
- "Series set on the Moon"
- "Movies filmed in Gotham City"
- "Films set in Hollywood"

**Note**: Questions can be expressed in English or any language understood by the underlying LLM (currently OpenAI's models). The API can handle complex multi-criteria searches involving actors, directors, genres, years, ratings, characters, locations, and technical specifications for both movies and TV series. Video search capabilities allow finding trailers, clips, and other media content associated with movies and series.

## 🐳 Docker Deployment

The project includes a `Dockerfile` for containerized deployment. **Secrets are never baked into the image** — they are injected at runtime via `--env-file` from a host-managed env file kept outside the app source tree.

### Build

```bash
docker build -t fastapi-text2sql .
```

The build excludes `.env` from the build context (see `.dockerignore`), and the `Dockerfile` does not `COPY` it or declare it via `ENV`. Only non-sensitive defaults (e.g. `LD_LIBRARY_PATH`) live in the image.

### Run with `--env-file`

Keep the env file outside the app source tree, e.g. `/home/debian/docker/fastapi-text2sql-<color>/.env`, and pass it via `--env-file`:

```bash
docker run -d --rm --network="host" \
  --env-file /home/debian/docker/fastapi-text2sql-blue/.env \
  -v $(pwd):/app \
  --name fastapi-text2sql-blue \
  fastapi-text2sql-blue-app
```

The provided helper scripts ([restart-blue.sh](restart-blue.sh), [restart-green.sh](restart-green.sh)) already use this pattern — the host env files are expected at `/home/debian/docker/fastapi-text2sql-blue/.env` and `/home/debian/docker/fastapi-text2sql-green/.env` respectively.

### Why

- `.env` is listed in [.dockerignore](.dockerignore) so local environment files are excluded from the build context and cannot end up in image layers, build cache, or pushed registries.
- The `Dockerfile` never `COPY`s `.env` and never sets secrets via `ENV`.
- Runtime secrets flow only through `--env-file`, which sources from a path that is never part of any image.

## 📁 Project Structure

```
fastapi-text2sql/
├── main.py                  # FastAPI app, endpoint orchestration, entity detail endpoints, MCP server, DB/Chroma startup
├── text2sql.py              # Core text-to-SQL conversion, unified LLM dispatch (OpenAI/Anthropic/Gemini), retry helpers
├── entity.py                # Entity extraction, entity-resolution config loading, regex-validated placeholders, and placeholder resolution logic
├── closed_vocab.py          # Closed-vocabulary resolver (Movie_genre, Serie_genre, Technical_format, Status_name, Serie_type, Department_name) — DB-driven canonicals + JSON aliases + RapidFuzz typo tolerance
├── sql_cache.py             # SQL cache lookups and cache writes for exact/anonymized questions
├── auth.py                  # API key authentication middleware (multi-key support via API_KEYS)
├── logs.py                  # API usage logging (JSON log files in logs/ folder)
├── data_watcher.py          # File-system watcher for hot-reloading data/ files
├── language_family.py       # Latin vs non-Latin script detection for person name routing
├── rapidfuzz_query.py       # RapidFuzz + MariaDB/MySQL lexical matching utilities
├── cleanup.py               # Cache cleanup functions (ChromaDB and SQL)
├── RAPIDFUZZ.md             # RapidFuzz module documentation
├── MCP.md                   # MCP integration guide (tools, resources, deployment, Claude connector)
├── requirements.txt         # Python dependencies
├── Dockerfile               # Docker configuration for containerized deployment
├── .env.example             # Example environment variables template
├── .env                     # Environment variables (create from .env.example)
├── LICENSE                  # Project license file
├── restart-blue.sh          # Blue deployment restart script
├── restart-green.sh         # Green deployment restart script
├── data/                    # Hot-reloaded prompt templates and configuration
│   ├── entity_extraction.md                                          # Entity extraction prompt (hot-reloaded)
│   ├── text_to_sql.md                                                # Text2SQL prompt (hot-reloaded)
│   ├── complex_question.md                                           # Stronger model prompt (complex question simplification, hot-reloaded)
│   ├── entity_resolution.json                                        # Entity resolution configuration (embeddings + rapidfuzz, hot-reloaded)
│   └── closed_vocabularies.json                                      # Closed-vocabulary aliases for Movie_genre, Serie_genre, Technical_format, Status_name, Serie_type, Department_name (hot-reloaded)
├── doc/
│   └── sql/                 # Reference SQL dumps for canonical tables
│       └── T_WC_T2S_TECHNICAL.sql                                    # 56-row Technical_format canonical table
├── logs/                    # API usage logs with timing metrics (auto-created)
├── CLAUDE.md                # AI assistant guide for understanding the codebase
└── README.md                # This file
```

**Key Architecture Components:**
- **ChromaDB Integration**: Vector database for entity matching and similarity search with 15 entity collections (`persons`, `movies`, `series`, `companies`, `networks`, `topics`, `locations`, `groups`, `characters`, `lists`, `collections`, `deaths`, `awards`, `nominations`, `movements`) plus a separate `anonymizedqueries` cache collection
- **Multi-Level Caching**: SQL cache + embeddings cache for performance optimization with automatic cleanup
- **Entity Extraction**: `entity.py` handles GPT-powered entity recognition and anonymization for supported entity types
- **Unified LLM Dispatch**: `text2sql.py` routes to OpenAI (native SDK), Anthropic (native `anthropic` SDK), or Google Gemini (`google-generativeai`) based on model name
- **Reasoning Retry Helpers**: `text2sql.py` contains stronger-model calls and retry-question construction helpers
- **Endpoint Orchestration**: `main.py` coordinates request flow, recursive retry execution, and response/message merging
- **Entity Detail Endpoints**: 14 endpoints returning full entity data with embedded relations, each with usage logging
- **MCP Server**: FastMCP 2.x tools and resource exposed at `/mcp` for Claude clients (see `MCP.md`)
- **Blue/Green Deployment**: Automatic port selection based on API version (even: port 8000, odd: port 8001)
- **Processing Transparency**: Messages array tracks every processing step for debugging and analysis
- **Version Management**: Utility functions for version comparison and automatic cache cleanup

## 🔧 Configuration

### API Version
The API version is controlled by the `strapiversion` variable in `main.py`. Update this when making changes to the prompt templates.

### Prompt Templates
The system uses prompt templates stored in the `data/` folder. `text2sql.py` loads the Text2SQL and complex-question templates, and `entity.py` loads the entity-extraction template.

Files in the `data/` folder are hot-reloaded. If you modify `entity_extraction.md`, `text_to_sql.md`, `complex_question.md`, or `entity_resolution.json`, the running API automatically picks up the changes without requiring a restart.

Prompt template files are read using UTF-8 encoding so the application starts reliably on Windows even when prompt files contain non-ASCII characters.

The current prompt template is specifically designed for a **movie and TV series database** using MariaDB. It includes:

**🎬 Database Schema Coverage:**
- **Movies** (`T_WC_T2S_MOVIE`): Complete TMDB (The Movie Database) schema with detailed movie information
- **TV Series** (`T_WC_T2S_SERIE`): Full series data including episodes, seasons, and network information
- **People** (`T_WC_T2S_PERSON`, `T_WC_TMDB_PERSON_ALSO_KNOWN_AS`): Actors, directors, and crew members with their roles, relationships, and AKAs (used for non-Latin name resolution)
- **Companies** (`T_WC_T2S_COMPANY`): Production companies and studios
- **Networks** (`T_WC_T2S_NETWORK`): TV networks and streaming platforms
- **Topics** (`T_WC_T2S_TOPIC`): Curated themes and recurring-character topics (e.g., World War II, Christmas, Philip Marlowe)
- **Lists** (`T_WC_T2S_LIST`): Notable curated rankings, registries, and editorial lists (e.g., Sight and Sound, IMDb Top 250)
- **Awards** (`T_WC_T2S_AWARD`) and **Nominations** (`T_WC_T2S_NOMINATION`): Award wins and award nominations for movies, series, and persons
- **Collections** (`T_WC_T2S_COLLECTION`): Trilogies, named series of works, universes, and franchises (e.g., Dollars Trilogy, James Bond Collection, Star Wars, Marvel Cinematic Universe, Middle-Earth, Harry Potter movies)
- **Movements** (`T_WC_T2S_MOVEMENT`): Film movements and stylistic schools (Film Noir, French New Wave, etc.)
- **Groups** (`T_WC_T2S_GROUP`): Organizations, publications, and musical/comedy groups associated with persons
- **Deaths** (`T_WC_T2S_DEATH`): Causes and circumstances of persons' deaths
- **Locations** (`T_WC_T2S_ITEM` joined via `T_WC_WIKIDATA_ITEM_PROPERTY` with `ID_PROPERTY IN ('P840', 'P915')`): Wikidata-backed narrative or filming locations
- **Ratings**: IMDB ratings integration (raw and weighted)
- **Genres** (`T_WC_TMDB_GENRE` + `T_WC_TMDB_GENRE_LANG`): closed-vocabulary reference table; 27 canonical English names plus multilingual aliases (currently French, extensible to any LANG); used by both `T_WC_T2S_MOVIE_GENRE` and `T_WC_T2S_SERIE_GENRE` join tables (shared ID space)
- **Technical formats** (`T_WC_T2S_TECHNICAL`): closed-vocabulary reference table grouping 56 active rows by `TECHNICAL_TYPE` (sound systems, color/film/sound technologies, film formats — e.g. IMAX, Technicolor, CinemaScope, 35 mm, Dolby); joined to movies via `T_WC_T2S_MOVIE_TECHNICAL.ID_TECHNICAL`
- **Languages**: Multi-language support for titles and content
- **Images**: Poster, backdrop, and profile image management
- **Videos**: Trailer, clip, and behind-the-scenes video management
- **Cache** (`T_WC_T2S_CACHE`): Stores both exact and anonymized cached questions, partitioned by `API_VERSION` (`XXX.YYY.ZZZ`) and `UI_LANGUAGE`

**🎯 Key Features:**
- **Smart Title Matching**: Handles English, French, and original language titles
- **Movie Type Detection**: Distinguishes between movies, documentaries, and short films
- **Person Search**: Advanced cast and crew search with role-specific filtering
- **Criterion Collection**: Special handling for Criterion Collection movies
- **Color/B&W Detection**: Filters for color vs black-and-white films
- **Multi-language Support**: Proper handling of international titles
- **Default Sorting**: Intelligent sorting by release date, popularity, etc.

**📋 Query Rules:**
- Returns only valid SQL queries for successful conversions
- For unclear requests, sets the `error` field with an explanation and `ambiguous_question_for_text2sql` to `true`
- Includes comprehensive join conditions for complex relationships
- Handles edge cases like archive footage exclusions for cast searches
- Supports advanced filtering by decade, genre, rating, and more

**🎭 Specialized Collections:**
The template includes knowledge of famous film collections and trilogies like:
- Nouvelle Vague française
- Sight and Sound's Greatest Films
- Director-specific trilogies (Sergio Leone, Ingmar Bergman, etc.)
- Genre-specific collections (Film Noir, Neorealism, etc.)

This makes the API particularly powerful for film enthusiasts, researchers, and applications requiring sophisticated movie database queries.

## 🚀 Advanced Features

### Multi-Level Caching System

The API implements a sophisticated three-tier caching system for optimal performance:

#### 1. **Exact Question Cache (SQL Database)**
- Stores exact question-to-SQL mappings in `T_WC_T2S_CACHE` table
- Instant retrieval for previously asked questions
- Includes processing time metrics and API version tracking
- Supports both original and processed SQL queries

#### 2. **Anonymized Question Cache (SQL Database)**  
- Caches entity-extracted (anonymized) questions
- Enables reuse of SQL logic across similar questions with different entity values
- Example: "Movies with Brad Pitt" and "Movies with Tom Cruise" share the same anonymized pattern

#### 3. **Vector Embeddings Cache (ChromaDB)**
- Uses OpenAI's `text-embedding-3-large` model for semantic similarity
- Finds similar questions even with different wording
- Configurable similarity threshold (default: 0.15)
- Stores anonymized SQL queries in metadata for quick retrieval

### Automatic Cache Cleanup (Refactored in v1.1.13)

The system automatically cleans up cached data on startup to ensure optimal performance. In v1.1.13, cleanup functions were refactored into a separate `cleanup.py` module for better code organization.

#### **ChromaDB Embeddings Cleanup**
- Runs on application startup before the API accepts requests
- Cleans the `anonymizedqueries` collection in ChromaDB
- Removes embeddings from previous API versions
- Processes documents in batches of 1000 for efficient cleanup
- Provides console output showing progress and deletion counts

#### **SQL Cache Cleanup**
- Automatically deletes SQL cache entries matching the current API version
- Ensures fresh cache state for new version deployments
- Executes on startup: `DELETE FROM T_WC_T2S_CACHE WHERE API_VERSION = {current_version}`

**Impact**: Application startup may take slightly longer during cache cleanup operations, but this ensures optimal cache accuracy and prevents stale results from previous versions.

### Entity Extraction & Anonymization

The system intelligently extracts and replaces entities in natural language questions. The supported placeholder types are:

**Embeddings + RapidFuzz (config-driven via [data/entity_resolution.json](data/entity_resolution.json)):**

| Placeholder prefix | Description | Resolver |
|---|---|---|
| `Person_name` | Actors, directors, writers, composers, crew | RapidFuzz (Latin → `T_WC_T2S_PERSON`; non-Latin → AKA table with canonical resolution) |
| `Movie_title` | Movie titles (English/French/original) | Embeddings — `movies` collection |
| `Serie_title` | TV series titles (English/French/original) | Embeddings — `series` collection |
| `Company_name` | Production / distribution companies | Embeddings — `companies` collection |
| `Network_name` | TV networks / streaming platforms | Embeddings — `networks` collection |
| `Topic_name` | Themes, recurring-character collections | Embeddings — `topics` collection |
| `List_name` | Curated rankings / canons / registries | Embeddings — `lists` collection |
| `Award_name` | Named awards or recognitions | Embeddings — `awards` collection |
| `Nomination_name` | Named award nominations | Embeddings — `nominations` collection |
| `Collection_name` | Trilogies / named series of works / universes / franchises | Embeddings — `collections` collection |
| `Movement_name` | Film movements / stylistic schools | Embeddings — `movements` collection |
| `Group_name` | Organizations / publications / musical groups | Embeddings — `groups` collection |
| `Death_name` | Cause or circumstance of death | Embeddings — `deaths` collection |
| `Location_name` | Narrative / filming locations (Wikidata) | Embeddings — `locations` collection |
| `Character_name` | Movie / series character names | *(extracted but currently unresolved — raw fallback)* |

**Closed vocabulary ([closed_vocab.py](closed_vocab.py); DB-driven canonicals + JSON aliases hot-reloaded from [data/closed_vocabularies.json](data/closed_vocabularies.json); RapidFuzz typo tolerance, `score_cutoff = 85`):**

| Placeholder prefix | Description | Canonical source | Substitution |
|---|---|---|---|
| `Movie_genre` | Movie genre (TMDb /genre/movie/list) | `T_WC_TMDB_GENRE` filtered by `APPLIES_TO_MOVIE = 1` + matching rows of `T_WC_TMDB_GENRE_LANG` (multilingual aliases) | Integer `ID_GENRE` |
| `Serie_genre` | TV series genre (TMDb /genre/tv/list) | `T_WC_TMDB_GENRE` filtered by `APPLIES_TO_SERIE = 1` + matching rows of `T_WC_TMDB_GENRE_LANG` (multilingual aliases) | Integer `ID_GENRE` |
| `Technical_format` | Sound systems, color/film/sound tech, film formats | `T_WC_T2S_TECHNICAL` (56 active rows grouped by `TECHNICAL_TYPE`) | Integer `ID_TECHNICAL` |
| `Status_name` | Production lifecycle status | `DISTINCT STATUS` over `T_WC_T2S_MOVIE` ∪ `T_WC_T2S_SERIE` | Canonical string (e.g. `Released`, `Canceled`) |
| `Serie_type` | TV series type | `DISTINCT SERIE_TYPE` over `T_WC_T2S_SERIE` | Canonical string (e.g. `Documentary`, `Miniseries`) |
| `Department_name` | Crew department / known-for crew job (cast / acting excluded) | `DISTINCT CREW_DEPARTMENT` over `T_WC_T2S_PERSON_MOVIE` ∪ `T_WC_T2S_PERSON_SERIE` ∪ `DISTINCT KNOWN_FOR_DEPARTMENT` over `T_WC_T2S_PERSON`, all filtered with `NOT IN ('Actors', 'Acting')` | Canonical string (e.g. `Directing`, `Camera`, `Writing`) |

**Regex-validated ([entity.py](entity.py) `_REGEX_PLACEHOLDER_RULES`; malformed values are rejected and the placeholder is left unresolved):**

| Placeholder prefix | Pattern | Substitution kind | Target column |
|---|---|---|---|
| `Release_year` / `Birth_year` / `Death_year` | `\d{4}` | Bare integer | INT (`RELEASE_YEAR` / `BIRTH_YEAR` / `DEATH_YEAR`) |
| `TMDb_ID` / `Criterion_spine_ID` | `\d+` | Bare integer | INT primary keys (`ID_*`) |
| `IMDb_ID` / `IMDb_person_ID` | `tt\d+` / `nm\d+` | Quoted SQL string | VARCHAR `ID_IMDB` |
| `Wikidata_ID` / `Wikidata_property_ID` | `Q\d+` / `P\d+` | Quoted SQL string | VARCHAR `ID_WIKIDATA` / `ID_PROPERTY` |

**Process Flow:**
1. Extract entities from the user question using GPT-4o (or the configured `llm_model_entity_extraction`)
2. Replace entities with typed numbered placeholders (e.g., `{{Person_name1}}`, `{{Movie_title1}}`, `{{Award_name1}}`, `{{Group_name1}}`, `{{Release_year1}}`)
3. Check cache for the anonymized question pattern
4. Generate SQL if not cached
5. Resolve each placeholder to a real DB value using the per-prefix `search_list` in [data/entity_resolution.json](data/entity_resolution.json) (embeddings or RapidFuzz, with optional language-family gating)
6. Substitute resolved values back into `sql_query`, `justification`, and `answer`, using SQL-safe `''` quote escaping

The full pipeline is implemented in [entity.py](entity.py) (resolver dispatch, regex-validated placeholders, embeddings, RapidFuzz person resolution, generic fallback replacement) plus [closed_vocab.py](closed_vocab.py) (DB-driven closed-vocabulary lookups for `Movie_genre`, `Serie_genre`, `Technical_format`, `Status_name`, `Serie_type`, `Department_name` with RapidFuzz typo tolerance and JSON-driven alias layering).

If the user provides a disambiguation pattern like `<movie_title> (YYYY)`, entity extraction returns a `{{Release_yearN}}` placeholder alongside the `{{Movie_titleN}}` placeholder so the SQL can disambiguate same-titled films by release year.

### Vector Search Integration

ChromaDB collections for entity matching (15 entity collections + 1 cache collection — see [main.py:124-150](main.py#L124-L150)):
- `persons` — actor/director/crew embeddings (also used by RapidFuzz pipeline as a secondary signal)
- `movies` — movie title embeddings (English / French / original)
- `series` — TV series title embeddings (English / French / original)
- `companies` — production/distribution company embeddings
- `networks` — TV network / streaming platform embeddings
- `topics` — theme and recurring-character-collection embeddings
- `lists` — curated ranking / canon embeddings (e.g., Sight and Sound, IMDb Top 250)
- `awards` — named award embeddings
- `nominations` — named award-nomination embeddings
- `collections` — trilogy / named-work-series embeddings plus universe / franchise embeddings (e.g., Star Wars, Marvel Cinematic Universe, Middle-Earth)
- `movements` — film-movement / stylistic-school embeddings
- `groups` — organization / publication / musical-group embeddings
- `deaths` — cause-of-death embeddings
- `characters` — character-name embeddings (provisioned for upcoming use; not currently consumed by `entity_resolution.json`)
- `locations` — Wikidata-backed narrative / filming location embeddings
- `anonymizedqueries` — cached anonymized question patterns (disabled by default via `USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE = False`)

### Processing Transparency (Messages Array)

Each API response includes a detailed `messages` array that tracks every processing step:

**Example Messages:**
```json
"messages": [
  {"position": 1, "text": "Stripped whitespace and carriage return characters from question."},
  {"position": 2, "text": "Exact question cache hit used for SQL query."},
  {"position": 3, "text": "Entity extraction successful; question anonymized."},
  {"position": 4, "text": "Anonymized question cache hit found."},
  {"position": 5, "text": "Embeddings cache search completed in 0.05s."},
  {"position": 6, "text": "Executing SQL query: SELECT..."},
  {"position": 7, "text": "Query execution completed successfully."}
]
```

**Benefits:**
- **Debugging**: Easily identify which processing stage succeeded or failed
- **Performance Analysis**: See which steps take the most time
- **Cache Visibility**: Know which cache tier was used (exact, anonymized, or embeddings)
- **Transparency**: Understand exactly how your question was processed

### Blue/Green Deployment

The API supports Blue/Green deployment strategy for zero-downtime updates:

**How It Works:**
- **Even patch versions** (1.1.0, 1.1.2, 1.1.4, etc.) → **Blue environment** on port 8000
- **Odd patch versions** (1.1.1, 1.1.3, 1.1.5, etc.) → **Green environment** on port 8001
- Version controlled by `strapiversion` variable in `main.py`
- Automatic port selection on startup

**Deployment Scripts:**
- `restart-blue.sh`: Deploys to Blue environment (port 8000)
- `restart-green.sh`: Deploys to Green environment (port 8001)

**Benefits:**
- Zero-downtime deployments
- Easy rollback to previous version
- A/B testing capabilities
- Parallel version testing

### Logging
Log files are created in the `logs/` folder (via `logs.py`) for the following events:
- API startup (`start` event)
- Health check requests to `GET /` (`hello` event)
- Each processed `POST /search/text2sql` request (`text2sql_post` event)
- Each entity detail endpoint request (`movies`, `series`, `persons`, `companies`, `networks`, `collections`, `topics`, `lists`, `movements`, `technicals`, `groups`, `deaths`, `awards`, `nominations`, `locations`)
- Each successful hot-reload of a file in the `data/` folder (`data_hot_reload` event)

API request/response log files include:
- Timestamp
- Endpoint used
- API version
- Content hash
- Full request/response data
- Processing messages array

## 🔒 Security

- **API Key Authentication**: All endpoints require a valid API key via `X-API-Key` header; multiple keys supported via `API_KEYS` env var
- **MCP Bearer Token**: `/mcp` route is protected by a bearer token middleware (`MCP_API_KEY`); skipped when empty
- **Environment Variables**: Sensitive data like LLM API keys are stored in environment variables
- **Request Logging**: All API usage is logged for monitoring and debugging

## 🐛 Troubleshooting

### Common Issues

1. **Missing OpenAI API Key**
   - Ensure your `.env` file contains a valid `OPENAI_API_KEY`
   - Check that your OpenAI account has sufficient credits

2. **Authentication Errors**
   - Verify you're sending the correct API key in the `X-API-Key` header
   - Ensure `Content-Type: application/json` is set for POST requests

3. **Database Connection Issues**
   - Verify database credentials in `.env` file
   - Ensure MariaDB/MySQL server is running and accessible
   - Check that the database contains the required tables (`T_WC_T2S_CACHE`, etc.)

4. **ChromaDB Connection Issues**
   - Ensure ChromaDB server is running on the configured host/port
   - Check `CHROMADB_HOST` and `CHROMADB_PORT` in `.env` file
   - Verify ChromaDB collections are properly initialized

5. **Entity Extraction Failures**
   - The system includes fallback mechanisms for malformed OpenAI responses
   - Check logs for JSON parsing errors and API response issues
   - Entity extraction will fall back to original question if extraction fails

6. **SQL Escaping Issues**
   - The system now properly handles single quotes in movie titles (e.g., "The King's Speech")
   - Uses proper SQL escaping (`''` instead of `\'`) for parameterized queries

7. **Memory Issues**
   - The application monitors system memory and will display usage on startup
   - Large embedding operations may require additional memory

8. **Cache Performance**
   - Monitor cache hit rates in response fields (`cached_exact_question`, etc.)
   - Clear ChromaDB collections if embeddings become stale
   - Check `T_WC_T2S_CACHE` table for SQL cache entries

9. **Prompt File Encoding Issues on Windows**
   - Prompt templates are loaded with UTF-8 encoding
   - If you modify prompt files, keep them saved as UTF-8 to avoid `UnicodeDecodeError` during module import or application startup

10. **Missing RapidFuzz Dependency**
   - `entity.py` imports `rapidfuzz_query.py`, which depends on the `rapidfuzz` package
   - If startup fails with `ModuleNotFoundError: No module named 'rapidfuzz'`, install dependencies from `requirements.txt` in the active Python environment

### Logs
Check the `logs/` folder for detailed request/response logs with comprehensive timing metrics if you encounter issues. Each log file includes:
- Entity extraction processing time
- Text2SQL conversion time  
- Embeddings processing time
- Query execution time
- Cache hit/miss information

## 📝 API Response Format

All successful text2sql requests return a comprehensive response with:

**Core Fields:**
- `question`: The original natural language question
- `question_hashed`: SHA256 hash of the question for pagination/caching
- `sql_query`: The generated and optimized SQL query (with entities resolved)
- `sql_query_anonymized`: The SQL query with entity placeholders (new in v1.1.13)
- `justification`: Explanation or reasoning for the SQL query (if provided), with entities resolved
- `justification_anonymized`: The `justification` before entity de-anonymization
- `answer`: User-oriented plain-language description of what the query returns, in the requested `ui_language` (new in v1.1.15)
- `answer_anonymized`: The `answer` before entity de-anonymization (new in v1.1.15)
- `error`: Error message if query processing failed (e.g., the LLM's explanation when the question is ambiguous)
- `entity_extraction`: Full entity extraction dictionary from LLM (new in v1.1.13)
- `question_anonymized`: The anonymized version of the question with placeholders (new in v1.1.13)
- `result`: Array of query results with `index` and `data`
- `messages`: Array of processing step messages (`position` and `text`)

**Performance Metrics:**
- `entity_extraction_processing_time`: Time for entity extraction (seconds)
- `text2sql_processing_time`: Time for SQL generation (seconds)
- `embeddings_processing_time`: Time for vector search operations (seconds)
- `embeddings_cache_search_time`: Time for embeddings cache lookup (seconds)
- `query_execution_time`: Time for SQL execution (seconds)
- `total_processing_time`: Total request processing time (seconds)

**Pagination:**
- `page`: Current page number
- `limit`: Records per page
- `offset`: Current offset
- `rows_per_page`: Configured page size (default: 50)
- `llm_defined_limit`/`llm_defined_offset`: LLM-specified pagination (if any)

**Cache Indicators:**
- `cached_exact_question`: Whether exact question was found in cache
- `cached_anonymized_question`: Whether anonymized question was cached
- `cached_anonymized_question_embedding`: Whether similar question found via embeddings
- `ambiguous_question_for_text2sql`: Whether question was too ambiguous for SQL generation

**Configuration & Metadata:**
- `llm_model_entity_extraction`: LLM model actually used for entity extraction
- `llm_model_text2sql`: LLM model actually used for text-to-SQL conversion
- `llm_model_complex`: LLM model **configured** for complex-question resolution / stronger-model retry (does not by itself indicate the retry path was taken)
- `complex_model_used` (bool, new in v1.1.15): Whether the stronger model was actually invoked during the request — `true` only when one of the four complex-retry code paths fired (text2sql error, SQL execution error, zero-row result on page 1, or single-cell zero-count direct answer)
- `ui_language` (new in v1.1.15): Language code used for the `answer` field and as part of the cache key
- `api_version`: Current API version (e.g., "1.1.16")

### Recent updates within v1.1.16

The following changes ship under v1.1.16. They align the entity detail endpoints with the text-to-SQL prompt spec and add a directional sorting rule to remove ambiguity in cross-entity person queries:

- **Entity-detail response shape aligned with the text-to-SQL spec**: the response-dict key order in `GET /movies/{id}`, `GET /series/{id}`, and `GET /persons/{id}` now mirrors the "Default Sorting" section of `data/text_to_sql.md` (cast/crew last for movies and series; spec'd lists in spec order; non-spec'd "extras" kept at their relative position). `GET /movies/{id}` and `GET /series/{id}` gained a `lists` array (curated `T_WC_T2S_LIST` membership, ordered by `DISPLAY_ORDER`). Internal `ORDER BY` clauses added where the spec required them (`companies` by `ID_COMPANY`; `networks` by `ID_NETWORK`).
- **Self-appearance cast filter (movies only)**: the `cast` array in `GET /movies/{id}` and the `movie_cast` array in `GET /persons/{id}` now drop rows whose `CAST_CHARACTER` is `Self`, `Himself`, `Herself`, `(archive footage)`, `Self (archive footage)`, `Self (archive footage) (uncredited)`, or `Self (uncredited)` — applied per-row only when the host movie is non-documentary (`IS_DOCUMENTARY != 1`), matching `data/text_to_sql.md` rules at lines 850-851. Series queries are deliberately unchanged so the endpoint mirrors text-to-SQL behavior, which does not apply the exclusion to series cast.
- **Text-to-SQL prompt — directional ORDER BY rules for cross-entity person queries**: added two explicit rules in the "Default Sorting" section so the LLM emits `ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC` (and the series analog) for questions like "list movies starring X", instead of incorrectly reusing `T_WC_T2S_PERSON_MOVIE.DISPLAY_ORDER ASC` (which is correct only for the reverse direction, persons-for-a-given-movie).
- **Coherence guidance for coding agents**: [AGENTS.md](AGENTS.md) now contains a dedicated "Text-to-SQL ↔ entity endpoint coherence" section listing the four drift categories (filter predicates, sort order, included list keys, result columns) so agents surface any divergence between `data/text_to_sql.md` and the hand-written endpoint SQL to the user instead of silently patching either side.

### Recent updates within v1.1.15

The following changes shipped inside the v1.1.15 deployment. They reorganize entity resolution into four well-defined categories and remove duplicated canonical lists from the prompt templates:

- **Closed-vocabulary resolver layer ([closed_vocab.py](closed_vocab.py))**: introduced a unified DB-driven canonical loader (`closed_vocab.init(connection)` runs once at startup) plus a JSON-driven alias loader (hot-reloaded via `data_watcher`). Powers `Genre_name`, `Technical_format`, `Status_name`, and `Serie_type` resolution through a single `_resolve_closed_vocab()` matcher (RapidFuzz, `score_cutoff = 85`, `margin = 5`). Hard-coded `MOVIE_GENRE_NAME_TO_ID` / `SERIE_GENRE_NAME_TO_ID` dicts removed from `entity.py`; movie-vs-series context dispatch retired (both join tables share the same `T_WC_TMDB_GENRE` ID space).
- **`Technical_format` placeholder added**: new closed-vocabulary entity backed by the `T_WC_T2S_TECHNICAL` reference table (56 active rows: sound systems, color/film/sound technologies, film formats — IMAX, Technicolor, CinemaScope, 35 mm, Dolby, etc.). Resolver substitutes the integer `ID_TECHNICAL` into `T_WC_T2S_MOVIE_TECHNICAL.ID_TECHNICAL`. The "do not extract technical formats" rule was lifted from `data/entity_extraction.md`.
- **Multilingual genre aliases via DB**: `T_WC_TMDB_GENRE_LANG(id, LANG, name)` is now read at startup alongside `T_WC_TMDB_GENRE`; adding rows for any new LANG (de, es, ja, …) auto-extends genre matching with no code change.
- **`Status_name` and `Serie_type` placeholders added**: closed-vocabulary string substitution for production lifecycle status (`Released`, `Canceled`, `In Production`, `Post Production`, `Planned`, `Rumored`) and TV series type (`Documentary`, `Miniseries`, `News`, `Reality`, `Scripted`, `Talk Show`, `Video`).
- **Hot-reloaded alias config (`data/closed_vocabularies.json`)**: per-entity alias dictionaries for typos, format variants, and multilingual synonyms (e.g. `35mm` → `35 mm`, `scifi` → `Science Fiction`, `cancelled` → `Canceled`, `documentaire` → `Documentary`). Edits picked up within ~5 seconds without restart.
- **Regex-validated placeholder layer ([entity.py](entity.py) `_REGEX_PLACEHOLDER_RULES`)**: unified dispatcher covering 9 placeholders — `Release_year`, `Birth_year`, `Death_year` (`\d{4}` numeric), `TMDb_ID`, `Criterion_spine_ID` (`\d+` numeric), `IMDb_ID` / `IMDb_person_ID` (`tt\d+` / `nm\d+` quoted strings), `Wikidata_ID` / `Wikidata_property_ID` (`Q\d+` / `P\d+` quoted strings). Malformed values are now rejected at resolution time (placeholder left unresolved → marks question ambiguous), tightening defense against LLM hallucinations on identifier-style entities.
- **`Birth_year` / `Death_year` placeholders added**: 4-digit year extraction for person filtering ("actors born in 1962", "directors who died in 1980"), reusing the `Release_year` substitution shape.
- **Prompt deduplication (Option 1)**: the 56-row Technical_format ID:DESCRIPTION list and the 27 + 18 Genre Reference blocks have been removed from `data/text_to_sql.md`. The LLM now emits placeholders (`{{Genre_nameN}}`, `{{Technical_formatN}}`) and the resolver substitutes the integer ID at runtime — single source of truth for canonicals = the database. Saves ~500 prompt tokens per request and eliminates drift between prompt and DB.
- **`doc/sql/T_WC_T2S_TECHNICAL.sql`**: reference dump of the Technical_format canonical table is now versioned alongside the code.

### New Features in v1.1.15

- **Localized user-oriented `answer`**: every successful response now includes an `answer` field — a plain-language sentence describing what the query returns, written in the language specified by `ui_language` (default `"en"`). The answer is generated alongside the SQL using the same LLM, preserves entity placeholders during generation, and is de-anonymized in lockstep with `sql_query` and `justification`. `ui_language` is also part of the cache key so the same question cached in different languages keeps separate entries.
- **`answer_anonymized`** companion field exposes the placeholder version for cache reuse and debugging.
- **`UI_LANGUAGE` cache column**: cache reads and writes filter by language (with `OR UI_LANGUAGE IS NULL` for backward compatibility).
- **New first-class entities**: `List_name`, `Award_name`, `Nomination_name`, `Collection_name`, `Movement_name`, `Group_name`, `Death_name` — each with a dedicated `T_WC_T2S_*` table, ChromaDB collection, embedding-based resolver in `entity_resolution.json`, and `/`<entity>`/{id}` REST + MCP detail endpoint. Topics no longer overload these concepts.
- **Single-cell zero-count direct answer**: when the SQL returns exactly one row / one column with value `0` and `complex_question_processing=true`, the stronger model is asked for the correct scalar; the answer is wrapped in a synthetic `SELECT {value} AS '{question}' FROM DUAL`, executed, and cached so subsequent calls bypass the stronger model.
- **`complex_model_used` response flag**: tells callers whether the stronger model was actually invoked during the request (independent of the configured `llm_model_complex` value). Useful for evaluation pipelines and cost analysis.
- **`f_build_retry_question_from_reasoning()`**: deterministically composes the retry question from the stronger model's structured reasoning output (typed entities + years), removing earlier free-text drift on retries.

### New Features in v1.1.14

- **Character Name Entity Extraction**: New entity type for extracting movie/series character names (e.g., "James Bond", "Sherlock Holmes", "R2-D2") with dedicated `characters` ChromaDB collection
- **Location Name Entity Extraction**: New entity type for extracting narrative or filming locations (e.g., "New York City", "Gotham City", "South America") with dedicated `locations` ChromaDB collection
- **Groups Collection**: New `groups` ChromaDB collection for group/collection-based entity matching

### Recent Refactor Updates

- **Lighter `main.py`**: request handling now delegates entity extraction/resolution and SQL cache operations to dedicated modules
- **New `entity.py` module**: centralizes entity extraction, entity-resolution config loading, embeddings/RapidFuzz resolution, and placeholder substitution
- **`sql_cache.py` module**: centralizes SQL cache lookup and write logic for exact and anonymized questions
- **Reasoning helpers in `text2sql.py`**: complex-question resolution and retry-question construction now live alongside the LLM helper code
- **API-selectable complex model**: clients can now provide `llm_model_complex` to choose the model used for complex-question resolution retries
- **stronger-model compatibility handling**: complex-question resolution now uses model-compatible temperature settings, including `temperature=1` for `o1*`/`o3*` models
- **Retry message transparency**: retry messages now include the selected complex-question model name
- **Original complex-question cache persistence**: after a successful stronger-model retry, the original complex question is also stored in SQL cache with the final SQL returned by the retried flow
- **Language-family-based person resolution**: `entity.py` now uses `guess_language_family()` so Latin person names search `T_WC_T2S_PERSON`, while non-Latin names keep the AKA-table resolution flow through `T_WC_TMDB_PERSON_ALSO_KNOWN_AS`
- **Person-name justification formatting**: when a person is matched through an AKA entry and resolved to a canonical name, SQL uses the canonical value while justification shows `AKA (Canonical)` only when the AKA differs from the canonical name

### New Features in v1.1.13

- **Enhanced Response Fields**: Added `sql_query_anonymized`, `entity_extraction`, and `question_anonymized` to the API response for better transparency into the query processing pipeline
- **Justification Caching**: The `justification` field is now stored in both SQL cache and ChromaDB embeddings cache for retrieval on cache hits
- **Improved Ambiguous Question Handling**: Ambiguous questions are now handled via the `error` response field instead of the previous `##AMBIGUOUS##` marker approach, providing clearer error messages
- **Cleanup Module Refactoring**: Cleanup functions moved to separate `cleanup.py` module for better code organization and maintainability

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is open source. Please check the repository for license details.

## 🔗 Links

- **Repository**: https://github.com/vaugouin/FastAPI-Text2SQL
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **OpenAI API**: https://platform.openai.com/docs/
- **Anthropic API**: https://docs.anthropic.com/
- **Google Gemini API**: https://ai.google.dev/docs
- **FastMCP**: https://github.com/jlowin/fastmcp
- **MCP Integration Guide**: See `MCP.md` in this repository

---

**Current Version**: 1.1.16
**Last Updated**: 2026-05-11

**Note**: This API requires an active OpenAI API key to function. Make sure you have sufficient credits in your OpenAI account for the text-to-SQL conversions.

For detailed technical documentation and AI assistant guidance, see [CLAUDE.md](CLAUDE.md).
