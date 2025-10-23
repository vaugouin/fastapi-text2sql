# FastAPI Text2SQL API

A powerful FastAPI-based REST API that converts natural language questions into SQL queries using OpenAI's language models and LangChain.

## 🚀 Features

- **Natural Language to SQL**: Convert plain English questions into SQL queries using OpenAI's GPT-4o
- **FastAPI Framework**: High-performance, modern Python web framework
- **API Key Authentication**: Secure access with API key validation
- **ChromaDB Vector Search**: Advanced similarity search for entity matching and query optimization
- **Entity Extraction**: Intelligent extraction and anonymization of entities (persons, movies, series, companies)
- **Multi-Level Caching**: Three-tier caching system (exact questions, anonymized questions, vector embeddings)
- **Comprehensive Logging**: Automatic logging of all API requests and responses with detailed timing metrics
- **Memory Monitoring**: Built-in system memory usage tracking
- **Pagination Support**: Built-in pagination with configurable page sizes
- **Robust Error Handling**: Enhanced error handling for malformed responses and SQL escaping issues
- **Docker Support**: Containerized deployment ready
- **UTF-8 Support**: Proper handling of Unicode characters in queries and logs

## 📊 Database Scale

The API operates on a comprehensive entertainment database containing:
- **Movies**: More than 620,000 entries
- **Series**: More than 88,000 entries
- **Persons**: More than 890,000 entries (actors, directors, crew members)

## 🔄 Query Processing Pipeline

The API implements a sophisticated multi-stage pipeline to efficiently convert natural language questions into SQL queries. The pipeline leverages multiple caching layers and entity extraction to maximize performance and accuracy:

### Pipeline Steps

1. **Exact Question Cache Lookup (SQL Database)**
   - Search for the exact user question in the SQL cache (`T_WC_T2S_CACHE` table)
   - If found, return the cached SQL query immediately
   - This cache is also used for efficient pagination through result pages

2. **Entity Extraction & Anonymization**
   - If not found in exact cache, extract and anonymize entities from the user question using GPT-4o
   - Entities extracted include:
     - Person names (actors, directors, crew)
     - Place names
     - Movie titles
     - TV series titles
     - Company names
     - Network names
     - Years and temporal references
   - Replace entities with placeholders (e.g., `{{PERSON_NAME}}`, `{{MOVIE_TITLE}}`)

3. **Anonymized Question Cache Lookup (SQL Database)**
   - Search for the anonymized question pattern in the SQL cache
   - Enables reuse of SQL logic across similar questions with different entity values
   - Example: "Movies with Brad Pitt" and "Movies with Tom Cruise" share the same anonymized pattern

4. **Embeddings Cache Search (ChromaDB)**
   - If not found in SQL caches, search for similar anonymized questions in the vector embeddings cache
   - Uses semantic similarity matching with OpenAI's `text-embedding-3-large` model
   - **Similarity threshold**: Distance < 0.1 (configurable)
   - Returns cached SQL query if a sufficiently similar question is found

5. **Entity Validation & Resolution**
   - Validate and resolve each extracted entity using specialized SQL tables and ChromaDB collections:
     - **Person names**: Search in `persons` collection/table
     - **Places**: Search in relevant location tables
     - **Movie titles**: Search in `movies` collection with multi-language support
     - **TV series titles**: Search in `series` collection
     - **Company names**: Search in `companies` collection
     - **Network names**: Search in `networks` collection
     - **Years**: Validate temporal references
   - Vector similarity matching ensures fuzzy matching for misspellings and variations

6. **Text-to-SQL Generation (LLM)**
   - If no cache hit occurs, process the anonymized question through the LLM model
   - Uses the prompt template from `data/` folder with comprehensive database schema
   - GPT-4o generates a SQL query based on the anonymized question pattern
   - This is the core text-to-SQL task

7. **Query De-anonymization**
   - Replace placeholders in the generated SQL query with actual validated entity values
   - Apply parameters from the entity extraction step (person names, movie titles, etc.)
   - Produce the complete, executable SQL query with proper SQL escaping

8. **SQL Query Execution**
   - Execute the final SQL query on the MariaDB/MySQL database
   - Apply pagination parameters (page size, offset)
   - Return the result set with timing metrics

9. **Cache Population**
   - **Exact question cache**: Save the original question and SQL query to `T_WC_T2S_CACHE` (if applicable)
   - **Anonymized question cache**: Save the anonymized question and SQL pattern to SQL cache (if applicable)
   - **Embeddings cache**: Save the anonymized question embedding and SQL query to ChromaDB for future semantic searches

10. **Result Return**
    - Return the result set to the client with comprehensive metadata:
      - Generated SQL query
      - Query results (paginated)
      - Performance metrics (entity extraction time, text2SQL time, embeddings time, query execution time)
      - Cache hit indicators
      - Pagination information

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
   # API Key for authentication
   API_KEY=your_api_key_here
   # OpenAI API Key for Text2SQL conversion
   OPENAI_API_KEY=your_openai_api_key_here
   
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
   ```

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
  "retrieve_from_cache": true,
  "store_to_cache": true,
  "llm_model": "default"
}
```

**Request Parameters:**
- `question` (optional): Natural language question to convert to SQL
- `question_hashed` (optional): SHA256 hash of a previously processed question for pagination
- `page` (optional, default: 1): Page number for pagination
- `disambiguation_data` (optional): Additional context for ambiguous queries
- `retrieve_from_cache` (optional, default: true): Whether to check cache for existing results
- `store_to_cache` (optional, default: true): Whether to store results in cache
- `llm_model` (optional, default: "default"): LLM model to use

**Example:**
```bash
curl -X POST "http://localhost:8000/search/text2sql" \
     -H "X-API-Key: your_api_key" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "List all color movies with Humphrey Bogart",
       "page": 1,
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
  "llm_model": "default",
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

## 💡 Sample Usage Examples

Based on real API usage data, here are examples of natural language questions the API can successfully convert to SQL:

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

**Note**: Questions can be expressed in English or any language understood by the underlying LLM (currently OpenAI's models). The API can handle complex multi-criteria searches involving actors, directors, genres, years, ratings, and technical specifications for both movies and TV series.

## 🐳 Docker Deployment

The project includes a `Dockerfile` for containerized deployment:

```bash
docker build -t fastapi-text2sql .
docker run -p 8000:8000 fastapi-text2sql
```

## 📁 Project Structure

```
fastapi-text2sql/
├── main.py              # FastAPI application, endpoints, and ChromaDB integration
├── text2sql.py          # Core text-to-SQL conversion and entity extraction logic
├── auth.py              # API key authentication
├── requirements.txt     # Python dependencies
├── Dockerfile          # Docker configuration
├── .env                # Environment variables (create this)
├── data/               # Prompt templates and configuration
│   └── prompt-chatgpt-4o-1-0-10-20250728.txt  # Current prompt template
├── logs/               # API usage logs with detailed timing metrics (auto-created)
└── README.md           # This file
```

**Key Architecture Components:**
- **ChromaDB Integration**: Vector database for entity matching and similarity search
- **Multi-Level Caching**: SQL cache + embeddings cache for performance optimization
- **Entity Extraction**: GPT-4o powered entity recognition and anonymization
- **Blue/Green Deployment**: Automatic port selection based on API version

## 🔧 Configuration

### API Version
The API version is controlled by the `strapiversion` variable in `main.py`. Update this when making changes to the prompt templates.

### Prompt Templates
The system uses prompt templates stored in the `data/` folder. The current template file is specified in `text2sql.py`.

The current prompt template is specifically designed for a **movie and TV series database** using MariaDB. It includes:

**🎬 Database Schema Coverage:**
- **Movies**: Complete TMDB (The Movie Database) schema with detailed movie information
- **TV Series**: Full series data including episodes, seasons, and network information
- **People**: Actors, directors, and crew members with their roles and relationships
- **Collections**: Movie collections and franchises
- **Companies**: Production companies and studios
- **Ratings**: IMDB ratings integration
- **Genres**: Movie and series genre classifications
- **Languages**: Multi-language support for titles and content
- **Lists**: Curated movie and series lists
- **Images**: Poster, backdrop, and profile image management

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
- Returns `##AMBIGUOUS##` with explanations for unclear requests
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
- Configurable similarity threshold (default: 0.1)
- Stores anonymized SQL queries in metadata for quick retrieval

### Entity Extraction & Anonymization

The system intelligently extracts and replaces entities in natural language questions:

- **Person Names**: Actors, directors, crew members
- **Movie Titles**: English, French, and original language titles  
- **TV Series Titles**: Series names in multiple languages
- **Company Names**: Production companies and studios
- **Network Names**: TV networks and streaming platforms
- **Topic Names**: Genres, themes, and categories

**Process Flow:**
1. Extract entities from user question using GPT-4o
2. Replace entities with placeholders (e.g., `{{PERSON_NAME}}`)
3. Check cache for anonymized question pattern
4. Generate SQL if not cached
5. Replace placeholders with actual entity values using vector search

### Vector Search Integration

ChromaDB collections for entity matching:
- `persons`: Actor/director/crew member embeddings
- `movies`: Movie title embeddings (multiple languages)
- `series`: TV series title embeddings
- `companies`: Production company embeddings  
- `networks`: TV network embeddings
- `topics`: Genre/theme embeddings
- `anonymizedqueries`: Cached anonymized question patterns

### Logging
All API requests are automatically logged to the `logs/` folder with:
- Timestamp
- Endpoint used
- API version
- Content hash
- Full request/response data

## 🔒 Security

- **API Key Authentication**: All endpoints (except health check) require a valid API key
- **Environment Variables**: Sensitive data like OpenAI API keys are stored in environment variables
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
- `sql_query`: The generated and optimized SQL query
- `result`: Array of query results with index and data

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
- `rows_per_page`: Configured page size
- `llm_defined_limit`/`llm_defined_offset`: LLM-specified pagination (if any)

**Cache Indicators:**
- `cached_exact_question`: Whether exact question was found in cache
- `cached_anonymized_question`: Whether anonymized question was cached
- `cached_anonymized_question_embedding`: Whether similar question found via embeddings
- `ambiguous_question_for_text2sql`: Whether question was too ambiguous for SQL generation

**Configuration:**
- `llm_model`: LLM model used for processing

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

---

**Note**: This API requires an active OpenAI API key to function. Make sure you have sufficient credits in your OpenAI account for the text-to-SQL conversions.
