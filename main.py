from typing import List, Optional
from fastapi import FastAPI, Depends
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
from urllib.parse import unquote_plus
import pymysql.cursors
from dotenv import load_dotenv
import re
import openai
import chromadb
#from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
import cleanup
import logs
import rapidfuzz_query

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

# Change API version each time the prompt file in the data folder is updated and text2sql API container is restarted
strapiversion = "1.1.15"
# Convert API version to XXX.YYY.ZZZ format
strapiversionformatted = format_api_version(strapiversion)

API_PORT_BLUE = int(os.getenv('API_PORT_BLUE', 8000))
API_PORT_GREEN = int(os.getenv('API_PORT_GREEN', 8001))

#intcleanupenabled = False
intcleanupenabled = True

ENTITY_RESOLUTION_CONFIG = [
    {
        "search_mode": "rapidfuzz",
        "placeholder_prefix": "Person_name",
        "strtablename": "T_WC_T2S_PERSON",
        "strtableid": "ID_PERSON",
        "collection": "persons",
        "default_field": "PERSON_NAME",
        "order_by": "POPULARITY",
        "languages": {"*": "PERSON_NAME"},
        "rapidfuzz_col_norm": "PERSON_NAME_NORM",
        "rapidfuzz_col_key": "PERSON_NAME_KEY",
        "rapidfuzz_col_popularity": "POPULARITY",
    },
    {
        "search_mode": "embeddings",
        "placeholder_prefix": "Movie_title",
        "strtablename": "T_WC_T2S_MOVIE",
        "strtableid": "ID_MOVIE",
        "collection": "movies",
        "default_field": "MOVIE_TITLE",
        "order_by": "POPULARITY",
        "languages": {"en": "MOVIE_TITLE", "fr": "MOVIE_TITLE_FR", "*": "ORIGINAL_TITLE"},
    },
    {
        "search_mode": "embeddings",
        "placeholder_prefix": "Serie_title",
        "strtablename": "T_WC_T2S_SERIE",
        "strtableid": "ID_SERIE",
        "collection": "series",
        "default_field": "SERIE_TITLE",
        "order_by": "POPULARITY",
        "languages": {"en": "SERIE_TITLE", "fr": "SERIE_TITLE_FR", "*": "ORIGINAL_TITLE"},
    },
    {
        "search_mode": "embeddings",
        "placeholder_prefix": "Company_name",
        "strtablename": "T_WC_T2S_COMPANY",
        "strtableid": "ID_COMPANY",
        "collection": "companies",
        "default_field": "COMPANY_NAME",
        "order_by": None,
        "languages": {"*": "COMPANY_NAME"},
    },
    {
        "search_mode": "embeddings",
        "placeholder_prefix": "Network_name",
        "strtablename": "T_WC_T2S_NETWORK",
        "strtableid": "ID_NETWORK",
        "collection": "networks",
        "default_field": "NETWORK_NAME",
        "order_by": None,
        "languages": {"*": "NETWORK_NAME"},
    },
    {
        "search_mode": "embeddings",
        "placeholder_prefix": "Topic_name",
        "strtablename": "T_WC_T2S_TOPIC",
        "strtableid": "ID_TOPIC",
        "collection": "topics",
        "default_field": "TOPIC_NAME",
        "order_by": None,
        "languages": {"en": "TOPIC_NAME", "fr": "TOPIC_NAME_FR", "*": "TOPIC_NAME"},
    },
    {
        "search_mode": "embeddings",
        "placeholder_prefix": "Location_name",
        "strtablename": "T_WC_T2S_ITEM",
        "strtableid": "ID_WIKIDATA",
        "collection": "locations",
        "default_field": "ITEM_LABEL",
        "order_by": None,
        "languages": {"en": "ITEM_LABEL", "fr": "ITEM_LABEL_FR", "*": "ITEM_LABEL"},
    },
]

# Set your OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")

# Validate that the API key was loaded
if not openai.api_key:
    raise ValueError("OPENAI_API_KEY not found in environment variables. Please check your .env file.")

class OpenAIEmbeddingFunction:
    def __init__(self, model="text-embedding-3-large"):
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
chroma_client = chromadb.HttpClient(host=os.getenv("CHROMADB_HOST", "localhost"), port=os.getenv("CHROMADB_PORT", 8000))

# Initialize ChromaDB with OpenAI's embedding function
embedding_function = OpenAIEmbeddingFunction(model="text-embedding-3-large")

print("ChromaDB initialized with a text-embedding-3-large model.")

# Create or load entity collections with the custom embedding function
CHROMADB_COLLECTIONS_BY_NAME = {
    name: chroma_client.get_or_create_collection(name=name, embedding_function=embedding_function)
    for name in ["persons", "movies", "series", "companies", "networks", "topics", "locations", "groups", "characters"]
}

#Anonymized queries collection
strentitycollection = "anonymizedqueries"
anonymizedqueries = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)

# By default, do not use embeddings-based question cache (read/write) for anonymized queries.
USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE = False

if intcleanupenabled:
    if USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE:
        cleanup.cleanup_anonymized_queries_collection(anonymizedqueries, strapiversion)

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

app = FastAPI(title="Text2SQL API", version=strapiversion, description="Text2SQL API for text to SQL query conversion")

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
connection = get_db_connection()

if intcleanupenabled:
    cleanup.cleanup_sql_cache(connection, strapiversion)

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
    complex_question_already_resolved: bool = False
    
    @model_validator(mode='after')
    def validate_question_or_hashed(self):
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
    error: str
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
    result = {"message": "hello world! The universal answer is " + str(answer)}
    logs.log_usage("hello", result, strapiversion)
    return result

@app.post("/search/text2sql", response_model=Text2SQLResponse)
async def search_text2sql(request: Text2SQLRequest, api_key: str = Depends(get_api_key)):
    """Convert natural language questions to SQL queries with caching and entity extraction.
    
    This endpoint processes natural language questions and converts them to SQL queries using:
    - Entity extraction to anonymize questions
    - Multi-level caching (exact, anonymized, embeddings)
    - Vector similarity search for entity matching
    - Pagination support for results
    
    Args:
        request (Text2SQLRequest): Request containing question and processing options
        api_key (str): Valid API key for authentication (injected by dependency)
        
    Returns:
        Text2SQLResponse: Complete response with SQL query, results, and performance metrics
        
    Raises:
        ValueError: If neither question nor question_hashed is provided
        HTTPException: If API key is invalid or database errors occur
        
    Example:
        POST /search/text2sql
        {
            "question": "Show me movies with Tom Hanks",
            "page": 1,
            "retrieve_from_cache": true,
            "store_to_cache": true
        }
    """
    total_start_time = time.time()
    
    # Initialize messages list and position counter
    messages = []
    position_counter = 1
    
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
    ambiguous_question_for_text2sql = 0
    strentityextractionmodel = t2s.strentityextractionmodeldefault
    if request.llm_model_entity_extraction and request.llm_model_entity_extraction != "default":
        strentityextractionmodel = request.llm_model_entity_extraction
    strtext2sqlmodel = t2s.strtext2sqlmodeldefault
    if request.llm_model_text2sql and request.llm_model_text2sql != "default":
        strtext2sqlmodel = request.llm_model_text2sql

    print("/search/text2sql LLM selection:")
    print("- Entity extraction model:", strentityextractionmodel)
    print("- Text2SQL model:", strtext2sqlmodel)
    
    # Try to retrieve user question from cache if requested
    if request.retrieve_from_cache:
        messages.append(TextMessage(
            position=position_counter, 
            text="Attempting to retrieve exact question from cache."
        ))
        position_counter += 1
        with connection.cursor() as cursor:
            cache_result_exact = None
            
            # First, try to find by question_hashed if provided
            if request.question_hashed:
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Searching cache by question hash."
                ))
                position_counter += 1
                cache_query = """
SELECT QUESTION, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION, ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME
FROM T_WC_T2S_CACHE
WHERE QUESTION_HASHED = %s
AND API_VERSION = %s
AND (DELETED IS NULL OR DELETED = 0)
ORDER BY TIM_UPDATED DESC
LIMIT 1 """
                print("Looking for the exact question hash in the SQL cache:", cache_query)
                cursor.execute(cache_query, (request.question_hashed, strapiversionformatted))
                #print("Cache query executed")
                cache_result_exact = cursor.fetchone()
                if not cache_result_exact:
                    print("Exact question hash not found in the SQL cache")
                    messages.append(TextMessage(
                        position=position_counter, 
                        text="Exact question hash not found in cache."
                    ))
                    position_counter += 1
            
            # If not found by hash and we have a question, try to find by question text
            if not cache_result_exact and request.question:
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Searching cache by question text."
                ))
                position_counter += 1
                cache_query = """
SELECT QUESTION, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION, ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME
FROM T_WC_T2S_CACHE
WHERE QUESTION = %s
AND API_VERSION = %s
AND (DELETED IS NULL OR DELETED = 0)
ORDER BY TIM_UPDATED DESC
LIMIT 1 """
                print("Looking for the exact question in the SQL cache:", cache_query)
                cursor.execute(cache_query, (request.question, strapiversionformatted))
                #print("Cache query executed")
                cache_result_exact = cursor.fetchone()
                if not cache_result_exact:
                    print("Exact question not found in the SQL cache")
                    messages.append(TextMessage(
                        position=position_counter, 
                        text="Exact question not found in cache."
                    ))
                    position_counter += 1
            
            if cache_result_exact:
                # Found exact result in the SQL cache
                print("Found exact question in the SQL cache")
                cached_exact_question = True
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Exact question cache hit used for SQL query."
                ))
                position_counter += 1
                input_text = cache_result_exact['QUESTION']
                input_text = cache_result_exact['QUESTION']
                sql_query = cache_result_exact['SQL_PROCESSED'] or cache_result_exact['SQL_QUERY']
                sql_query_anonymized = cache_result_exact['SQL_QUERY']
                justification = cache_result_exact.get('JUSTIFICATION', '')
                # Because the SQL query can be updated in the t2scache.php back-office script,
                # we need to replace &#039; by ' because the back-office script stores &#039; instead of ' in the database
                #sql_query = sql_query.replace("&#039;", "'")
                #entity_extraction_processing_time = cache_result_exact['ENTITY_EXTRACTION_PROCESSING_TIME']
                #text2sql_processing_time = cache_result_exact['TEXT2SQL_PROCESSING_TIME']
                #embeddings_processing_time = cache_result_exact['EMBEDDINGS_TIME']
                #query_execution_time = cache_result_exact['QUERY_TIME']
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
            # If we have question_hashed but no cache hit, we can't proceed without the original question
            raise ValueError("question_hashed provided but no entry found in the SQL cache and no original question provided")
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
        entity_extraction = t2s.f_entity_extraction(input_text, strentityextractionmodel)
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
            # Is this anonymized query in the SQL cache?
            with connection.cursor() as cursor:
                cache_query = """
SELECT QUESTION, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION, ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME
FROM T_WC_T2S_CACHE
WHERE QUESTION = %s
AND API_VERSION = %s
AND (DELETED IS NULL OR DELETED = 0)
ORDER BY TIM_UPDATED DESC
LIMIT 1 """
                print("Looking for the anonymized question in the SQL cache:", cache_query)
                cursor.execute(cache_query, (input_text_anonymized, strapiversionformatted))
                #print("Cache query executed")
                cache_result_anonymized = cursor.fetchone()
            
            if cache_result_anonymized:
                # Found anonymized question in the SQL cache so we retrieved the question in cache and the SQL query
                print("Found anonymized question in the SQL cache")
                cached_anonymized_question = True
                messages.append(TextMessage(
                    position=position_counter, 
                    text="Anonymized question cache hit used for SQL query."
                ))
                position_counter += 1
                input_text_anonymized = cache_result_anonymized['QUESTION']
                sql_query_cached_processed = cache_result_anonymized['SQL_PROCESSED'] or ""
                sql_query_cached_raw = cache_result_anonymized['SQL_QUERY'] or ""

                sql_query = sql_query_cached_processed or sql_query_cached_raw
                if sql_query_cached_processed and sql_query_cached_raw and '{{' not in sql_query_cached_raw:
                    match_raw_limit = re.search(r"\blimit\b\s+(\d+)", sql_query_cached_raw, re.IGNORECASE)
                    match_processed_limit = re.search(r"\blimit\b\s+(\d+)", sql_query_cached_processed, re.IGNORECASE)
                    if match_raw_limit and match_processed_limit:
                        raw_limit = int(match_raw_limit.group(1))
                        processed_limit = int(match_processed_limit.group(1))
                        if raw_limit < processed_limit:
                            sql_query = sql_query_cached_raw
                            messages.append(TextMessage(
                                position=position_counter,
                                text="Cache hit: using SQL_QUERY instead of SQL_PROCESSED to preserve smaller LIMIT."
                            ))
                            position_counter += 1

                justification = cache_result_anonymized.get('JUSTIFICATION', '')
                # Because the SQL query can be updated in the t2scache.php back-office script,
                # we need to replace &#039; by ' because the back-office script stores &#039; instead of ' in the database
                #sql_query = sql_query.replace("&#039;", "'")
                sql_query_anonymized = sql_query
                justification_anonymized = justification
                #entity_extraction_processing_time = cache_result_anonymized['ENTITY_EXTRACTION_PROCESSING_TIME']
                #text2sql_processing_time = cache_result_anonymized['TEXT2SQL_PROCESSING_TIME']
                #embeddings_processing_time = cache_result_anonymized['EMBEDDINGS_TIME']
                #query_execution_time = cache_result_anonymized['QUERY_TIME']
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

                # If no cache hit, call Text2SQL on anonymized question
                if not cached_anonymized_question_embedding:
                    text2sql_start_time = time.time()
                    messages.append(TextMessage(
                        position=position_counter,
                        text=f"Generating SQL using LLM model '{strtext2sqlmodel}'."
                    ))
                    position_counter += 1
                    json_content = t2s.f_text2sql(input_text_anonymized, strtext2sqlmodel)
                    if not isinstance(json_content, dict):
                        json_content = {"error": str(json_content)}

                    # Only use json_content when we actually executed Text2SQL (no SQL cache hit, no embeddings cache hit)
                    if not cached_anonymized_question and not cached_anonymized_question_embedding:
                        print("JSON content:", json_content)
                        if 'sql_query' not in json_content:
                            ambiguous_question_for_text2sql = 1
                            sql_query = ""
                            sql_query_anonymized = ""
                            justification = json_content.get('justification', '')
                            justification_anonymized = justification
                            error_text2sql = json_content.get('error', 'Text2SQL failed to return sql_query')
                            messages.append(TextMessage(
                                position=position_counter,
                                text=f"Text2SQL failed using LLM model '{strtext2sqlmodel}': {error_text2sql}"
                            ))
                            position_counter += 1
                        else:
                            sql_query = json_content.get('sql_query', '')
                            if sql_query.endswith(';'):
                                sql_query = sql_query[:-1]
                            sql_query_anonymized = sql_query
                            justification = json_content.get('justification', '')
                            justification_anonymized = justification
                            error_text2sql = json_content.get('error', '')

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
                        messages.append(TextMessage(
                            position=position_counter, 
                            text="Error: " + error_text2sql
                        ))
                        position_counter += 1
    sql_query_llm = sql_query
    # if the error element is found in json content
    if error_text2sql!="" and error_text2sql!=None:
        print("Problem detected so the Text-to-SQL cannot produce a SQL query")
        print("Error: ", error_text2sql)

        # One-time retry: try resolving the original (non-anonymized) question into a simpler one
        # using a reasoning model, then rerun the whole pipeline from the beginning.
        try:
            can_retry = (
                bool(request.question)
                and not getattr(request, "complex_question_already_resolved", False)
                and "original_question" in locals()
                and isinstance(original_question, str)
                and original_question.strip() != ""
            )
        except Exception:
            can_retry = False

        if can_retry:
            messages.append(TextMessage(
                position=position_counter,
                text="Attempting to simplify the original question using the reasoning model (one-time retry)."
            ))
            position_counter += 1

            resolved_complex = t2s.f_resolve_complex_question(original_question)
            try:
                resolved_complex_json = json.dumps(resolved_complex, ensure_ascii=False)
            except Exception:
                resolved_complex_json = str(resolved_complex)
            messages.append(TextMessage(
                position=position_counter,
                text=f"Complex question resolution output: {resolved_complex_json.replace('"', '\\"')}"
            ))
            position_counter += 1

            if isinstance(resolved_complex, dict) and not resolved_complex.get("error"):
                simplified_question = str(resolved_complex.get("question") or "").strip()
                if simplified_question != "":
                    messages.append(TextMessage(
                        position=position_counter,
                        text="Text2SQL error detected; attempting one-time retry with simplified question from reasoning model."
                    ))
                    position_counter += 1

                    # Close the current DB connection before restarting the pipeline to avoid leaks.
                    try:
                        connection.close()
                    except Exception:
                        pass

                    retry_request = request.model_copy(deep=True)
                    retry_request.question = simplified_question
                    retry_request.question_hashed = None
                    retry_request.complex_question_already_resolved = True

                    retry_response = await search_text2sql(retry_request, api_key)

                    # Merge messages from the retry call into the current messages collection
                    # to provide a single coherent trace.
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

                    return retry_response
                else:
                    messages.append(TextMessage(
                        position=position_counter,
                        text="Complex question resolution did not return a simplified question; skipping retry."
                    ))
                    position_counter += 1
            else:
                messages.append(TextMessage(
                    position=position_counter,
                    text="Complex question resolution returned an error; skipping retry."
                ))
                position_counter += 1
        else:
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
        # Compute embeddings for entity resolution in the SQL query and/or justification
        print("Computing embeddings for entity resolution")
        messages.append(TextMessage(
            position=position_counter, 
            text="Processing entity values using embeddings for entity matching."
        ))
        position_counter += 1
        def _find_entity_config(placeholder_key: str):
            for cfg in ENTITY_RESOLUTION_CONFIG:
                if isinstance(placeholder_key, str) and placeholder_key.startswith(cfg.get("placeholder_prefix", "")):
                    return cfg
            return None

        def _sql_escape_literal(v: str) -> str:
            return str(v).replace("'", "''")

        def _apply_entity_match_from_docid(
            *,
            cursor,
            key: str,
            cfg: dict,
            docid,
            doclang: str,
            message: str,
        ) -> bool:
            nonlocal sql_query, justification, position_counter

            if docid is None:
                return False

            languages_map = cfg.get("languages", {}) or {}
            strfieldnamenew = languages_map.get(doclang) or languages_map.get("*") or cfg.get("default_field")
            strtableidlookup = strfieldnamenew

            strtablename = cfg.get("strtablename")
            strtableid = cfg.get("strtableid")
            if not strtablename or not strtableid:
                return False

            strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strtableid + " = %s"
            cursor.execute(strsql_query, (docid,))
            sql_query_results = cursor.fetchall()
            if not sql_query_results:
                placeholder = "{{" + str(key) + "}}"
                messages.append(TextMessage(
                    position=position_counter,
                    text=(
                        f"Entity resolution: embeddings returned docid={docid} (lang={doclang}) for {placeholder}, "
                        f"but no row exists in table {strtablename}.{strtableid}. "
                        "Embeddings collection may be out of sync with the underlying table."
                    )
                ))
                position_counter += 1
                return False
            first_record = sql_query_results[0]

            first_record_value = first_record.get(strtableidlookup, '')
            first_record_value_sql = _sql_escape_literal(first_record_value)

            placeholder = "{{" + str(key) + "}}"
            target_col = cfg.get("default_field")
            if not target_col:
                return False

            sql_query = re.sub(
                rf"\b{re.escape(target_col)}\b\s*=\s*'{re.escape(placeholder)}'",
                f"{strfieldnamenew} = '{first_record_value_sql}'",
                sql_query,
                flags=re.IGNORECASE,
            )
            sql_query = re.sub(
                rf"\b{re.escape(target_col)}\b\s*=\s*{re.escape(placeholder)}",
                f"{strfieldnamenew} = '{first_record_value_sql}'",
                sql_query,
                flags=re.IGNORECASE,
            )

            # Also replace placeholder tokens wherever they appear (e.g. IN (...) lists).
            # - If the placeholder is already quoted, keep it quoted.
            # - If it's unquoted, inject quotes to keep SQL valid for string placeholders.
            sql_query = re.sub(
                rf"'{re.escape(placeholder)}'",
                f"'{first_record_value_sql}'",
                sql_query,
                flags=re.IGNORECASE,
            )
            sql_query = re.sub(
                rf"{re.escape(placeholder)}",
                f"'{first_record_value_sql}'",
                sql_query,
                flags=re.IGNORECASE,
            )

            justification = justification.replace(placeholder, str(first_record_value))

            messages.append(TextMessage(
                position=position_counter,
                text=message.format(placeholder=placeholder, resolved=first_record_value)
            ))
            position_counter += 1
            return True

        if isinstance(entity_extraction, dict):
            with connection.cursor() as cursor:
                for key, value in entity_extraction.items():
                    if key == "question":
                        continue

                    # Numeric placeholders (e.g. {{Release_year1}}) should be substituted directly
                    # so expressions like BETWEEN {{Release_year1}} - 1 AND {{Release_year1}} + 1 keep working.
                    if isinstance(key, str) and key.startswith("Release_year"):
                        raw_value = "" if value is None else str(value).strip()
                        if raw_value == "":
                            continue
                        if not re.fullmatch(r"\d{4}", raw_value):
                            continue

                        placeholder = "{{" + key + "}}"
                        # Replace both quoted and unquoted forms with a numeric literal
                        sql_query = re.sub(
                            rf"'{re.escape(placeholder)}'",
                            raw_value,
                            sql_query,
                            flags=re.IGNORECASE,
                        )
                        sql_query = re.sub(
                            rf"{re.escape(placeholder)}",
                            raw_value,
                            sql_query,
                            flags=re.IGNORECASE,
                        )
                        justification = justification.replace(placeholder, raw_value)

                        messages.append(TextMessage(
                            position=position_counter,
                            text=f"Entity resolution: {placeholder} -> {raw_value} (numeric)"
                        ))
                        position_counter += 1
                        continue

                    cfg = _find_entity_config(key)
                    if cfg is None:
                        raw_value = "" if value is None else str(value)
                        if raw_value.strip() == "":
                            continue

                        placeholder = "{{" + str(key) + "}}"
                        raw_value_sql = _sql_escape_literal(raw_value)

                        # Generic fallback: unknown entity types still need placeholder substitution.
                        # Keep surrounding quotes intact by replacing only the placeholder token.
                        if placeholder in sql_query or placeholder in justification:
                            sql_query = sql_query.replace(placeholder, raw_value_sql)
                            justification = justification.replace(placeholder, raw_value)
                            messages.append(TextMessage(
                                position=position_counter,
                                text=f"Entity resolution: {placeholder} -> {raw_value} (generic)"
                            ))
                            position_counter += 1
                        continue

                    raw_value = "" if value is None else str(value)
                    if raw_value.strip() == "":
                        continue

                    placeholder = "{{" + str(key) + "}}"
                    raw_value_sql = _sql_escape_literal(raw_value)

                    search_mode = str(cfg.get("search_mode") or "embeddings").strip().lower()
                    if search_mode == "rapidfuzz":
                        strtablename = cfg.get("strtablename")
                        strtableid = cfg.get("strtableid")
                        if not strtablename or not strtableid:
                            continue

                        strcolumndesc = cfg.get("default_field")
                        strcolumndescnorm = cfg.get("rapidfuzz_col_norm") or (f"{strcolumndesc}_NORM" if strcolumndesc else None)
                        strcolumndesckey = cfg.get("rapidfuzz_col_key") or (f"{strcolumndesc}_KEY" if strcolumndesc else None)
                        strcolumnpopularity = cfg.get("rapidfuzz_col_popularity") or cfg.get("order_by") or "POPULARITY"
                        if not strcolumndesc or not strcolumndescnorm or not strcolumndesckey:
                            continue

                        try:
                            has_fulltext = rapidfuzz_query.db_has_fulltext(cursor, strtablename, strcolumndescnorm)
                            rapidfuzz_result = rapidfuzz_query.search_first_match(
                                cursor,
                                strtablename,
                                strtableid,
                                strcolumndesc,
                                strcolumndescnorm,
                                strcolumndesckey,
                                strcolumnpopularity,
                                raw=raw_value,
                                has_fulltext=has_fulltext,
                                timings_enabled=False,
                            )
                        except Exception:
                            continue

                        best = (rapidfuzz_result or {}).get("best")
                        if not isinstance(best, dict):
                            continue

                        docid = best.get(strtableid)
                        doclang = "*"
                        if docid is None:
                            continue

                        _apply_entity_match_from_docid(
                            cursor=cursor,
                            key=str(key),
                            cfg=cfg,
                            docid=docid,
                            doclang=doclang,
                            message="Entity resolution: {placeholder} -> {resolved} (rapidfuzz)",
                        )
                        # If rapidfuzz resolution didn't replace the placeholder, fall back to raw substitution.
                        if placeholder in sql_query or placeholder in justification:
                            sql_query = sql_query.replace(placeholder, raw_value_sql)
                            justification = justification.replace(placeholder, raw_value)
                            messages.append(TextMessage(
                                position=position_counter,
                                text=f"Entity resolution: {placeholder} -> {raw_value} (raw fallback after rapidfuzz)"
                            ))
                            position_counter += 1
                        continue

                    if search_mode != "embeddings":
                        continue

                    collection_name = cfg.get("collection")
                    current_collection = CHROMADB_COLLECTIONS_BY_NAME.get(collection_name)
                    if current_collection is None:
                        if placeholder in sql_query or placeholder in justification:
                            sql_query = sql_query.replace(placeholder, raw_value_sql)
                            justification = justification.replace(placeholder, raw_value)
                            messages.append(TextMessage(
                                position=position_counter,
                                text=f"Entity resolution: {placeholder} -> {raw_value} (raw fallback; embeddings collection unavailable)"
                            ))
                            position_counter += 1
                        continue

                    start_time_chromadb = time.time()
                    results = current_collection.query(query_texts=[raw_value], n_results=10)
                    end_time_chromadb = time.time()
                    search_duration_chromadb = end_time_chromadb - start_time_chromadb

                    documents = (results.get("documents", [[]]) or [[]])[0] or []
                    ids = (results.get("ids", [[]]) or [[]])[0] or []

                    if not documents or not ids:
                        if placeholder in sql_query or placeholder in justification:
                            sql_query = sql_query.replace(placeholder, raw_value_sql)
                            justification = justification.replace(placeholder, raw_value)
                            messages.append(TextMessage(
                                position=position_counter,
                                text=f"Entity resolution: {placeholder} -> {raw_value} (raw fallback; no embeddings match)"
                            ))
                            position_counter += 1
                        continue

                    matched_result_position = 0
                    found_match = False
                    try:
                        target_value_norm = raw_value.strip().lower()
                    except Exception:
                        target_value_norm = ""

                    for i, document in enumerate(documents):
                        if isinstance(document, str) and document.strip().lower() == target_value_norm:
                            matched_result_position = i
                            found_match = True
                            break
                    if not found_match:
                        for i, document in enumerate(documents):
                            if isinstance(document, str) and document.strip().lower().startswith(target_value_norm):
                                matched_result_position = i
                                found_match = True
                                break

                    first_record_id = ids[matched_result_position]
                    parts = str(first_record_id).split('_')
                    docid = parts[1] if len(parts) > 1 else None
                    doclang = parts[2] if len(parts) > 2 else "*"

                    if docid is None:
                        if placeholder in sql_query or placeholder in justification:
                            sql_query = sql_query.replace(placeholder, raw_value_sql)
                            justification = justification.replace(placeholder, raw_value)
                            messages.append(TextMessage(
                                position=position_counter,
                                text=f"Entity resolution: {placeholder} -> {raw_value} (raw fallback; invalid embeddings docid)"
                            ))
                            position_counter += 1
                        continue

                    _apply_entity_match_from_docid(
                        cursor=cursor,
                        key=str(key),
                        cfg=cfg,
                        docid=docid,
                        doclang=doclang,
                        message=f"Entity resolution: {{placeholder}} -> {{resolved}} (lang={doclang}, {search_duration_chromadb:.4f}s)",
                    )

                    # If embeddings resolution didn't replace the placeholder, fall back to raw substitution.
                    if placeholder in sql_query or placeholder in justification:
                        sql_query = sql_query.replace(placeholder, raw_value_sql)
                        justification = justification.replace(placeholder, raw_value)
                        messages.append(TextMessage(
                            position=position_counter,
                            text=f"Entity resolution: {placeholder} -> {raw_value} (raw fallback after embeddings)"
                        ))
                        position_counter += 1

        # Safety: the SQL query must be fully de-anonymized (no {{...}} placeholders) before execution.
        # If placeholders remain, skip execution to avoid running a broken query.
        unresolved_placeholders = re.findall(r"{{[^}]+}}", sql_query or "")
        if unresolved_placeholders:
            ambiguous_question_for_text2sql = 1
            unresolved_preview = ", ".join(unresolved_placeholders[:10])
            if len(unresolved_placeholders) > 10:
                unresolved_preview += ", ..."
            messages.append(TextMessage(
                position=position_counter,
                text=f"Unresolved placeholders remain in SQL after entity resolution: {unresolved_preview}"
            ))
            position_counter += 1
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
                        "data": record
                    })
            except Exception as e:
                print(f"Database operation failed: {e}")
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
        if request.store_to_cache and not cached_exact_question and request.question:
            messages.append(TextMessage(position=position_counter, text="Storing exact question and SQL query to cache."))
            position_counter += 1
            with connection.cursor() as cursor2:
                # Insert exact question into cache table
                insert_query = """
INSERT INTO T_WC_T2S_CACHE
(QUESTION, QUESTION_HASHED, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION, API_VERSION,
ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME, TOTAL_PROCESSING_TIME,
DELETED, DAT_CREAT, TIM_UPDATED, IS_ANONYMIZED)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), NOW(), 0)
"""
                print("Insert query:", insert_query)
                # Use the actual measured query execution time
                query_time = query_execution_time
                """
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing SQL insert into cache: {insert_query} | params: [question={request.question}, hash={question_hash}]"
                ))
                position_counter += 1
                """
                cursor2.execute(insert_query, (
                    request.question,
                    question_hash,
                    sql_query_llm,
                    sql_query_processed_base,
                    justification or "",
                    strapiversionformatted,
                    entity_extraction_processing_time,
                    text2sql_processing_time,
                    embeddings_processing_time,
                    query_time,
                    total_processing_time,
                    0  # DELETED = 0 (not deleted)
                ))
                connection.commit()

        # Store to SQL cache if requested and not already stored as exact question or anonymized question
        if request.store_to_cache and not cached_exact_question and not cached_anonymized_question and request.question:
            messages.append(TextMessage(
                position=position_counter, 
                text="Storing anonymized question and SQL query to cache."
            ))
            position_counter += 1
            with connection.cursor() as cursor2:
                # Insert anonymized question into cache table
                insert_query = """
INSERT INTO T_WC_T2S_CACHE
(QUESTION, QUESTION_HASHED, SQL_QUERY, SQL_PROCESSED, JUSTIFICATION, API_VERSION,
ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME, TOTAL_PROCESSING_TIME,
DELETED, DAT_CREAT, TIM_UPDATED, IS_ANONYMIZED)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), NOW(), 1)
"""
                print("Insert query:", insert_query)
                # Use the actual measured query execution time
                query_time = query_execution_time
                """
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing SQL insert into cache (anonymized): {insert_query} | params: [question={input_text_anonymized}, hash={question_hash}]"
                ))
                position_counter += 1
                """
                cursor2.execute(insert_query, (
                    input_text_anonymized,
                    question_hash,
                    sql_query_llm,
                    sql_query_anonymized_base,
                    justification_anonymized or "",
                    strapiversionformatted,
                    entity_extraction_processing_time,
                    text2sql_processing_time,
                    embeddings_processing_time,
                    query_time,
                    total_processing_time,
                    0  # DELETED = 0 (not deleted)
                ))
                connection.commit()
                cursor2.close()
        
        if USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE and request.store_to_cache and not cached_anonymized_question_embedding and input_text_anonymized:
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
                            "api_version": strapiversionformatted,
                            "entity_variables": ",".join(entity_vars_for_metadata),  # Store as comma-separated string
                            "entity_extraction_processing_time": entity_extraction_processing_time,
                            "text2sql_processing_time": text2sql_processing_time,
                            "dat_creat": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }]
                )
                print(f"Anonymized question added to embeddings cache with entity variables: {entity_vars_for_metadata}")
    
    connection.close()
    
    # Generate question hash if we have a question and no hash was provided
    response_question_hash = request.question_hashed
    if not response_question_hash and request.question:
        response_question_hash = hashlib.sha256(request.question.encode('utf-8')).hexdigest()
    
    # Compute the final global processing time with also the write cache operations (SQL and embeddings)
    total_end_time = time.time()
    total_processing_time = total_end_time - total_start_time
    
    messages.append(TextMessage(
        position=position_counter, 
        text="Completed request processing and prepared response."
    ))
    position_counter += 1

    response = Text2SQLResponse(
        question=input_text,
        question_hashed=response_question_hash,
        sql_query=sql_query or "",
        sql_query_anonymized=sql_query_anonymized or "",
        justification=justification or "",
        justification_anonymized=justification_anonymized or "",
        error=error_text2sql or "",
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
