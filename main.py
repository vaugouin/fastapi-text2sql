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
import cleanup
import entity
import logs
import sql_cache

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
    llm_model_complex: Optional[str] = "default"
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
    llm_model_complex: str
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
                sql_query_anonymized = sql_query
                justification_anonymized = justification
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
    async def _retry_with_resolved_complex_question(*, start_message: str, success_message: str, empty_question_message: str, error_message: str):
        nonlocal position_counter
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
                            api_version=strapiversionformatted,
                            entity_extraction_processing_time=getattr(retry_response, "entity_extraction_processing_time", 0.0) or 0.0,
                            text2sql_processing_time=getattr(retry_response, "text2sql_processing_time", 0.0) or 0.0,
                            embeddings_time=getattr(retry_response, "embeddings_processing_time", 0.0) or 0.0,
                            query_time=getattr(retry_response, "query_execution_time", 0.0) or 0.0,
                            total_processing_time=getattr(retry_response, "total_processing_time", 0.0) or 0.0,
                            is_anonymized=False,
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
                            text=f"Failed to store original complex question to cache after stronger-model retry: {str(cache_retry_error).replace('"', '\\"')}"
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

        # One-time retry: try resolving the original (non-anonymized) question into a simpler one
        # using a stronger model, then rerun the whole pipeline from the beginning.
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
            retry_response = await _retry_with_resolved_complex_question(
                start_message=f"Attempting to simplify the original question using the stronger model '{strcomplexquestionmodel}' (one-time retry).",
                success_message=f"Text2SQL error detected; attempting one-time retry with simplified question from stronger model '{strcomplexquestionmodel}'.",
                empty_question_message="Complex question resolution did not return a simplified question; skipping retry.",
                error_message="Complex question resolution returned an error; skipping retry."
            )
            if retry_response is not None:
                return retry_response
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
            position_counter=position_counter,
            text_message_cls=TextMessage,
            messages=messages,
            chromadb_collections_by_name=CHROMADB_COLLECTIONS_BY_NAME,
        )
        sql_query = entity_resolution_result["sql_query"]
        justification = entity_resolution_result["justification"]
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
                        "data": record
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
                sql_execution_failed
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
                not sql_execution_failed
                and lngpage == 1
                and isinstance(query_results, list)
                and len(query_results) == 0
                and bool(request.question)
                and not getattr(request, "complex_question_already_resolved", False)
                and "original_question" in locals()
                and isinstance(original_question, str)
                and original_question.strip() != ""
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
            sql_cache.write_sql_cache_entry(
                connection,
                question=request.question,
                question_hashed=question_hash,
                sql_query=sql_query_llm,
                sql_processed=sql_query_processed_base,
                justification=justification or "",
                api_version=strapiversionformatted,
                entity_extraction_processing_time=entity_extraction_processing_time,
                text2sql_processing_time=text2sql_processing_time,
                embeddings_time=embeddings_processing_time,
                query_time=query_execution_time,
                total_processing_time=total_processing_time,
                is_anonymized=False,
            )

        # Store to SQL cache if requested and not already stored as exact question or anonymized question
        if request.store_to_cache and not cached_exact_question and not cached_anonymized_question and request.question:
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
                api_version=strapiversionformatted,
                entity_extraction_processing_time=entity_extraction_processing_time,
                text2sql_processing_time=text2sql_processing_time,
                embeddings_time=embeddings_processing_time,
                query_time=query_execution_time,
                total_processing_time=total_processing_time,
                is_anonymized=True,
            )
        
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
        llm_model_complex=strcomplexquestionmodel,
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
