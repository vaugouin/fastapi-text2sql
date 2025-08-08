# FastAPI Text2SQL API

A powerful FastAPI-based REST API that converts natural language questions into SQL queries using OpenAI's language models and LangChain.

## 🚀 Features

- **Natural Language to SQL**: Convert plain English questions into SQL queries
- **FastAPI Framework**: High-performance, modern Python web framework
- **API Key Authentication**: Secure access with API key validation
- **Comprehensive Logging**: Automatic logging of all API requests and responses
- **Memory Monitoring**: Built-in system memory usage tracking
- **Docker Support**: Containerized deployment ready
- **UTF-8 Support**: Proper handling of Unicode characters in queries and logs

## 📊 Database Scale

The API operates on a comprehensive entertainment database containing:
- **Movies**: More than 620,000 entries
- **Series**: More than 88,000 entries  
- **Persons**: More than 890,000 entries (actors, directors, crew members)

## 📋 Requirements

- Python 3.8+
- OpenAI API key
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
GET /search/text2sql?text=your_natural_language_question
```

**Headers Required:**
```
X-API-Key: your_api_key
```

**Example:**
```bash
curl -X GET "http://localhost:8000/search/text2sql?text=List all color movies with Humphrey Bogart" \
     -H "X-API-Key: your_api_key"
```

**Response:**
```json
{
  "text": "List all color movies with Humphrey Bogart",
  "sqlquery": "SELECT T_WC_TMDB_MOVIE.ID_MOVIE, T_WC_TMDB_MOVIE.TITLE, T_WC_TMDB_MOVIE.ORIGINAL_TITLE, CONCAT(T_WC_TMDB_MOVIE.RELEASE_YEAR, '-', T_WC_TMDB_MOVIE.RELEASE_MONTH, '-', T_WC_TMDB_MOVIE.RELEASE_DAY) AS DAT_RELEASE, T_WC_TMDB_MOVIE.ID_IMDB, T_WC_IMDB_MOVIE_RATING_IMPORT.averageRating, T_WC_TMDB_MOVIE.OVERVIEW, T_WC_TMDB_MOVIE.POSTER_PATH, T_WC_TMDB_MOVIE.ORIGINAL_LANGUAGE, T_WC_TMDB_MOVIE.RUNTIME, T_WC_TMDB_MOVIE.BUDGET, T_WC_TMDB_MOVIE.REVENUE, T_WC_TMDB_MOVIE.ID_WIKIDATA, T_WC_TMDB_MOVIE.ADULT, T_WC_TMDB_MOVIE.IS_COLOR, T_WC_TMDB_MOVIE.IS_BLACK_AND_WHITE, T_WC_TMDB_MOVIE.IS_SILENT, T_WC_TMDB_MOVIE.IS_MOVIE, T_WC_TMDB_MOVIE.IS_DOCUMENTARY, T_WC_TMDB_MOVIE.IS_SHORT_FILM, T_WC_TMDB_MOVIE.STATUS, T_WC_TMDB_MOVIE.POPULARITY, T_WC_TMDB_MOVIE.ID_COLLECTION FROM T_WC_TMDB_MOVIE JOIN T_WC_TMDB_PERSON_MOVIE ON T_WC_TMDB_MOVIE.ID_MOVIE = T_WC_TMDB_PERSON_MOVIE.ID_MOVIE JOIN T_WC_TMDB_PERSON ON T_WC_TMDB_PERSON_MOVIE.ID_PERSON = T_WC_TMDB_PERSON.ID_PERSON LEFT JOIN T_WC_IMDB_MOVIE_RATING_IMPORT ON T_WC_TMDB_MOVIE.ID_IMDB = T_WC_IMDB_MOVIE_RATING_IMPORT.tconst WHERE T_WC_TMDB_PERSON.NAME = 'Humphrey Bogart' AND T_WC_TMDB_MOVIE.ADULT = 0 AND T_WC_TMDB_MOVIE.IS_COLOR = 1 AND T_WC_TMDB_MOVIE.ID_IMDB IS NOT NULL AND T_WC_TMDB_MOVIE.ID_IMDB != '' ORDER BY DAT_RELEASE ASC;",
  "processing_time": 1.23
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
├── main.py              # FastAPI application and endpoints
├── text2sql.py          # Core text-to-SQL conversion logic
├── auth.py              # API key authentication
├── requirements.txt     # Python dependencies
├── Dockerfile          # Docker configuration
├── .env                # Environment variables (create this)
├── data/               # Prompt templates and configuration
│   └── prompt-chatgpt-4o-1-0-10-20250728.txt  # Current prompt template
├── logs/               # API usage logs (auto-created)
└── README.md           # This file
```

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

2. **Authentication Errors**
   - Verify you're sending the correct API key in the `X-API-Key` header

3. **Memory Issues**
   - The application monitors system memory and will display usage on startup

### Logs
Check the `logs/` folder for detailed request/response logs if you encounter issues.

## 📝 API Response Format

All successful text2sql requests return:
- `text`: The original natural language question
- `sqlquery`: The generated SQL query
- `processing_time`: Time taken to process the request and produce the SQL query (in seconds)

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
