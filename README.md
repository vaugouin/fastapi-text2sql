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
- **Picture-based search**: an optional `image_ref` on `/search/text2sql` turns a photo into a question. A poster, a frame or a Blu-ray sleeve is read by a vision model, the work or person it points at is identified with the clues that support each candidate, and the ordinary pipeline answers from there. A photo alone opens the entity's card, a photo with a question answers the question, a question about the picture itself is answered from the pixels with no catalogue query, and an image with nothing of cinema in it says so rather than guessing
- **MCP Server**: Remote MCP endpoint for Claude clients (web, desktop, mobile) via FastMCP 2.x
- **Entity Detail Endpoints**: 18 REST endpoints returning full entity data with embedded relations and usage logging, each accepting an optional `ui_language` parameter (`en`/`fr`) that returns fully localized, language-collapsed responses (see below)
- **Multi-API Key Support**: Comma-separated `API_KEYS` env var with legacy `API_KEY` fallback

### Advanced Features
- **Localized User-Oriented Answers (`ui_language`)**: Each response includes a plain-language `answer` field describing what the query returns, written in the language specified by `ui_language` (default `"en"`). The answer preserves entity placeholders during generation and is de-anonymized alongside the SQL and justification. `ui_language` is part of the cache key so that the same question cached in different languages gets separate entries.
- **Multi-Language Support**: Handles English, French, and original language titles for movies and series
- **Processing Transparency**: Detailed messages array showing each processing step
- **Configurable LLM Models**: one selector per LLM task, six in all: entity extraction, text-to-SQL conversion, answer-entity classification, complex-question escalation, the direct scalar answer, and the image reader
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

0a. **Vision pre-stage (only when `image_ref` is supplied)**
   - When the request carries an `image_ref` (the bare filename returned by `POST /uploads/vision`), the image is read **first** and turned into a question in words; everything below then runs unchanged on that question. Neither entity extraction nor SQL generation ever sees the image.
   - **A photo alone** yields the canonical identity question (`Movie Blade Runner released in 1982`), composed deterministically from the identified candidates by the same helper the complex-question retry uses. **A photo with a question** keeps the question and has the identified entity substituted into it (`who directed this film?` → `who directed the movie Blade Runner (1982)?`), so a relation question is answered instead of being flattened into an entity card.
   - **Three cases never reach the catalogue**, and none is an error: a question about the image itself (`what is written on this poster?`, answered from the pixels), an image with nothing of cinema in it, and an image the model could not read. All three return an `answer`, an empty `result` and no SQL.
   - The identification is cached on the **fingerprint of the image bytes** (the MD5 already carried by the `image_ref`) and the API version, so the same photo re-deposited costs nothing: `vision_model_used` comes back `false` and `vision_identification_processing_time` 0.0. Only the question-independent half is stored, so one row answers any later question about that photo.
   - Because the composed question is deterministic, **page 2 of a search born from an image is an ordinary paginated request**: the hash is taken on the composed question, with or without the `image_ref`.
   - Skipped on the complex-question retry re-entry. It is a pre-stage and not a recursive call, so a picture-based request still writes exactly **one** log file.

0b. **Bare-Identifier Fast Path (no LLM)**
   - Before any cache or LLM step, if the **whole trimmed question is just a self-identifying identifier** it is answered with a direct, indexed SQL lookup and the entire LLM pipeline (entity extraction + text-to-SQL + resolution) is skipped — a sub-millisecond, zero-token response.
   - Recognized forms (an optional leading `imdb` / `wikidata` keyword is tolerated, casing is normalized): `tt…` (IMDb title → looked up on `T_WC_T2S_MOVIE` then `T_WC_T2S_SERIE` by `ID_IMDB`; if it is instead a **season / episode** IMDb id, it is resolved through `T_WC_TMDB_SEASON` / `T_WC_TMDB_EPISODE` to its parent series, which is returned), `nm…` (IMDb person → `T_WC_T2S_PERSON.ID_IMDB`), `Q…` (Wikidata id → scanned across the `ID_WIKIDATA`-bearing entity tables in a fixed precedence, first match wins).
   - The response keeps the **same shape** as a normal `/search/text2sql` answer: `result_entity` is set, the entity's "Result Columns" are projected, and `sql_query` + `messages` show the direct lookup (there is **no** text-to-SQL LLM message in the trace). The projected columns are read from the **live, hot-reloaded** "Result Columns" section of `data/text_to_sql.md` (single source of truth — a static per-entity table in `main.py` is only a fallback), so the fast path stays in sync when that prompt section changes.
   - Deliberately **not** short-circuited (they fall through to the normal pipeline): bare integers (TMDb id / Criterion spine / year — ambiguous without a type word) and `P…` (a Wikidata *property*, not a returnable entity).

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
   - **Runs concurrently with step 6.** Resolution depends only on the extracted key/value pairs, never on the generated SQL, so its expensive half (`plan_entity_resolutions`) is started in a worker thread just before the text-to-SQL call and joined right after it. Only the substitution, step 7, waits for the SQL. Set `ENTITY_RESOLUTION_PARALLEL=0` for the strictly sequential path.
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
     - **Location names** (`{{Location_nameN}}`): embeddings on `t2slocations` collection, `T_WC_T2S_LOCATION.LOCATION_NAME` / `LOCATION_NAME_FR` (locations are linked to movies/series via `T_WC_T2S_MOVIE_LOCATION` / `T_WC_T2S_SERIE_LOCATION`, whose `LOCATION_ROLE` is `'narrative'` or `'filming'`).
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
   - Runs while step 5 resolves the entities in a worker thread: the model only ever sees `input_text_anonymized`, so the two branches are independent
   - Uses the prompt template from `data/` folder with comprehensive database schema
   - Files in `data/` are hot-reloaded, so prompt/config edits are picked up automatically without restarting the API
   - GPT-4o generates a SQL query based on the anonymized question pattern
   - **Best-effort interpretation**: The model always produces a SQL query even when the question is ambiguous; it never returns an error solely because of ambiguity
   - This is the core text-to-SQL task
   - **`result_entity` selection**: alongside the SQL, the model returns `result_entity` — the kind of row the user wants *listed* (`movie`, `serie`, `person`, `collection`, …). It drives the answer-entity guard below.
   - **Answer-entity guard (validated against the original question)**: the SELECT must project the entity the user actually asked for. Because the text-to-SQL step runs on the **anonymized** question, anonymizing a head-noun entity word can flip the apparent answer type — e.g. *"Which movie directors died in 2025?"* becomes *"Which movie `{{Department_name1}}` died in `{{Death_year1}}`?"*, which reads as a movie query and makes the model return movies instead of the directors. To catch this, the expected answer type is re-derived from the **original** (non-anonymized) question via a classification call (the strong model, default `gpt-4o`, so a filter phrase such as "in the Criterion collection" is not mistaken for the answer type), independently of the LLM's anonymized-derived `result_entity`. The classifier returns `unknown` when genuinely ambiguous, in which case the LLM's own `result_entity` is trusted. When the SELECT does not project the expected entity (this case, or the classic "actors of <movie>" projecting the movie instead of the persons), the step does **one** targeted regeneration with a correction hint, adopting the new query only if it actually fixes the projection. The classification runs only on a fresh generation (skipped on cache hits and on text-to-SQL errors), and UNION / multi-entity (`movie_serie` / `CONTENT_TYPE`) queries are left untouched. When the classifier agrees with `result_entity` — the common case — behavior is unchanged.

7. **Query De-anonymization**
   - Replace placeholders in the generated SQL query, justification, and answer with actual validated entity values
   - Pure string substitution (`apply_entity_resolutions`), microseconds of work: everything expensive already happened in step 5
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

   # Pipeline shape (all read at import time, so a change needs a restart)
   BKTREE_ENABLED=1               # BK-tree index for RapidFuzz matching
   ENTITY_RESOLUTION_PARALLEL=1   # 1: resolve entities while the SQL is being generated
   CACHE_EMPTY_RESULTS=0          # 0: never cache a query that returned 0 rows
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
Answers both halves of the question a Blue/Green deployment raises: is this instance ready, and which one is it. Requires the `X-API-Key` header like every other endpoint.

```json
{
  "message": "hello world! The universal answer is 42",
  "bktrees_ready": true,
  "api_version": "1.1.18"
}
```

`bktrees_ready` is `false` while the background BK-tree warm-up is still running; the API already serves requests, and RapidFuzz resolution lazily builds whatever tree it needs in the meantime.

`api_version` is the same value and format as the `api_version` field of a `/search/text2sql` response (raw `1.1.18`, never the zero-padded `001.001.018` used for cache keys). Since the colour of a deployment follows the parity of its patch number, this one field is enough to tell which colour a client just reached, with no token spent and no cache touched:

```bash
curl -s -H "X-API-Key: $KEY" http://<host>:8186/   # even patch -> Blue
curl -s -H "X-API-Key: $KEY" http://<host>:8187/   # odd patch  -> Green
```

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
  "llm_model_result_entity": "default",
  "llm_model_answer_single_value": "default",
  "llm_model_vision": "default",
  "image_ref": null,
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
- `llm_model_result_entity` (optional, str, default: "default"): LLM model for the answer-entity classifier, which decides from the **original** question what kind of thing the returned rows should be. Before FASTAPI-TEXT2SQL-232 this task was reachable only through its module default, so it could be neither priced nor moved.
- `llm_model_answer_single_value` (optional, str, default: "default"): LLM model asked for a direct scalar answer when the SQL came back as a single cell worth 0. Before -232 it borrowed `llm_model_complex`; the two share a caller but not a job, so they now have separate selectors and separate defaults.
- `llm_model_vision` (optional, str, default: "default"): LLM that reads the image when `image_ref` is supplied, the sixth and last task of the pipeline (FASTAPI-TEXT2SQL-114). `"default"` resolves to **`gpt-6-astra`**, not `gpt-4o`: this is the one task whose default is not the house model, because it is the model the feature was designed and tried on. Only the OpenAI families read images here (`gpt-4o`, the GPT-5.x line, `gpt-6-astra`); an Anthropic or Gemini name is refused with an explicit error rather than silently ignored.
- `image_ref` (optional, str): The bare filename returned by `POST /uploads/vision`. This is the picture-based search, and it is a **string**, not bytes: the deposit has its own route, so a search request stays JSON and one endpoint serves both modes. A request may legitimately carry **only** an image, with no `question` and no `question_hashed`. See the vision pre-stage in *Query Processing Pipeline* for what happens then, and `vision_evidence` in the response for what comes back.
- `ui_language` (optional, str, default: `"en"`): Language code for the user-oriented `answer` field in the response. Only `"en"` (English) and `"fr"` (French) are supported; the value is normalized (case-insensitive, region/script subtags stripped, so `"fr-FR"` → `"fr"`) and any missing, empty, or unsupported value falls back to `"en"`. The answer is a plain-language sentence describing what the query returns, written in the specified language, with no table/column names or SQL details. This value is also used as part of the cache key, so the same question submitted with different `ui_language` values produces separate cache entries.
- `complex_question_processing` (optional, bool, default: `false`): Controls whether the API is allowed to escalate to the stronger model when the primary pipeline fails. When `false` (the default), the API returns the raw error or empty result set directly to the caller without retrying. When `true`, the three automatic retry triggers are active:
  - The text-to-SQL model cannot produce a SQL query and returns an error
  - The generated SQL raises an execution error on the database
  - The generated SQL executes successfully but returns an empty result set

  Set to `false` when calling from an agent or MCP tool so that the agent itself handles error conditions and decides whether to rephrase or escalate the question.

**Supported LLM Values for the 5 model parameters:**

- `default`
  - Uses the module default for the corresponding stage
  - Current defaults:
    - `llm_model_entity_extraction` → `gpt-4o`
    - `llm_model_text2sql` → `gpt-4o`
    - `llm_model_complex` → `gpt-4o`
    - `llm_model_result_entity` → `gpt-4o`
    - `llm_model_answer_single_value` → `gpt-4o`
    - `llm_model_vision` → `gpt-6-astra`

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
    - `gpt-5.6-terra`
    - `gpt-6-astra`
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
  - `llm_model_result_entity`
  - `llm_model_answer_single_value`
- **`llm_model_vision` is the exception, and deliberately so.** It reads an image, and every
  provider encodes an image differently, so it is wired for the OpenAI chat-completions route
  only: `gpt-4o`, the GPT-5.x line and `gpt-6-astra`. A `claude-*` or `gemini-*` name is
  refused with an error naming the supported families, rather than being sent and failing
  obscurely. Both providers do read images; adding one is a small explicit job, not something
  to have half-done in advance.
- `gemma-4-google` is intended for direct Google Gemma 4 access on entity extraction and text-to-SQL.
- `gemma-4` is available through OpenRouter and is useful if you prefer the OpenRouter route for Gemma 4.
- For `llm_model_complex`, if the selected stronger model is unavailable and it is not already `gpt-4o`, the application may retry once with `gpt-4o`.
- **Reasoning models do not take `temperature` at all (FASTAPI-TEXT2SQL-231).** The whole o-series, the entire GPT-5.x family (the 5.6 Sol / Terra / Luna tiers included) and the GPT-6 line answer HTTP 400 on any explicit `temperature`. `_openai_sampling_kwargs` therefore omits the parameter for those families and sends `reasoning_effort` instead; `gpt-4o` and the other 4.x models keep `temperature=0` and behave exactly as before. This applies to all five parameters, not just `llm_model_complex`.
- **`reasoning_effort` is the cost and latency knob, and it matters more than the tier.** The same model runs about 1.8 s to first token at `low` and about 115 s at `max`, and reasoning tokens are billed at the output rate. Defaults are the cheapest rung for the three tasks on the 100 % path and `medium` for the two complex-question tasks that fire on roughly 1 % of requests.
- **The GPT-6 family is selectable on every task, not only on the vision path (FASTAPI-TEXT2SQL-274).** `gpt-6-astra` is accepted by all six selectors above, exactly like any other model name, and the response echoes it back the same way (it is also the default of the sixth, the vision task). Two family details are handled for you and are worth knowing before reading a bill: GPT-6 has **no `none` rung** (its floor is `low`, unlike GPT-5.6), and it is served through `chat.completions` rather than the Responses API, so its prompt-cache figures are directly comparable with the `gpt-4o` baseline. Measured on 2026-09-19: the static prefix caches at **100 %** on repeat calls (24 190 of 24 193 tokens), against 99.5 % for `gpt-4o`, so the switch carries no cache penalty. On latency it is slightly slower at effort `low` (7.9–11.1 s on the text-to-SQL task alone, against 6.6 s for `gpt-4o` with a warm cache).
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
  "result_entity": "movie",
  "dropped_clause": "",
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
  "result_entity_processing_time": 0.31,
  "embeddings_processing_time": 0.12,
  "embeddings_cache_search_time": 0.05,
  "entity_resolution_planning_time": 0.09,
  "entity_raw_fallback_count": 0,
  "no_entity_extracted": false,
  "first_pass_sql_query": "",
  "first_pass_failure_code": "",
  "first_pass_failure_reason": "",
  "complex_retry_question": "",
  "complex_retry_cache_policy": "",
  "no_entity_rescue_outcome": "",
  "sql_regeneration_outcome": "",
  "complex_retry_intent_dropped": false,
  "complex_question_processing_time": 0.0,
  "answer_single_value_processing_time": 0.0,
  "vision_identification_processing_time": 0.0,
  "vision_model_used": false,
  "image_ref": "",
  "vision_evidence": null,
  "entity_match_worst_distance": 0.41,
  "entity_match_worst_fuzz_ratio": 88.0,
  "entity_match_scores": [
    {"placeholder": "{{Person_name1}}", "search_mode": "rapidfuzz", "collection": "persons",
     "sought": "humphrey bogart", "candidate": "Humphrey Bogart", "distance": null,
     "fuzz_ratio": 100.0, "fuzz_ratio_raw": 100.0, "stopwords_applied": false,
     "exact_match": true, "rejected": false}
  ],
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
  "llm_model_result_entity": "gpt-4o",
  "llm_model_answer_single_value": "gpt-4o",
  "llm_model_vision": "gpt-6-astra",
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
- `result_entity` (str): The kind of row the result set lists — one of `movie`, `serie`, `person`, `collection`, `list`, `topic`, `movement`, `technical`, `group`, `death`, `award`, `nomination`, `company`, `network`, `location`, `genre` (empty when not determined, e.g. ambiguous questions or `movie_serie` UNION results). `genre` is only chosen when the genres themselves are the answer ("what are the movie genres?"); a genre used to scope a search ("Sci-Fi movies") is a filter and yields `movie` / `serie`. It is the answer type enforced by the answer-entity guard, stored in the cache (`T_WC_T2S_CACHE.RESULT_ENTITY`) so it is also returned on cache hits.
- `dropped_clause` (str): **What the SQL does not implement.** Names the part of the question the generator had to abandon, empty when the SQL implements all of it (FASTAPI-TEXT2SQL-220). It is filled when a filter would have needed a placeholder that entity extraction never produced: dropping the filter widens the result, and saying nothing would present a narrower answer as a complete one. Example: `"genre filter: science-fiction"`. Neutral like `name_ambiguity`: the API states the fact, each client decides whether to show it. It is deliberately NOT used to decide whether an empty result is authoritative; that call belongs to FASTAPI-TEXT2SQL-207 and wants measuring first.
- `name_ambiguity` (dict, optional): **Neutral same-name-cluster signal** — present only when the generated SQL is a *pure* exact-equality match on an entity's name/title column(s) against a single literal (never `LIKE`) and returns **≥2 distinct rows**, i.e. the user named one entity (`movie` / `serie` / `person`) but the database holds several homonyms or duplicate titles (e.g. *"Steve McQueen"* → actor + director; *"Le Bonheur"* → four films). It is a **fact about the result, not an instruction**: the API does not decide whether to disambiguate — intent (*"tell me about Dracula"* vs *"list all movies called Dracula"*) is **not** in the SQL (both produce the identical `WHERE`), so a conversational client (voice-agent) reads this flag and asks *"which one?"* while a plain display client (tmdb-front) ignores it. `null` otherwise, so ignoring clients are unaffected. Shape: `{ "entity": "movie", "anchor": "Le bonheur", "count": 4, "candidates": [ { "id": 53023, "display": "Le Bonheur", "discriminator": { "year": 1965, "release_date": "1965-02-17", "directors": ["Agnès Varda"], "top_cast": ["Jean-Claude Drouot", "Claire Drouot", "Marie-France Boyer"] } }, … ] }` — for `movie` / `serie` the discriminator carries the `year` (human phrasing, "the 1969 one"), the full `release_date` (`YYYY-MM-DD`, `null` when only a year is known), the **`directors`** and the top-3 billed **`top_cast`** (plus **`creators`** for `serie`) — so twins sharing *both* title AND year (e.g. *The Odyssey*'s two 2026 films, Nolan vs Walz) are told apart by the director/cast name, not only the date (FASTAPI-TEXT2SQL-176). For `person` the discriminator is `{ "birth_year", "death_year", "role", "birth_date", "death_date", "country_of_birth", "known_for" }`, where **`known_for`** lists up to 3 of the person's best-rated titles (by `IMDB_RATING_WEIGHTED`, movies + series) so two homonyms (e.g. *Steve McQueen* the actor vs the director) are separable by their notable works, nationality and full dates. `candidates` is ordered **chronologically, oldest first** (by `release_date`, else the year — `birth_year` for a person — with undated candidates last, ties keeping DB order). DB order is arbitrary, which misled consumers twice: an agent enumerating candidates read them out of order, and a *positional* reading of a superlative (*"the latest one"* = the last item) picked the wrong entity. Ordering by date makes position agree with time, so the last candidate really is the most recent. Only **true duplicates** (rows sharing the same `ID_IMDB`) are collapsed; distinct works that merely share a title and year are kept as separate candidates (e.g. two different *Dracula* films from 2025). Computed on page 1 only.
- `image_ref` (str): The image this turn was built from, echoed back so a client can keep holding it across the turns of one conversation without ever re-sending the bytes. Empty when no image was sent
- `vision_evidence` (dict, optional): **What the model read in the image, and why it proposes what it proposes.** `null` without an image. Shape: `{ "image_ref", "user_question" (the words the user actually typed, before the composition overwrote them), "cached" (true when the identification came from the recognition cache), "hints": { "kind": poster | frame | still | physical_media | other, "title_text", "credits_block", "faces": [], "era_cues": [], "genre_cues": [], "text_language" }, "candidates": [ { "type", "value", "year", "note", "confidence", "evidence": [] } ] (ranked, best first), "selected", "alternatives", "dominant" (true when one candidate clearly leads, so its entry is opened and the others are only reported), "about_image", "authoritative_empty", "justification", "composed_question" (the question the rest of the pipeline actually answered), "confidence_thresholds" }`. The `evidence` strings are the point: they cite what was read (a credits block, a typography, a face), which is what lets a client show **how** the image was read instead of dropping a title out of nowhere
- `entity_extraction` (dict, optional): Full LLM entity extraction output, including the anonymized `question` key plus one key per extracted placeholder (e.g., `Person_name1`, `Movie_title1`)
- `question_anonymized` (str, optional): The user question with entities replaced by typed placeholders
- `error` (str): Error message if query processing failed (e.g., the LLM's explanation when the question is ambiguous)
- `error_code` (str, optional): Structured API error code when the failure can be classified. `"429"` is used for retryable provider quota / rate-limit failures. `"cache_miss"` is returned (with HTTP 200, `is_retryable: false`) when a request supplies a `question_hashed` that is not present in the cache and provides no original `question` text to fall back on: resend the request including the original question. Four more belong to the picture-based search, all of them HTTP 200 with a `Text2SQLResponse` body so a client never has to branch on the status code: `"image_ref_invalid"` (the reference is not one this API could have produced), `"image_gone"` (the image is past its 30-day retention, the answer says the deposit date), `"image_missing"` (it is absent although still inside its window, which points at the uploads mount rather than at the purge) and `"vision_failed"` (the vision model could not be reached or answered outside its contract). Note that an image with nothing of cinema in it is **not** one of these: it is an answer, with `error` empty.
- `is_retryable` (bool): Indicates whether the client should treat the failure as retryable.
- `retry_after_seconds` (float, optional): Suggested wait time before retrying the request. When available, this is extracted from the underlying provider response.
- `provider` (str, optional): Provider associated with the failure when it can be inferred, such as `google`, `openrouter`, `openai`, or `anthropic`.
- `result` (list): Array of query results, each with `index` (int) and `data` (dict)

**Performance Metrics:**
- `entity_extraction_processing_time` (float): Time for entity extraction in seconds
- `text2sql_processing_time` (float): Time for SQL generation in seconds
- `result_entity_processing_time` (float): Time spent classifying the expected answer entity from the original question
- `embeddings_processing_time` (float): Time for entity resolution, vector search included, in seconds
- `embeddings_cache_search_time` (float): Time for embeddings cache lookup in seconds
- `entity_resolution_planning_time` (float): How much of `embeddings_processing_time` was overlapped with SQL generation by the fork-join. **Already counted inside it**, never add the two. 0.0 on a cache hit or when `ENTITY_RESOLUTION_PARALLEL=0`
- `entity_raw_fallback_count` (int): Entities whose configured resolvers all failed, so their raw words went into the SQL. Non-zero means a following empty result is a resolution failure, not a fact about the data
- `no_entity_extracted` (bool): True when extraction returned no entity at all, so the question was never anonymized
- `first_pass_sql_query` (string): On a retried request, the SQL the first pass generated (executed, or refused before execution) before the stronger model took over. Empty when no retry happened (FASTAPI-TEXT2SQL-241). Before that ticket the failing SQL survived nowhere: the response returned is the second pass's, and the log file for the user's own wording was never written
- `first_pass_failure_code` (string): Why that first pass was abandoned, closed vocabulary: `descriptive_identification` (entity extraction classified the question as the identification of an unnamed entity, so the routing is deliberate rather than a failure), `requires_complex_resolution` (Text2SQL declared itself unable), `unbacked_entity_literal` (the provenance guard refused a literal supplied by neither the user nor the extraction), `text2sql_error`, `sql_guard_rejected`, `entity_fallback_unmatchable`, `sql_execution_error`, or `no_results:<signal>[+<signal>]` with the signals of the no-results guard in its own order, `unresolved_placeholder`, `raw_fallback`, `no_entity_extracted`, `person_role_collapse`. The first two shared the second label until FASTAPI-TEXT2SQL-271
- `first_pass_failure_reason` (string): The same in words, with the database error text or the guard signals spelled out
- `complex_retry_question` (string): The question the stronger model rewrote, which the second pass answered. Compare it with `question` to see what the rewrite added or changed (a release year the user never typed, a title turned into a person, ...)
- `complex_retry_cache_policy` (string): What became of the cache row for the original question after a retry (FASTAPI-TEXT2SQL-242): `stored`, `skipped:empty_result`, or `skipped:added_constraint (year 2004)` when the rewrite carries a year absent from the question. A rewrite that narrows the question is never frozen under the user's own wording; the rewritten question stays cached under its own. Empty without a retry
- `no_entity_rescue_outcome` (string): When the first pass returned 0 rows with no entity extracted, the API puts the literal values of the SQL (`MOVIE_TITLE = 'Pour le plaisir'`) back through the entity resolver before calling the stronger model (FASTAPI-TEXT2SQL-244): `rescued` (re-executed with the resolved value, rows came back), `still_empty` (re-executed, still nothing), `resolver_found_nothing` (raw fallback, first-pass SQL stands), `no_literal` (nothing resolvable in the SQL), `error`. Empty when the rescue was not attempted
- `sql_regeneration_outcome` (string): When the query was refused by the engine (an unknown column) or by the SQL guard, the API regenerates the SQL ONCE for the same question, handing the model its own error back, before any question rewrite (FASTAPI-TEXT2SQL-262): `regenerated` (the new query executed and returned rows), `regenerated_empty` (it executed and returned none), `unchanged` / `no_sql` (the model gave nothing usable), `guard_rejected`, `unbacked_entity_literal` (the new query invented an entity value, refused by the -252 provenance guard), `error`. Empty when no regeneration was attempted. A broken SQL is a generator defect, not a question defect, so the question is never touched here
- `complex_retry_intent_dropped` (boolean): True when the stronger model's rewrite REPLACED the question instead of repairing it (FASTAPI-TEXT2SQL-263): the original asked about a relation ("in which city does the action of Pulp Fiction take place?") and the rewrite came back as a bare entity card ("Movie Pulp Fiction (1994)"), with a different answer entity. The rows returned identify that entity; they do NOT answer what was asked, and nothing is cached under the original question. False on a retry that kept the intention (an alias corrected to its credited name), and without a retry
- `entity_match_worst_distance` (float or null): Embeddings distance of the **weakest accepted** match of the request. A dissimilarity, so larger is further and a threshold reads `<= max_distance`. `null` when no entity went through a scored resolver (closed-vocabulary and regex placeholders produce no score)
- `entity_match_worst_fuzz_ratio` (float or null): `fuzz.ratio` of the weakest accepted match, on 100. A similarity, so larger is closer and a threshold reads `>= min_fuzz_ratio`. The two "worst" therefore run in opposite directions
- `entity_match_scores` (list): One entry per candidate weighed by an embeddings or rapidfuzz strategy, accepted or not, with what was sought, what was found and how far apart they sat. `fuzz_ratio` is the score the gate actually used, after the entity's own descriptor words were neutralised on both sides; `fuzz_ratio_raw` is what it would have been without that, kept so the effect stays auditable. Measured 2026-08-24: "wagonlit collection" against "life collection" scores 76.5 raw and 33.3 stripped, and the threshold sits at 72. This is the calibration material for FASTAPI-TEXT2SQL-206: twelve of the fourteen resolvers currently have no threshold and accept their nearest neighbour however far it sits. Not summed across a retry, like the counts: it describes the resolution that produced the returned result
- `complex_question_processing_time` (float): The stronger-model simplification call that precedes a complex retry. 0.0 when no retry happened, so it is the most direct marker of a retried request. **On a retried request every timing above covers both passes**, and `total_processing_time` is the real end-to-end elapsed
- `answer_single_value_processing_time` (float): The direct scalar answer asked of the stronger model when the SQL returned a single cell worth 0 (FASTAPI-TEXT2SQL-233). 0.0 when that branch did not fire. Banked before any early return, so an answer that errored still reports the seconds it spent. With this field the response carries **one wall clock per LLM task**, which is what makes a per-task model swap measurable rather than merely configurable. The five do not sum to `total_processing_time`: that one is measured end to end and includes the plumbing between the steps
- `vision_identification_processing_time` (float): The sixth and last wall clock, the vision call that read the image and named what it points at (FASTAPI-TEXT2SQL-114). 0.0 when no image was sent **and** on a recognition-cache hit, which is the criterion that proves the cache: the same photo re-deposited answers with this at 0.0 and `vision_model_used` false, because the identification came from the fingerprint of the bytes rather than from a second call of about 4 cents
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
- `llm_model_result_entity` (str): LLM model actually used for the answer-entity classifier (FASTAPI-TEXT2SQL-232)
- `llm_model_answer_single_value` (str): LLM model **configured** for the direct scalar answer, exposed even when that branch did not fire
- `llm_model_vision` (str): LLM model **configured** for the image-reading task, exposed even when no image was sent
- `vision_model_used` (bool, default `false`): **Whether the vision model was actually invoked** on this turn. Read this rather than `llm_model_vision`, exactly as `complex_model_used` is read rather than `llm_model_complex`. It stays `false` on a recognition-cache hit, and it is what proves a second turn on the same photo cost nothing
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

**Localization (`ui_language`)**: every entity detail endpoint accepts an optional `ui_language` query parameter (e.g. `GET /movies/123?ui_language=fr`). Supported values are `"en"` (default) and `"fr"`; the value is normalized and any missing/unsupported value falls back to `"en"`. Responses are **fully localized and collapsed**: each localizable column (`MOVIE_TITLE`, `SERIE_TITLE`, `TOPIC_NAME`, `LIST_NAME`, `COLLECTION_NAME`, `MOVEMENT_NAME`, `AWARD_NAME`, `NOMINATION_NAME`, `GROUP_NAME`, `DEATH_NAME`, `ITEM_LABEL`, technical `DESCRIPTION`) is returned under its canonical name carrying the requested language's value (English fallback when the French value is empty), both on the primary entity and on nested related entities. The separate `*_FR` columns are **not** returned. `wikipedia_content` and `wikipedia_images` are filtered to the requested language with English fallback. Note: person `BIOGRAPHY` and company `DESCRIPTION` have no French variant in the database and are always returned as stored.

**Localized main picture (`ui_language` != `"en"`)**: image paths have no `_FR` column, so for a non-default language the server overrides each entity's main-picture path with the main (lowest `DISPLAY_ORDER`) related image whose `LANG` matches the requested language, keeping the canonical (default) path as a fallback when no localized image exists.

- **Primary entity**: wired on the endpoints that carry a language-tagged image array — `/movies/{id}`, `/series/{id}`, and `/seasons/{id_serie}/{season_number}` override `POSTER_PATH` from their `posters` array; `/persons/{id}` overrides `PROFILE_PATH` from its `portraits` array.
- **Nested collections**: the related-entity rows embedded in every detail response are localized too. Person rows (`cast`, `crew`, and the `persons` arrays on `/groups`, `/deaths`, `/awards`, `/nominations`) get a localized `PROFILE_PATH`; movie and series rows (`movie_cast`/`movie_crew`, `series_cast`/`series_crew`, and the `movies`/`series` arrays on `/companies`, `/networks`, `/collections`, `/topics`, `/lists`, `/movements`, `/technicals`, `/awards`, `/nominations`, `/locations`) get a localized `POSTER_PATH`; the parent-`series`/`season` navigation stubs (`/seasons`, `/episodes`) and the `seasons` array on `/series` are localized as well. These are resolved with one batched image lookup per entity kind, so a non-`en` request adds at most a few extra queries.

The language-tagged image arrays themselves (`posters`, `portraits`, …) are always returned in full so a client can still pick a different language, and usage logs keep the canonical paths (localization runs after logging). Episodes are not affected (`STILL_PATH` frames are not language-specific).

**Collection pagination (`collection` / `page` / `rows_per_page`)**: the embedded **related-entity lists** can be very large (a prolific person has thousands of `movie_cast` credits; a popular technical format has thousands of `movies`). To keep responses bounded, every entity detail endpoint paginates these lists:

- **Default (no extra params)** — a bare `GET /persons/123` returns **every** related-entity list, each capped to its first page (`rows_per_page` rows, default **50**, max **200**). A top-level `pagination` object reports each list's totals:
  ```jsonc
  "pagination": {
    "movie_cast": { "total": 1287, "page": 1, "rows_per_page": 50, "returned": 50 },
    "movie_crew": { "total": 12,   "page": 1, "rows_per_page": 50, "returned": 12 },
    "groups":     { "total": 1,    "page": 1, "rows_per_page": 50, "returned": 1 }
    /* one entry per paginated list */
  }
  ```
  The arrays themselves stay plain lists (backward compatible); only the new `pagination` key is added.
- **Targeted (`?collection=<name>&page=N&rows_per_page=M`)** — `GET /persons/123?collection=movie_cast&page=2` returns a **lean** payload with just that one list's requested page (the base entity fields and the other lists are omitted to save bandwidth):
  ```jsonc
  {
    "id": 123,
    "collection": "movie_cast",
    "movie_cast": [ /* page-2 rows */ ],
    "pagination": { "movie_cast": { "total": 1287, "page": 2, "rows_per_page": 50, "returned": 50 } }
  }
  ```
  (For composite-key endpoints the identifier echo uses the path keys, e.g. `id_serie`/`season_number` for `/seasons`.) An unknown `collection` name for that endpoint returns `400` listing the valid names. `page` defaults to `1`, `rows_per_page` to `50` (clamped to `1..200`). Targeted mode does not re-validate the parent entity's existence — an unmatched id simply yields an empty list with `total: 0`.

Pagination covers only the related-entity lists. Image arrays (`posters`, `backdrops`, `portraits`, `stills`), `videos`, `wikipedia_images`, `wikipedia_content`, and scalar lists (`genres`, `production_countries`, `spoken_languages`) are always returned in full. Each endpoint's paginatable `collection` names are exactly the related-list field names documented in the per-endpoint tables below.

**Data freshness (`data_freshness`)**: every entity detail endpoint returns a top-level `data_freshness` object dating the payload. Nothing in a response is fetched live from TMDb or Wikipedia, everything is served from the read-model, so without this block a client (the `voice-agent` in particular) has no way to tell the user how current an answer is, or to distinguish a movie whose TMDb record was refreshed yesterday from one last touched two years ago.

```jsonc
"data_freshness": {
  "record_source":        "tmdb",                  // "tmdb" | "wikidata" | "reference"
  "record_updated_at":    "2026-07-21T04:12:33",   // base row TIM_UPDATED
  "tmdb_updated_at":      "2026-07-21T04:12:33",   // TMDb refresh datetime (null when not TMDb-sourced)
  "wikidata_updated_at":  null,                    // TIM_WIKIDATA_COMPLETED, when the base table has it
  "wikipedia_updated_at": "2026-07-14T02:31:07",   // last SUCCESSFUL Wikipedia fetch = data date of wikipedia_content
  "wikipedia_crawled_at": "2026-07-20T03:02:11",   // last crawl attempt (later than updated_at = recent failures)
  "wikipedia_lang":       "fr"                     // language wikipedia_content / wikipedia_images were served in
}
```

- `record_source` says where the base row comes from, which is what makes `tmdb_updated_at` meaningful. For the TMDb-sourced entities (`/movies`, `/series`, `/seasons`, `/episodes`, `/persons`, `/companies`, `/networks`) the preprocess copies `TIM_UPDATED` **verbatim** from the `T_WC_TMDB_*` source row, so it really is the TMDb refresh datetime. For the Wikidata-derived entities (`/collections`, `/topics`, `/lists`, `/movements`, `/technicals`, `/groups`, `/deaths`, `/awards`, `/nominations`, `/locations`) TMDb has no say in the record, so `tmdb_updated_at` is `null` and `record_updated_at` / `wikidata_updated_at` are the dates that matter. `/genres` reads the static reference table `T_WC_TMDB_GENRE`, which carries no timestamps at all, so every field is `null`.
- The `wikipedia_*` fields come from `T_WC_WIKIPEDIA_PAGE_LANG` for the entity's `ID_WIKIDATA`, resolved to the **same language** the `wikipedia_content` / `wikipedia_images` arrays of that response were served in (requested language when it actually has sections, English fallback otherwise). They are `null` on `/companies`, `/networks`, and `/genres`, whose base tables have no `ID_WIKIDATA`.
- `wikipedia_updated_at` (`LAST_SUCCESS_AT`) is the honest data date: the last time the page was fetched **successfully**. `wikipedia_crawled_at` (`LAST_CRAWLED_AT`) is the last attempt whether it succeeded or not, so a `crawled_at` later than `updated_at` means recent attempts failed and the served content is older than the crawl suggests.
- The block is returned on the **full** response only. A targeted `?collection=<name>` page is a pagination sub-request and keeps its lean shape.

**Wikipedia page reference (`wikipedia_page`)**: every endpoint that can return `wikipedia_content` also returns the **resolved source article** for that content. A client holding only an `ID_WIKIDATA` cannot build this link, and it needs it: displaying the `wikipedia_content` prose requires **CC BY-SA attribution** pointing at the exact article the prose came from. The article's title is not the entity's title, and it differs per language, so the URL cannot be derived client-side.

```jsonc
"wikipedia_page": {
  "lang":  "fr",                                                  // the language actually served
  "title": "Le Seigneur des anneaux : La Communauté de l'anneau", // WIKIPEDIA_PAGE_TITLE
  "url":   "https://fr.wikipedia.org/wiki/..."                    // WIKIPEDIA_PAGE_URL
}
```

- **The language is resolved server-side**, by the same rule that governs `wikipedia_content` / `wikipedia_images`: the requested `ui_language` when it actually has sections, English otherwise. `lang` reports **what was returned, not what was asked for**, so a client never has to redo the fallback and can label the credit honestly. `GET /movies/{id}?ui_language=de` therefore returns `lang: "en"` and the English article.
- **It is the same page row that `data_freshness` dates**, which is the point: `wikipedia_page.lang` always equals `data_freshness.wikipedia_lang`. The two must never diverge, or the response would date one language's content while crediting another language's article. Note the subtlety this guards against: a page row can exist for a language that carries **no sections**, so resolving on page-row availability instead of on the served content would put an `fr` credit over English prose.
- **The key is absent, not `null`**, when the entity has no Wikipedia page (or when the page row carries no title or no URL). A null-filled object would invite a client to render an empty credit; a missing key says plainly there is nothing to attribute. It is therefore always absent on `/companies`, `/networks` and `/genres`, whose base tables have no `ID_WIKIDATA`, and almost always absent on `/episodes`.
- **Detail responses only.** It is never added to `/search/text2sql` results or to related-entity list rows, and, like `data_freshness`, it is omitted from a targeted `?collection=<name>` page.
- Carried by the 15 detail endpoints that can serve `wikipedia_content`: `/movies/{id}`, `/series/{id}`, `/seasons/{id_serie}/{season_number}`, `/episodes/{id_serie}/{season_number}/{episode_number}`, `/persons/{id}`, `/collections/{id}`, `/topics/{id}`, `/lists/{id}`, `/movements/{id}`, `/technicals/{id}`, `/groups/{id}`, `/deaths/{id}`, `/awards/{id}`, `/nominations/{id}`, `/locations/{id}`. The 13 of those with an MCP `get_*` tool expose it there too (`/seasons` and `/episodes` have no MCP wrapper).

| Method | Endpoint | Identifier | Primary table | Purpose |
|---|---|---|---|---|
| `GET` | `/movies/{id}` | `ID_MOVIE` | `T_WC_T2S_MOVIE` | Movie detail |
| `GET` | `/series/{id}` | `ID_SERIE` | `T_WC_T2S_SERIE` | TV series detail |
| `GET` | `/seasons/{id_serie}/{season_number}` | `(ID_SERIE, SEASON_NUMBER)` | `T_WC_TMDB_SEASON` (TMDb source — no T2S equivalent yet) | TV series season detail |
| `GET` | `/episodes/{id_serie}/{season_number}/{episode_number}` | `(ID_SERIE, SEASON_NUMBER, EPISODE_NUMBER)` | `T_WC_TMDB_EPISODE` (row source) + `T_WC_T2S_EPISODE` (IMDb rating fields) | TV series episode detail |
| `GET` | `/persons/{id}` | `ID_PERSON` | `T_WC_T2S_PERSON` | Person detail |
| `GET` | `/companies/{id}` | `ID_COMPANY` | `T_WC_T2S_COMPANY` | Production company detail |
| `GET` | `/networks/{id}` | `ID_NETWORK` | `T_WC_T2S_NETWORK` | TV network detail |
| `GET` | `/collections/{id}` | `ID_T2S_COLLECTION` | `T_WC_T2S_COLLECTION` | Collection, franchise, or universe detail |
| `GET` | `/topics/{id}` | `ID_TOPIC` | `T_WC_T2S_TOPIC` | Topic detail |
| `GET` | `/lists/{id}` | `ID_T2S_LIST` | `T_WC_T2S_LIST` | Curated list detail |
| `GET` | `/movements/{id}` | `ID_MOVEMENT` | `T_WC_T2S_MOVEMENT` | Film movement or style detail |
| `GET` | `/technicals/{id}` | `ID_TECHNICAL` | `T_WC_T2S_TECHNICAL` | Technical format detail (sound system, color/film/sound technology, film format) |
| `GET` | `/genres/{id}` | `ID_GENRE` (TMDb genre code) | `T_WC_TMDB_GENRE` | Movie / TV genre detail (closed vocabulary) |
| `GET` | `/groups/{id}` | `ID_GROUP` | `T_WC_T2S_GROUP` | Person group detail |
| `GET` | `/deaths/{id}` | `ID_DEATH` | `T_WC_T2S_DEATH` | Cause or circumstance of death detail |
| `GET` | `/awards/{id}` | `ID_AWARD` | `T_WC_T2S_AWARD` | Award detail |
| `GET` | `/nominations/{id}` | `ID_NOMINATION` | `T_WC_T2S_NOMINATION` | Award nomination detail |
| `GET` | `/locations/{id}` | `ID_LOCATION` | `T_WC_T2S_LOCATION` | Location detail |

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
| `collections_context` | One chronological context **per collection** the entity belongs to (FASTAPI-TEXT2SQL-153): array of `{ ID_T2S_COLLECTION, collection_name, collection_movies (cross-type members, each with `ENTITY_TYPE` + `IS_CURRENT`), collection_previous, collection_next }`. **Primary-first**: `[0]` is the same collection the single `collection_name` / `collection_movies` / `collection_previous` / `collection_next` fields expose (kept for backward-compat). `[]` when standalone |
| `movements` | Array of `{ ID_MOVEMENT, MOVEMENT_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `technicals` | Array of `{ ID_TECHNICAL, DESCRIPTION, DESCRIPTION_FR, TECHNICAL_TYPE, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }` from `T_WC_T2S_MOVIE_TECHNICAL` joined to `T_WC_T2S_TECHNICAL`, ordered by `DISPLAY_ORDER`. `TECHNICAL_TYPE` is one of `sound_system`, `color_technology`, `film_technology`, `sound_technology`, `film_format` |
| `awards` | Array of `{ ID_AWARD, AWARD_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `nominations` | Array of `{ ID_NOMINATION, NOMINATION_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `cast` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER`. For non-documentary movies (`IS_DOCUMENTARY != 1`), rows whose `CAST_CHARACTER` is one of `Self`, `Himself`, `Herself`, `(archive footage)`, `Self (archive footage)`, `Self (archive footage) (uncredited)`, or `Self (uncredited)` are excluded |
| `crew` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `DISPLAY_ORDER` |
| `posters` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_MOVIE_IMAGE` where `TYPE_IMAGE = 'poster'`, ordered by `DISPLAY_ORDER` |
| `backdrops` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_MOVIE_IMAGE` where `TYPE_IMAGE = 'backdrop'`, ordered by `DISPLAY_ORDER` |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the movie's `ID_WIKIDATA`, filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the movie's `ID_WIKIDATA`, filtered to the requested `ui_language` (English fallback when that language has no sections) and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_page` | Resolved source article for `wikipedia_content`: `{ lang, title, url }` from `T_WC_WIKIPEDIA_PAGE_LANG`, using the same language resolution and the same page row that `data_freshness` dates (so `lang` always equals `data_freshness.wikipedia_lang`). **Absent**, not null, when there is no page. Required for CC BY-SA attribution when displaying `wikipedia_content` |
| `data_freshness` | Object `{ record_source, record_updated_at, tmdb_updated_at, wikidata_updated_at, wikipedia_updated_at, wikipedia_crawled_at, wikipedia_lang }` dating the payload. Same shape on every entity detail endpoint, see **Data freshness** above |
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
| `collections_context` | One chronological context **per collection** the entity belongs to (FASTAPI-TEXT2SQL-153): array of `{ ID_T2S_COLLECTION, collection_name, collection_movies (cross-type members, each with `ENTITY_TYPE` + `IS_CURRENT`), collection_previous, collection_next }`. **Primary-first**: `[0]` is the same collection the single `collection_name` / `collection_movies` / `collection_previous` / `collection_next` fields expose (kept for backward-compat). `[]` when standalone |
| `movements` | Array of `{ ID_MOVEMENT, MOVEMENT_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH, IMDB_RATING_WEIGHTED, POPULARITY }`, ordered by `DISPLAY_ORDER` |
| `awards` | Array of `{ ID_AWARD, AWARD_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `nominations` | Array of `{ ID_NOMINATION, NOMINATION_NAME, POSTER_PATH, WIKIPEDIA_IMAGE_PATH }`, ordered by `DISPLAY_ORDER` |
| `cast` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER`. No self-appearance filter is applied on the series side (text-to-SQL behavior is symmetric) |
| `crew` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `DISPLAY_ORDER` |
| `posters` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_SERIE_IMAGE` where `TYPE_IMAGE = 'poster'`, ordered by `DISPLAY_ORDER` |
| `backdrops` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_T2S_SERIE_IMAGE` where `TYPE_IMAGE = 'backdrop'`, ordered by `DISPLAY_ORDER` |
| `seasons` | Array of `{ ID_SEASON, SEASON_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, POSTER_PATH, EPISODE_COUNT, VOTE_AVERAGE, ID_IMDB, ID_WIKIDATA, ID_TVDB, IMDB_RATING, IMDB_RATED_EPISODES }`. Rows come from `T_WC_TMDB_SEASON`, `LEFT JOIN`ed to `T_WC_T2S_SEASON` for the two IMDb fields, ordered by `SEASON_NUMBER ASC`. Season 0 (specials) is included when present. **`IMDB_RATING` is derived, not sourced**: IMDb rates titles and episodes but never seasons, so this is the plain mean of the season's rated episodes, rolled up by `tmdb-movie-preprocess` Process 28. `IMDB_RATED_EPISODES` is how many episodes back that mean, the honest denominator for a season still airing (summing episode votes would count the same viewers once per episode). Both are `NULL` / `0` until the rollup has run |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the series's `ID_WIKIDATA`, filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the series's `ID_WIKIDATA`, filtered to the requested `ui_language` (English fallback when that language has no sections) and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_page` | Resolved source article for `wikipedia_content`: `{ lang, title, url }` from `T_WC_WIKIPEDIA_PAGE_LANG`, using the same language resolution and the same page row that `data_freshness` dates (so `lang` always equals `data_freshness.wikipedia_lang`). **Absent**, not null, when there is no page. Required for CC BY-SA attribution when displaying `wikipedia_content` |
| `videos` | Array of `{ SOURCE, VIDEO_KEY, VIDEO_NAME, VIDEO_SITE, VIDEO_TYPE, LANG, OFFICIAL, DAT_PUBLISHED, DURATION_SECONDS, WATCH_URL, EMBED_URL, FILE_URL, THUMBNAIL_URL, DISPLAY_ORDER }` merging TMDb-sourced videos (`T_WC_TMDB_SERIE_VIDEO`, `SOURCE='tmdb'`) and Wikidata-sourced videos (`T_WC_WIKIDATA_MEDIA_RESOURCE`, `SOURCE='wikidata'`, filtered to `RESOURCE_KIND='video'`). Ordering and field semantics match the `/movies/{id}` `videos` row |

Base series fields currently include `ID_SERIE`, `SERIE_TITLE`, `DAT_FIRST_AIR`, `FIRST_AIR_YEAR`, `FIRST_AIR_MONTH`, `FIRST_AIR_DAY`, `DAT_LAST_AIR`, `LAST_AIR_YEAR`, `LAST_AIR_MONTH`, `LAST_AIR_DAY`, `ID_IMDB`, `ID_WIKIDATA`, `POSTER_PATH`, `POPULARITY`, `ORIGINAL_LANGUAGE`, `STATUS`, `BACKDROP_PATH`, `TAGLINE`, `VOTE_AVERAGE`, `VOTE_COUNT`, `NUMBER_OF_EPISODES`, `NUMBER_OF_SEASONS`, `SERIE_TYPE`, `DAT_CREAT`, `TIM_UPDATED`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, `WIKIDATA_TITLE`, `ALIASES`, `PLEX_MEDIA_KEY`, and `INSTANCE_OF`.

##### `GET /seasons/{id_serie}/{season_number}`

Returns all `T_WC_TMDB_SEASON` fields for a single season of a TV series, identified by the composite key `(ID_SERIE, SEASON_NUMBER)`. Season `0` is the specials season when present. Returns `404` when the season does not exist for the given series.

Example: `GET /seasons/1396/5` returns season 5 of *Breaking Bad* (ID_SERIE 1396).

The endpoint reads its rows from the TMDb source tables `T_WC_TMDB_SEASON`, `T_WC_TMDB_PERSON_SEASON`, `T_WC_TMDB_SEASON_IMAGE` and `T_WC_TMDB_EPISODE`, and `LEFT JOIN`s `T_WC_T2S_EPISODE` for the IMDb rating fields on each episode row. The `T_WC_T2S_SEASON` / `T_WC_T2S_EPISODE` read-model tables **now exist** (tmdb-movie-preprocess Processes 27/28); the row source has deliberately not been swapped yet because the T2S scope filter and the `TITLE` → `EPISODE_TITLE` rename are behaviour changes — see [SEASONS_AND_EPISODES.md](doc/SEASONS_AND_EPISODES.md) §6.1 and the 2026-07-26 status note.

| Field | Shape |
|---|---|
| `cast` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, TOTAL_EPISODE_COUNT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER`. `TOTAL_EPISODE_COUNT` is the number of episodes the person appeared in across the season |
| `crew` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, TOTAL_EPISODE_COUNT, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `DISPLAY_ORDER` |
| `posters` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_TMDB_SEASON_IMAGE` where `TYPE_IMAGE = 'poster'`, ordered by `DISPLAY_ORDER` |
| `backdrops` | Array of `{ ID_ROW, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_TMDB_SEASON_IMAGE` where `TYPE_IMAGE = 'backdrop'`, ordered by `DISPLAY_ORDER`. Most TMDb seasons only have posters, so this list is frequently empty |
| `series` | Object `{ ID_SERIE, SERIE_TITLE, POSTER_PATH }` for the parent series — navigation stub so the frontend can render breadcrumbs without a second `/series/{id}` round trip |
| `episodes` | Array of `{ ID_EPISODE, EPISODE_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, RUNTIME, EPISODE_TYPE, STILL_PATH, VOTE_AVERAGE, VOTE_COUNT, ID_IMDB, ID_WIKIDATA, ID_TVDB, IMDB_RATING, IMDB_VOTES }` from `T_WC_TMDB_EPISODE` `LEFT JOIN`ed to `T_WC_T2S_EPISODE` for the two IMDb fields, ordered by `EPISODE_NUMBER ASC`. `IMDB_RATING` / `IMDB_VOTES` are `NULL` when the episode has no IMDb id, has no rating yet (typically not aired), or falls outside the T2S scope; they do **not** replace `VOTE_AVERAGE` / `VOTE_COUNT`, which stay the TMDb figures and are not comparable (TMDb episode votes are routinely in the dozens where IMDb is in the tens of thousands). Length matches the season's `EPISODE_COUNT`. Each row is a **summary**: episode cast/crew, additional stills, and Wikipedia payloads live on `/episodes/{id_serie}/{season_number}/{episode_number}` and are not duplicated here to keep the season payload bounded. To open a specific episode, call `/episodes/{id_serie}/{season_number}/{EPISODE_NUMBER}` (the path key is `EPISODE_NUMBER`, not the surrogate `ID_EPISODE`) |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the season's `ID_WIKIDATA`, filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL — common for seasons |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the season's `ID_WIKIDATA`, filtered to the requested `ui_language` (English fallback when that language has no sections) and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_page` | Resolved source article for `wikipedia_content`: `{ lang, title, url }` from `T_WC_WIKIPEDIA_PAGE_LANG`, using the same language resolution and the same page row that `data_freshness` dates (so `lang` always equals `data_freshness.wikipedia_lang`). **Absent**, not null, when there is no page. Required for CC BY-SA attribution when displaying `wikipedia_content` |
| `videos` | Array of TMDb-sourced videos (`SOURCE='tmdb'`) for this season from `T_WC_TMDB_SEASON_VIDEO`, ordered by `OFFICIAL DESC, DISPLAY_ORDER ASC`. Wikidata media is not modeled at the season level. Field shape matches the `/movies/{id}` `videos` row (Wikidata-only fields like `DURATION_SECONDS` are always null here) |

Base season fields currently include `ID_SEASON`, `ID_SERIE`, `SEASON_NUMBER`, `TITLE`, `OVERVIEW`, `AIR_YEAR`, `AIR_MONTH`, `AIR_DAY`, `DAT_AIR`, `POSTER_PATH`, `EPISODE_COUNT`, `VOTE_AVERAGE`, `ID_IMDB`, `ID_WIKIDATA`, `ID_TVDB`, `DELETED`, `DISPLAY_ORDER`, plus the standard TMDb provenance/timestamp columns (`DAT_CREAT`, `TIM_UPDATED`, `TIM_CREDITS_COMPLETED`, `TIM_IMAGES_COMPLETED`, `TIM_VIDEOS_COMPLETED`, `TIM_TRANSLATIONS_COMPLETED`, `TIM_EPISODES_COMPLETED`, `TIM_WIKIDATA_COMPLETED`).

##### `GET /episodes/{id_serie}/{season_number}/{episode_number}`

Returns all `T_WC_TMDB_EPISODE` fields for a single episode, identified by the composite key `(ID_SERIE, SEASON_NUMBER, EPISODE_NUMBER)`. Returns `404` when the episode does not exist for the given series and season.

Example: `GET /episodes/1396/5/14` returns "Ozymandias" — *Breaking Bad* season 5, episode 14.

The endpoint reads its rows from the TMDb source tables `T_WC_TMDB_EPISODE`, `T_WC_TMDB_PERSON_EPISODE` and `T_WC_TMDB_EPISODE_IMAGE`, and `LEFT JOIN`s `T_WC_T2S_EPISODE` for `IMDB_RATING` / `IMDB_VOTES`. The `T_WC_T2S_EPISODE` read-model table **now exists** (tmdb-movie-preprocess Process 28); the row source has deliberately not been swapped yet — see [SEASONS_AND_EPISODES.md](doc/SEASONS_AND_EPISODES.md) §6.1 and the 2026-07-26 status note.

| Field | Shape |
|---|---|
| `cast` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, DISPLAY_ORDER }` where `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER` |
| `crew` | Array of `{ ID_PERSON, PERSON_NAME, PROFILE_PATH, CREDIT_TYPE, CAST_CHARACTER, CREW_DEPARTMENT, CREW_JOB, DISPLAY_ORDER }` where `CREDIT_TYPE = 'crew'`, ordered by `DISPLAY_ORDER` |
| `stills` | Array of `{ ID_ROW, TYPE_IMAGE, IMAGE_PATH, LANG, ASPECT_RATIO, WIDTH, HEIGHT, VOTE_AVERAGE, VOTE_COUNT, DISPLAY_ORDER }` from `T_WC_TMDB_EPISODE_IMAGE`, ordered by `DISPLAY_ORDER`. TMDb episodes typically only carry still frames; any other `TYPE_IMAGE` rows stored upstream are surfaced as-is and can be filtered client-side. The episode's canonical frame is available directly on the base row as `STILL_PATH` |
| `season` | Object `{ ID_SEASON, SEASON_NUMBER, TITLE, POSTER_PATH }` for the parent season — navigation stub so the frontend can render breadcrumbs without a second `/seasons/{id_serie}/{season_number}` round trip |
| `series` | Object `{ ID_SERIE, SERIE_TITLE, POSTER_PATH }` for the parent series — second-level navigation stub |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on the episode's `ID_WIKIDATA`. Almost always empty — very few TMDb episodes have a Wikidata mapping |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the episode's `ID_WIKIDATA`. Almost always empty for the same reason |
| `wikipedia_page` | Resolved source article for `wikipedia_content`: `{ lang, title, url }` from `T_WC_WIKIPEDIA_PAGE_LANG`, using the same language resolution and the same page row that `data_freshness` dates (so `lang` always equals `data_freshness.wikipedia_lang`). **Absent**, not null, when there is no page. Required for CC BY-SA attribution when displaying `wikipedia_content` |
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
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the person's `ID_WIKIDATA`, filtered to the requested `ui_language` (English fallback when that language has no sections) and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_page` | Resolved source article for `wikipedia_content`: `{ lang, title, url }` from `T_WC_WIKIPEDIA_PAGE_LANG`, using the same language resolution and the same page row that `data_freshness` dates (so `lang` always equals `data_freshness.wikipedia_lang`). **Absent**, not null, when there is no page. Required for CC BY-SA attribution when displaying `wikipedia_content` |
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
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on the technical's `ID_WIKIDATA`, filtered to the requested `ui_language` (English fallback when that language has no sections) and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT`. Empty when `ID_WIKIDATA` is NULL |
| `wikipedia_page` | Resolved source article for `wikipedia_content`: `{ lang, title, url }` from `T_WC_WIKIPEDIA_PAGE_LANG`, using the same language resolution and the same page row that `data_freshness` dates (so `lang` always equals `data_freshness.wikipedia_lang`). **Absent**, not null, when there is no page. Required for CC BY-SA attribution when displaying `wikipedia_content` |

Base technical fields currently include `ID_TECHNICAL`, `ID_RECORD`, `ID_WIKIDATA`, `DESCRIPTION`, `DESCRIPTION_FR`, `OVERVIEW`, `TECHNICAL_TYPE` (one of `sound_system`, `color_technology`, `film_technology`, `sound_technology`, `film_format`), `MOVIE_COUNT`, `SERIE_COUNT`, `WIKIPEDIA_IMAGE_PATH`, `IMDB_RATING`, `IMDB_RATING_WEIGHTED`, and `POPULARITY`. No `series` array is returned because `T_WC_T2S_SERIE_TECHNICAL` does not exist yet.

##### `GET /genres/{id}`

Returns a genre from the closed-vocabulary reference table `T_WC_TMDB_GENRE`, identified by its TMDb genre code `ID_GENRE` (e.g. `28` = Action, `878` = Science Fiction, `18` = Drama), plus its member movies and TV series. Returns `404` when the genre code does not exist.

Because `T_WC_TMDB_GENRE` uses the legacy lowercase columns `id` / `name`, the base row is aliased to the API's canonical shape. Base genre fields are `ID_GENRE` (from `id`), `GENRE_NAME` (from `name`, localized to `ui_language` via `T_WC_TMDB_GENRE_LANG` with English fallback), `APPLIES_TO_MOVIE`, and `APPLIES_TO_SERIE` (the flags that say which side the genre is valid for — 8 codes apply to both).

| Field | Shape |
|---|---|
| `movies` | Array of `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH }` from `T_WC_T2S_MOVIE_GENRE` joined to `T_WC_T2S_MOVIE`, ordered by `IMDB_RATING_WEIGHTED DESC, ID_MOVIE ASC`. Empty for a TV-only genre |
| `series` | Array of `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH }` from `T_WC_T2S_SERIE_GENRE` joined to `T_WC_T2S_SERIE`, ordered by `IMDB_RATING_WEIGHTED DESC, ID_SERIE ASC`. Empty for a movie-only genre |

No `wikipedia_images` / `wikipedia_content` arrays are returned because `T_WC_TMDB_GENRE` has no `ID_WIKIDATA`. Both nested lists are paginated (`collection` = `movies` / `series`) and their `POSTER_PATH` is localized like every other nested movie/serie row.

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

##### `GET /locations/{id}`

Returns all `T_WC_T2S_LOCATION` fields for the location `ID_LOCATION`, plus the movies and series linked to it. Each related row carries `LOCATION_ROLE`, `'narrative'` (the story happens there) or `'filming'` (it was shot there). Until 1.1.18 this route took a Wikidata Q-id and the role travelled as the raw property code `P840` / `P915`.

| Field | Shape |
|---|---|
| `movies` | Array of `{ ID_MOVIE, MOVIE_TITLE, DAT_RELEASE, IMDB_RATING_WEIGHTED, POSTER_PATH, LOCATION_ROLE }`, ordered by `IMDB_RATING_WEIGHTED DESC` |
| `series` | Array of `{ ID_SERIE, SERIE_TITLE, DAT_FIRST_AIR, IMDB_RATING_WEIGHTED, POSTER_PATH, ID_PROPERTY }`, ordered by `IMDB_RATING_WEIGHTED DESC` |
| `wikipedia_images` | Array of `{ ID_ROW, LANG, SECTION_TITLE, IMAGE_URL, IMAGE_URL_NORMALIZED, THUMBNAIL_URL, MEDIA_TYPE, FILE_NAME, COMMONS_TITLE, CAPTION, ALT_TEXT, IS_MAIN_IMAGE, DISPLAY_ORDER }` from `T_WC_WIKIPEDIA_PAGE_LANG_IMAGE` joined on `ID_WIKIDATA` (the route parameter), filtered to `LANG IN ('en','fr')`, `DELETED = 0`, and `HTTP_STATUS = 200 OR HTTP_STATUS IS NULL`. Ordered by `IS_MAIN_IMAGE DESC, LANG ASC, DISPLAY_ORDER ASC` |
| `wikipedia_content` | Array of `{ title, content }` from `T_WC_WIKIPEDIA_PAGE_LANG_SECTION` joined on `ID_WIKIDATA` (the route parameter), filtered to the requested `ui_language` (English fallback when that language has no sections) and `DELETED = 0`, ordered by `DISPLAY_ORDER ASC`. Each element exposes the section `TITLE` and `CONTENT` |
| `wikipedia_page` | Resolved source article for `wikipedia_content`: `{ lang, title, url }` from `T_WC_WIKIPEDIA_PAGE_LANG`, using the same language resolution and the same page row that `data_freshness` dates (so `lang` always equals `data_freshness.wikipedia_lang`). **Absent**, not null, when there is no page. Required for CC BY-SA attribution when displaying `wikipedia_content` |

Base location fields currently include `ID_WIKIDATA`, `ITEM_LABEL`, `DESCRIPTION`, `INSTANCE_OF`, and `WIKIPEDIA_IMAGE_PATH`.

#### 4. Sample Questions

```http
GET /samples?ui_language=en
```

Returns the curated tree of suggested sample questions used by the front-end search/home panel ([`lib/text2sql-samples.inc.php`](../tmdb-front/lib/text2sql-samples.inc.php)), so clients without database access (e.g. the `voice-agent` repo) can render the same suggestions. Requires the same `X-API-Key` header as the other endpoints.

The tree is built from the evaluation tables: categories come from `T_WC_T2S_EVALUATION_CATEGORY` (rooted at `ID_PARENT = 1`, ordered by `DISPLAY_ORDER`), and the sample questions at each category are the `T_WC_T2S_EVALUATION` rows with `IS_SAMPLE = 1 AND DELETED = 0` (ordered by `DISPLAY_ORDER`). Categories that contain no sample anywhere in their subtree are pruned, matching the public (non-private) front-end behavior.

**Localization (`ui_language`)**: optional query parameter, `"en"` (default) or `"fr"` (any other value falls back to `"en"`). `DESCRIPTION` and `QUESTION` are returned under their canonical names carrying the requested language's value (English fallback when the French value is empty); the `*_FR` columns are not returned. Question text has its HTML entities decoded.

| Field | Shape |
|---|---|
| `ui_language` | Normalized language code actually used (`"en"` or `"fr"`) |
| `categories` | Array of category nodes (the children of the root), ordered by `DISPLAY_ORDER` |

Each **category node** has the shape:

```jsonc
{
  "ID_T2S_EVALUATION_CATEGORY": 12,
  "DESCRIPTION": "Movies",
  "categories": [ /* child category nodes (same shape, possibly empty) */ ],
  "samples": [ /* sample nodes, ordered by DISPLAY_ORDER */ ]
}
```

**Sample node — simulated result**: each sample carries not just the question but the *expected answer*, derived from the evaluation framework's ground-truth assertion (`ASSERTIONS_QUERY_RESULT`). This lets a client preview a realistic answer for a suggested question without running the Text2SQL pipeline. A sample node has:

- `ID_T2S_EVALUATION`, `QUESTION` (localized, HTML entities decoded);
- `assertion` — the parsed ground-truth spec (or `null` when the sample has no assertion):
  - `raw` — the original assertion string;
  - `result_kind` — one of `entity_rows` (assertion lists entity IDs), `scalar` (a known literal value), `count` (a cardinality expectation only), `bound` (an inequality/exclusion constraint), or `unknown`;
  - `entity_type` — for `entity_rows`: `movie` / `person` / `serie` / `topic` / `company` / `network` / `list` / `location` / `content`;
  - `expected_count`, `count_operator` — present when a `COUNT(...)` clause is in the assertion;
- `simulated_result` — a renderable simulation whose **row shape matches `/search/text2sql`** (`result` is a list of `{ index, data }`), or `null` when nothing is materializable:
  - **`entity_rows`** — the assertion IDs hydrated into display rows from the matching `T_WC_T2S_*` table (title/date/rating + poster or logo path, localized). `total_count` is the number of rows found (missing/deleted IDs are skipped). `location` IDs are `ID_LOCATION` resolved against `T_WC_T2S_LOCATION`; `content` is a movie+series union resolved movie-first then series, with a `MEDIA_TYPE` tag per row.
  - **`scalar`** — a single `{ index: 0, data: { <COLUMN>: <value> } }` (or `{ "VALUE": <v> }` for a `CELL(0,0)` assertion).
  - **`count` / `bound`** — `result: []` plus an `expectation` object (`{ aggregate|column|cell, operator, value }`); no rows are invented.

```jsonc
// entity_rows sample
{
  "ID_T2S_EVALUATION": 88,
  "QUESTION": "List movies directed by Sergio Leone and starring Clint Eastwood",
  "assertion": {
    "raw": "COUNT(*) == 3 AND ID_MOVIE IN (429, 938, 391)",
    "result_kind": "entity_rows", "entity_type": "movie",
    "expected_count": 3, "count_operator": "=="
  },
  "simulated_result": {
    "result_kind": "entity_rows", "entity_type": "movie", "total_count": 3,
    "result": [
      { "index": 0, "data": { "ID_MOVIE": 429, "MOVIE_TITLE": "...", "DAT_RELEASE": "...", "IMDB_RATING_WEIGHTED": 7.9, "POSTER_PATH": "/...jpg" } }
      /* one entry per ID, in assertion order */
    ]
  }
}

// scalar sample
{
  "ID_T2S_EVALUATION": 11,
  "QUESTION": "What character did Harrison Ford play in Star Wars?",
  "assertion": { "raw": "CAST_CHARACTER == 'Han Solo'", "result_kind": "scalar" },
  "simulated_result": { "result_kind": "scalar", "total_count": 1,
    "result": [ { "index": 0, "data": { "CAST_CHARACTER": "Han Solo" } } ] }
}

// count sample
{
  "ID_T2S_EVALUATION": 2165,
  "QUESTION": "List Sci-Fi movies released in the fifties",
  "assertion": { "raw": "COUNT(*) > 0", "result_kind": "count", "expected_count": 0, "count_operator": ">" },
  "simulated_result": { "result_kind": "count", "result": [],
    "expectation": { "aggregate": "COUNT(*)", "operator": ">", "value": 0 } }
}
```

The assertion DSL is parsed by [`samples_assertions.py`](samples_assertions.py); the `eval/data/evaluation*` JSON exports mirror the live tables and can be used to simulate this endpoint's output offline.

#### 5. Vision Image Deposit

```http
POST /uploads/vision
GET  /uploads/vision/{image_ref}
```

The first binary input path of this API (FASTAPI-TEXT2SQL-275). It receives the photo that the
vision task will read, files it under a name of our own, and gives back the reference that names
it everywhere afterwards. It identifies nothing by itself: recognition is FASTAPI-TEXT2SQL-114.

**The body is the image itself**, raw bytes, not a multipart form and not base64. A browser sends
a `File` or a `Blob` as the body and nothing else is needed:

```bash
curl -X POST -H "X-API-Key: $KEY" --data-binary @poster.jpg      https://www.vaugouin.com/uploads/vision
```

```json
{
  "image_ref": "20260920-084157_vision_1.1.19_c158099afc031554d3bb2133375c6f11.jpg",
  "bytes": 204,
  "image_format": "jpg",
  "deposited_at": "2026-09-20T08:41:57",
  "purge_after": "2026-10-20T08:41:57",
  "retention_days": 30,
  "api_version": "1.1.19"
}
```

`image_ref` is the bare filename, and it is the only thing a client ever holds: it goes back with
the later turns of a conversation, and it is what the JSON log of the turn records. **The image is
never written into the log**, only its name, which is how a question asked about a photo can be
replayed from its log file alone.

**What decides what, and what decides nothing.** The format comes from the magic number of the
payload; the declared `Content-Type` is not read at all, so a GIF announced as `image/jpeg` is
refused with 415. No filename travels with a raw body, so no filename can decide a path or an
extension. The name on disk follows the house convention of [logs.py](logs.py), with the hash
taken over the bytes: `YYYYMMDD-HHMMSS_vision_<version>_<md5>.<ext>`.

| Case | Answer |
| --- | --- |
| valid JPEG or PNG | `200` with the `image_ref` |
| bytes that are neither, whatever the header says | `415` |
| empty body | `400` |
| past `MAX_UPLOAD_IMAGE_BYTES` (25 MB by default) | `413`, streamed and refused without writing to disk |
| `GET` with a reference that is not one of ours | `400` |
| `GET` on an image past its 30 days | `410`, with the deposit date and the purge stated |
| `GET` on a missing image still inside its window | `404`, which points at the mount, not at the purge |

The `GET` exists for the replay, and it is the two-command proof that the `uploads/` mount is
really shared: deposit on blue, read from green. See
[Vision uploads: a folder with the opposite regime to `logs/`](#vision-uploads-a-folder-with-the-opposite-regime-to-logs).

**MCP carries no bytes.** The MCP server mounted on this same app is JSON only, so an MCP client
passes an `image_ref` that was deposited here first. That is the boundary of the design, not a
gap to fill later.

**What to do with the `image_ref` afterwards.** Send it as the `image_ref` field of an ordinary
`POST /search/text2sql`, with or without a question beside it. There is no second search route:
the deposit is what needed a content type of its own, and it has one. See the vision pre-stage
in *Query Processing Pipeline*, and `vision_evidence` in the response fields.

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
  -v /home/debian/docker/shared_data/fastapi-text2sql/logs:/app/logs \
  --name fastapi-text2sql-blue \
  fastapi-text2sql-blue-app
```

The provided helper scripts ([restart-blue.sh](restart-blue.sh), [restart-green.sh](restart-green.sh)) already use this pattern — the host env files are expected at `/home/debian/docker/fastapi-text2sql-blue/.env` and `/home/debian/docker/fastapi-text2sql-green/.env` respectively.

### The second mount: one log folder for every colour

The first mount carries the code. The second carries the **log corpus**, and it exists because without it there is no corpus, there are three. `LOGS_FOLDER` is the relative `"logs"` ([logs.py](logs.py)), so an unmounted container writes inside its own stack directory: blue into `fastapi-text2sql-blue/logs`, green into `fastapi-text2sql-green/logs`, and the third, colourless deployment into `fastapi-text2sql/logs`. Every analysis over "the logs" was then silently reading a third of them.

`-v /home/debian/docker/shared_data/fastapi-text2sql/logs:/app/logs` puts all three in one place. **No code changed for this** (FASTAPI-TEXT2SQL-276): the path stays relative, the application knows nothing about the mount, and a checkout on a laptop still writes to its own `logs/` exactly as before.

Two operational consequences, neither optional:

- **Create the host directory before the first run.** [restart-blue.sh](restart-blue.sh) / [restart-green.sh](restart-green.sh) do it with `mkdir -p`. Left to Docker, the directory appears **root-owned**, and [archive-logs.sh](archive-logs.sh) can then no longer delete the loose originals it has just archived, which is exactly how a log directory reaches 17 842 files.
- **The archiver becomes more critical, not less.** One directory now fills at the rate of the three combined, so the monthly cron is what keeps the mirror listing fast. Check that it really runs *after* the switch, not only before.

The one-shot merge of the three historical directories is [migrate-logs-to-shared.sh](migrate-logs-to-shared.sh); see [Archiving old logs](#archiving-old-logs).

### The third mount: the vision uploads, shared and purged

`-v /home/debian/docker/shared_data/fastapi-text2sql/uploads:/app/uploads` (FASTAPI-TEXT2SQL-275)
is the same move as the log mount, for the same reason, with the opposite retention. `UPLOADS_FOLDER`
is the relative `"uploads"` ([uploads.py](uploads.py)), so again no code knows about the mount and a
laptop checkout keeps its own folder.

Why it cannot live inside a colour's stack directory: an image deposited on blue would be
unreadable from green after a flip, and a replay would then fail **in silence**, which is worse
than a failure that shows. The restart scripts create `uploads/vision` on the host before the
first run, for the same ownership reason as `logs/`.

The two folders are neighbours under `shared_data/fastapi-text2sql/` and obey **inverse** rules,
so the rule belongs on each folder and never on their parent:

| | `logs/` | `uploads/` |
| --- | --- | --- |
| Retention | indefinite, monthly archives | **30 days**, sliding, by [purge-uploads.sh](purge-uploads.sh) |
| Backup | **yes**, it is a dataset | **no**: an archive would outlive the purge and cancel it |
| Off-box mirror | yes | **no**, excluded in `sync_exclude.conf` |

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
├── uploads.py               # Vision-mode image deposits: magic-number check, house filename, 30-day retention, safe image_ref parsing (FASTAPI-TEXT2SQL-275)
├── sql_cache.py             # SQL cache lookups and cache writes for exact/anonymized questions
├── vision_cache.py          # Recognition cache of the picture-based search: keyed on the MD5 of the image bytes, its own table, degrades to a silent miss before the migration runs (FASTAPI-TEXT2SQL-114)
├── auth.py                  # API key authentication middleware (multi-key support via API_KEYS)
├── logs.py                  # API usage logging (JSON log files in logs/ folder)
├── data_watcher.py          # File-system watcher for hot-reloading data/ files
├── language_family.py       # Latin vs non-Latin script detection for person name routing
├── rapidfuzz_query.py       # RapidFuzz + MariaDB/MySQL lexical matching utilities
├── cleanup.py               # Cache cleanup functions (ChromaDB and SQL)
├── requirements.txt         # Python dependencies
├── Dockerfile               # Docker configuration for containerized deployment
├── .env.example             # Example environment variables template
├── .env                     # Environment variables (create from .env.example)
├── LICENSE                  # Project license file
├── restart-blue.sh          # Blue deployment restart script
├── restart-green.sh         # Green deployment restart script
├── archive-logs.sh           # Monthly log archiver (cron): packs past months into logs/archive/
├── migrate-logs-to-shared.sh # One-shot merge of the three old per-stack log dirs
├── purge-uploads.sh          # Daily 30-day purge of uploads/vision (cron): deletes, unlike archive-logs.sh
├── data/                    # Hot-reloaded prompt templates and configuration (see data/AGENTS.md before editing one: what each file must keep, and the rules twinned between two prompts)
│   ├── entity_extraction.md                                          # Entity extraction prompt (hot-reloaded)
│   ├── text_to_sql.md                                                # Text2SQL prompt (hot-reloaded)
│   ├── complex_question.md                                           # Stronger model prompt (complex question simplification, hot-reloaded)
│   ├── vision_identification.md                                      # Image-reading prompt: what the picture shows and which work it points at (hot-reloaded)
│   ├── entity_resolution.json                                        # Entity resolution configuration (embeddings + rapidfuzz, hot-reloaded)
│   └── closed_vocabularies.json                                      # Closed-vocabulary aliases for Movie_genre, Serie_genre, Technical_format, Status_name, Serie_type, Department_name (hot-reloaded)
├── eval/                    # Evaluation harness (see eval/README.md)
│   ├── text2sql-eval.py                                              # End-to-end evaluator against the running API
│   ├── verif-275.sh                                                  # Checks the vision upload path against a running deployment (cross-colour read included)
│   ├── verif-114.py                                                  # Checks the deterministic half of the picture-based search: composition, confidence rule, cache contract (no API, no DB, no image)
│   ├── bench-entity-extraction.py                                    # Offline A/B comparison of two extraction configurations
│   ├── bench-entity-resolution.py                                    # Offline bench that calibrates the entity-resolution thresholds
│   ├── harvest-archived-entities.py                                  # Harvests entity values from the archived VPS logs
│   └── verif-206.sh                                                  # Three-question production probe of the resolution measurement
├── doc/                     # Reference documentation (see doc/AGENTS.md for the index)
│   ├── entity-resolution-thresholds.md                               # How each min_fuzz_ratio was measured, and how to redo it
│   ├── MCP.md                                                        # MCP integration guide (tools, resources, deployment, Claude connector)
│   ├── RAPIDFUZZ.md                                                  # RapidFuzz module documentation
│   ├── SEASONS_AND_EPISODES.md                                       # Seasons and episodes endpoints, their source tables and open gaps
│   ├── EXTEND_T2S_TECHNICAL.md                                       # Technical_format extension: schema, prompt and resolver changes
│   ├── closed-vocab-entity-plan.md                                   # Closed-vocabulary entity rollout plan
│   └── sql/                 # Reference SQL dumps for canonical tables
│       └── T_WC_T2S_TECHNICAL.sql                                    # 56-row Technical_format canonical table
├── logs/                    # API usage logs with timing metrics (auto-created; on the VPS a bind mount onto shared_data/fastapi-text2sql/logs, shared by every colour)
├── CLAUDE.md                # AI assistant guide for understanding the codebase
└── README.md                # This file
```

**Key Architecture Components:**
- **ChromaDB Integration**: Vector database for entity matching and similarity search with 15 entity collections (`persons`, `movies`, `series`, `companies`, `networks`, `topics`, `t2slocations`, `groups`, `characters`, `lists`, `collections`, `deaths`, `awards`, `nominations`, `movements`) plus a separate `anonymizedqueries` cache collection. `t2slocations` is opened with `get_collection`, never `get_or_create_collection`: its HNSW configuration is fixed at creation by `embedding-update`, and whoever creates the collection first decides it for every reader. The separate `anonymizedqueries` cache collection is disabled by default (`USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE = False` in [main.py](main.py))
- **Multi-Level Caching**: SQL cache + embeddings cache for performance optimization with automatic cleanup
- **Entity Extraction**: `entity.py` handles GPT-powered entity recognition and anonymization for supported entity types
- **Fork-Join Scheduling**: entity resolution runs in a worker thread while the text-to-SQL call is in flight (`ENTITY_RESOLUTION_PARALLEL`), since it depends only on the extraction output
- **Unified LLM Dispatch**: `text2sql.py` routes to OpenAI (native SDK), Anthropic (native `anthropic` SDK), or Google Gemini (`google-generativeai`) based on model name
- **Vision Pre-stage**: with an `image_ref`, `text2sql.py` reads the image (OpenAI route only), the code composes the question deterministically from what was identified, and the ordinary pipeline answers it. The identification is cached on the fingerprint of the bytes (`vision_cache.py`), so the same photo is never read twice
- **Reasoning Retry Helpers**: `text2sql.py` contains stronger-model calls and retry-question construction helpers
- **Endpoint Orchestration**: `main.py` coordinates request flow, recursive retry execution, and response/message merging
- **Entity Detail Endpoints**: 18 endpoints returning full entity data with embedded relations, each with usage logging
- **MCP Server**: FastMCP 2.x tools and resource exposed at `/mcp` for Claude clients (see `doc/MCP.md`)
- **Blue/Green Deployment**: Automatic port selection based on API version (even: port 8000, odd: port 8001)
- **Processing Transparency**: Messages array tracks every processing step for debugging and analysis
- **Version Management**: Utility functions for version comparison and automatic cache cleanup

## 🔧 Configuration

### API Version
The API version is controlled by the `strapiversion` variable in `main.py`. Update this when making changes to the prompt templates.

### Prompt Templates
The system uses prompt templates stored in the `data/` folder. `text2sql.py` loads the Text2SQL and complex-question templates, and `entity.py` loads the entity-extraction template.

Files in the `data/` folder are hot-reloaded. If you modify `entity_extraction.md`, `text_to_sql.md`, `complex_question.md`, or `entity_resolution.json`, the running API automatically picks up the changes without requiring a restart. Every file listed there must exist on disk at startup: the watcher reads each of them eagerly when the module is imported, so a missing one stops the API from booting.

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
- **Locations** (`T_WC_T2S_LOCATION` joined via `T_WC_T2S_MOVIE_LOCATION` / `T_WC_T2S_SERIE_LOCATION`, `LOCATION_ROLE` `'narrative'` or `'filming'`): places a movie or series is linked to
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

#### 4. **Recognition Cache (images, `T_WC_T2S_VISION_CACHE`)**
- Keyed on the **MD5 of the image bytes**, which the deposit filename already carries, plus the API version. The same photo re-deposited therefore gets a new name and the same key.
- Stores only what depends on the image and not on the question (the clues, the candidates, the authoritative-empty flag), so **one row answers any later question about that photo**.
- A photo with nothing of cinema in it **is** cached, unlike an empty SQL result: it will still be a photo of a meal tomorrow, and that is the case where the cache most reliably avoids a pointless spend.
- Survives the 30-day image purge, because the key is the fingerprint and not the file. It then serves the identification, never the pixels.
- Governed by the same `retrieve_from_cache` / `store_to_cache` request flags as the three tiers above. Its table is created by `maintenance/vision-recognition-cache.sql`, run in production on 2026-09-20. Should the table ever be absent (another database, a dropped table), the module degrades to a silent miss and the picture-based search works uncached rather than failing.

#### What is never cached: an empty result

A query that returns **0 rows on page 1** is not written to any of the three question tiers. An empty result is precisely where the odds that the SQL is wrong, rather than the
data genuinely absent, are at their highest, and caching one does not merely freeze the
question that produced it: the anonymized row freezes the whole **template**.

Measured on 2026-08-25. "Qui est la costumière du film Capote avec Philip Seymour Hoffman ?"
produced a query that asked for a costume designer on condition she be Philip Seymour
Hoffman, empty by construction. It was written to cache at 18:05:03 and served back
verbatim at 18:06:36 without ever being regenerated. Left alone, every film/actor pair on
the pattern `La costumière du film {{Movie_title1}} avec {{Person_name1}}` would have
answered 0 rows for as long as the row lived.

The cost of the rule is one regeneration per legitimately empty question. Set
`CACHE_EMPTY_RESULTS=1` to restore the previous behaviour. A page beyond the first coming
back empty is not affected: that only means the result set ended.

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
| `Location_name` | Places a movie or series is linked to | Embeddings — `t2slocations` collection |
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
4. Generate SQL if not cached, while the entities are already being resolved in parallel (see *Parallel entity resolution* below)
5. Resolve each placeholder to a real DB value using the per-prefix `search_list` in [data/entity_resolution.json](data/entity_resolution.json) (embeddings or RapidFuzz, with optional language-family gating)
6. Substitute resolved values back into `sql_query`, `justification`, and `answer`, using SQL-safe `''` quote escaping

#### Parallel entity resolution

Entity resolution (step 5) depends only on the extraction output, never on the generated SQL: the resolver iterates over the extracted key/value pairs, and the SQL appears only at the very end as the target of a string substitution. Steps 4 and 5 are therefore run concurrently — the resolution starts in a worker thread just before the text-to-SQL call and is joined right after it, so only the substitution itself waits for the SQL.

On 371 logged requests, resolution costs 0.245 s at the median but more than one second on 16% of requests and more than two on 6%. Hiding it behind the text-to-SQL call is worth about 5% of median latency and considerably more in that tail. Set `ENTITY_RESOLUTION_PARALLEL=0` to fall back to the strictly sequential path; results are identical either way.

`embeddings_processing_time` still reports what the resolution cost, overlapped or not, so the metric stays comparable across versions. The saving shows up in `total_processing_time`.

The full pipeline is implemented in [entity.py](entity.py) (resolver dispatch, regex-validated placeholders, embeddings, RapidFuzz person resolution, generic fallback replacement) plus [closed_vocab.py](closed_vocab.py) (DB-driven closed-vocabulary lookups for `Movie_genre`, `Serie_genre`, `Technical_format`, `Status_name`, `Serie_type`, `Department_name` with RapidFuzz typo tolerance and JSON-driven alias layering).

If the user provides a disambiguation pattern like `<movie_title> (YYYY)`, entity extraction returns a `{{Release_yearN}}` placeholder alongside the `{{Movie_titleN}}` placeholder so the SQL can disambiguate same-titled films by release year.

**Year semantics: one tolerant case, everything else strict.** A year attached to a named title (`<title> (YYYY)`, "the X movie of 1936") is a *discriminant*, and it is the only case where the generated SQL widens the year to `RELEASE_YEAR BETWEEN Y-1 AND Y+1`: a film can legitimately be dated by its closing-credits copyright, by a festival premiere a year earlier, or by a theatrical release that varies per country, and the ±1 absorbs that gap. Every other year is a *filter* and keeps strict bounds. A decade ("the seventies", "les années 70") becomes `BETWEEN 1970 AND 1979` and never 1969/1980, "before 1960" and "after 2010" stay plain inequalities, and person years (`BIRTH_YEAR`, `DEATH_YEAR`) are never widened since a birth date has only one version. The rules, the column map (`RELEASE_YEAR`, `FIRST_AIR_YEAR`, `BIRTH_YEAR`, `DEATH_YEAR`) and the phrasing tables live in the "Years, decades and date ranges" section of [data/text_to_sql.md](data/text_to_sql.md).

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

On the VPS, `logs/` is a bind mount onto `/home/debian/docker/shared_data/fastapi-text2sql/logs`, shared by **every** deployment (blue, green, and the colourless third one). The application still writes to the relative `logs/` and is unaware of it, so on a local checkout the folder is the one in the repository. A log file therefore says which colour served it by its **version component**, never by its location.

#### Why these logs are kept: a usage & agent-behaviour dataset

The `logs/` folder is **not** transient debug output — it is a permanent,
append-only record of **every** API call, intentionally retained and mirrored
off-box. It is meant to be **studied**, not just tailed when something breaks.
Each `text2sql_post` file captures the full request *and* the full response
(generated SQL, anonymized SQL, resolved entities, `answer`, `messages` trace,
per-stage timings, cache-hit flags, model used, `complex_model_used`, errors),
so the corpus supports analysis of:

- **Query behaviour** — what users/agents actually ask, how questions get
  anonymized, which entities are extracted and how they resolve.
- **Result & error quality** — ambiguous-question cases, empty result sets,
  SQL execution errors, stronger-model escalations, provider rate-limit (429) hits.
- **Cache & cost** — exact/anonymized/embedding hit rates and how often the
  stronger model is actually invoked.
- **Drift over time** — the version in each filename lets you compare behaviour
  across API versions.

**Agent observability (primary use case).** The main client of this API is an
LLM agent (the `voice-agent` repo). Because every tool invocation is logged, the
corpus is an exact record of **what the agent sent** when it called the search
tool (`POST /search/text2sql`) or an entity-retrieval endpoint (`/movies/{id}`,
`/persons/{id}`, …) — the literal question text, parameters, and the response it
got back. This is the ground truth for debugging and improving agent tool-use:
mismatches between what the agent *meant* and what it *asked*, redundant calls,
malformed parameters, and which tools it favours.

> ⚠️ **Retention policy: do not auto-prune or exclude from backup.** These files
> are a dataset. They are mirrored to the off-box backup on purpose. Do not add
> log rotation, a `find -delete` cron, or a backup/sync exclude for `*/logs/`
> without first archiving the corpus — doing so silently discards the usage
> history this analysis depends on. The files are small JSON; volume (tens of
> thousands) is expected and acceptable. If the live directory grows large enough
> to slow tooling, **archive** old logs rather than deleting them —
> [`archive-logs.sh`](archive-logs.sh) does exactly that (see
> [Archiving old logs](#archiving-old-logs) below).
>
> ⚠️ **Sensitivity:** these files contain full natural-language queries and
> responses, which may include personal or otherwise sensitive content. Treat the
> corpus (and its off-box mirror) as private; don't share casually.
>
> ⚠️ **The regime belongs to `logs/`, not to its parent.** Now that the corpus
> sits under `shared_data/fastapi-text2sql/` it has neighbours, and they do not obey
> the same rules: `logs/` is backed up, mirrored and kept without a time limit, while
> the vision-mode `uploads/` folder due beside it is neither backed up nor mirrored.
> A backup or sync rule written on the **parent** is therefore wrong for one of the
> two whichever way it is written. Write it on each subfolder.

#### Merging the three old log directories (one-shot)

Before FASTAPI-TEXT2SQL-276 each deployment wrote into its own stack directory, so the corpus existed in three copies of three different thirds. [migrate-logs-to-shared.sh](migrate-logs-to-shared.sh) merges them into the shared folder. **The merge is the work, not the mount**, because of one collision that destroys data if it is ignored:

- **The monthly archives share their names.** `archive-logs.sh` writes `logs/archive/<YYYYMM>.tar.gz` in each directory, so blue's `202608.tar.gz` and green's are two different files carrying one name; a plain `mv` or `cp` silently keeps one. The script concatenates their members into a single archive per month and refuses to move on unless the merged member count equals the sum of the sources'.
- **The loose files could collide, and in practice do not.** Their name is `YYYYMMDD-HHMMSS_<endpoint>_<version>_<md5>.json`, and the colours run different versions, so the version component separates them. A real collision means same second, same version and same payload hash, i.e. the same request logged twice; the script still compares the contents rather than assuming it, keeps one copy, and aborts without writing anything if the two differ.

```bash
./migrate-logs-to-shared.sh                        # dry run: inventory + collision report
sudo ./migrate-logs-to-shared.sh --apply           # merge the archives, move the loose files
sudo ./migrate-logs-to-shared.sh --prune-sources   # drop the source archives, once re-read
                                                   # out of the merged one
```

It is idempotent: a month is merged into a temporary file and moved into place only after its member count is verified, so it is either complete or absent, and a second run skips what is done. `--prune-sources` is a separate step on purpose: nothing is deleted before the merged archive has been proved to contain it.

#### Archiving old logs

`archive-logs.sh` keeps the **live** `logs/` directory small without losing any
data. It packs every **past month's** `*.json` files into
`logs/archive/<YYYYMM>.tar.gz`, verifies the archive, then removes the loose
originals. The **current** (and any future) month is left untouched, so in-flight
logging is never disturbed. It is idempotent and re-runnable — an existing
monthly archive is merged with any stragglers, and only files strictly older than
the current month are ever touched.

```bash
# Archive the shared log dir (the single default since FASTAPI-TEXT2SQL-276):
./archive-logs.sh
# Or target specific dirs (the retired stack dirs, if anything is ever found in them):
./archive-logs.sh /home/debian/docker/fastapi-text2sql-blue/logs

# Run monthly via cron (1st of the month, 03:30). The container logs as root, so the
# run needs sudo to delete the loose originals after archiving:
# 30 3 1 * * sudo /home/debian/docker/fastapi-text2sql-blue/archive-logs.sh \
#   >> /home/debian/docker/shared_data/fastapi-text2sql/logs/archive-run.log 2>&1
```

Note the redirect target: `logs/archive-run.log`, **not** `logs/archive/archive.log`. The shell
opens the redirect before running the command, so a target inside a directory the script has yet
to create can never work, which is one of the two reasons the archiver had never run once on
the blue deployment before 2026-08-21 (the other was a missing executable bit).

This is what lets the off-box mirror keep pace: once old logs are compressed into
a handful of monthly tarballs, the remote directory listing stays fast and the
additive sync just pulls the new archives plus the current month's loose files.
**The archives are part of the dataset and are mirrored** — they are not excluded
from backup. (Off-box mirroring is handled by `sync_vps_docker.py` in the
`tmdb-front` repo under `%USERPROFILE%/Nestor/projets/t2s-backlog/topics/debian-migration/`, whose SFTP timeouts were raised
so large log directories don't abort a sync mid-listing.)

### Vision uploads: a folder with the opposite regime to `logs/`

Images deposited on `POST /uploads/vision` land in `uploads/vision/` (FASTAPI-TEXT2SQL-275), on
the VPS a bind mount onto `/home/debian/docker/shared_data/fastapi-text2sql/uploads`, shared by
every colour. Everything about this folder is the reverse of `logs/`, deliberately: a visitor's
photo is not a request log, and Philippe set its retention at 30 days on 2026-09-19.

```bash
./purge-uploads.sh --dry-run      # list what would go, delete nothing
./purge-uploads.sh                # delete images older than 30 days in the shared dir
./purge-uploads.sh --days 7 /some/other/uploads/vision

# Daily cron, 03:50 (twenty minutes after the archiver's monthly slot, so the two never
# overlap on the 1st). ONE cron for the machine, not one per colour: the folder is shared,
# and a cron in each stack would purge the same files three times.
# 50 3 * * * /home/debian/docker/fastapi-text2sql-blue/purge-uploads.sh #   >> /home/debian/docker/shared_data/fastapi-text2sql/uploads/purge-run.log 2>&1
```

**It is a separate script from [archive-logs.sh](archive-logs.sh), and must stay one.** That one
advertises, in its own header, that it archives *without deleting any data*. Folding a deletion
into a tool whose promise is that it loses nothing would be a trap for the next reader.

**Three things the purge must never reach**, which is what the `vision/` level under `uploads/`
buys: the run log of the purge itself (it sits in `uploads/`, not in `uploads/vision/`), the
`logs/` folder (a guard refuses any directory whose path does not end in `uploads/vision`), and
the evaluation fixtures of the vision bench, which live versioned in the `voice-agent` repo and
must never be dropped here "just for now".

**The image is purged, the log that names it is not.** A replay attempted more than a month later
is therefore expected to fail, and it fails with a sentence and a date (`410 Gone`), never with a
stack trace. That is the likeliest error case of the whole device, and it is the one that had to
read well.

**Not backed up, not mirrored, and that has to be written down.** A backup would let a photo
survive its thirty days and the retention would mean nothing; the off-box mirror keeps
`shared_data` by default, so the host path is excluded explicitly in `sync_exclude.conf`. Both
exclusions are stated on the `uploads/` folder, never on `shared_data/fastapi-text2sql/`, which
also holds `logs/` and its exactly opposite regime.

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

Beyond troubleshooting, these logs are a **retained usage & agent-behaviour dataset** — see [Why these logs are kept](#why-these-logs-are-kept-a-usage--agent-behaviour-dataset) under the Logging section before pruning or excluding them from backup.

## 📝 API Response Format

Every field of a `/search/text2sql` response is documented once, under [Text to SQL Conversion](#2-text-to-sql-conversion): the example payload, then **Response Fields** grouped into core fields, performance metrics, pagination, cache indicators and configuration. A second, shorter copy used to sit here and had fallen twelve fields behind the list it copied (`result_entity`, `name_ambiguity`, `dropped_clause`, the four error-handling fields and five more), so it was deleted rather than repaired. Per-version feature notes now live in the git history, which is the only place they cannot drift.

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
- **Reference documentation**: everything long-form lives in [doc/](doc/), indexed by [doc/AGENTS.md](doc/AGENTS.md). Start there rather than guessing a filename
- **Entity resolution thresholds**: [doc/entity-resolution-thresholds.md](doc/entity-resolution-thresholds.md) explains how every `min_fuzz_ratio` was measured, what data was used, and how to redo it for a new entity. Read it before changing a value by hand
- **MCP Integration Guide**: See `doc/MCP.md` in this repository

---

**Note**: This API requires an active OpenAI API key to function. Make sure you have sufficient credits in your OpenAI account for the text-to-SQL conversions.

For detailed technical documentation and AI assistant guidance, see [CLAUDE.md](CLAUDE.md).
