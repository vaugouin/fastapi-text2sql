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
strapiversion = "1.1.14"
# Convert API version to XXX.YYY.ZZZ format
strapiversionformatted = format_api_version(strapiversion)

API_PORT_BLUE = int(os.getenv('API_PORT_BLUE', 8000))
API_PORT_GREEN = int(os.getenv('API_PORT_GREEN', 8001))

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

# Create or load a collection with the custom embedding function
strentitycollection = "topics"
topics = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
strentitycollection = "movies"
movies = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
strentitycollection = "series"
series = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
strentitycollection = "persons"
persons = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
strentitycollection = "companies"
companies = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
strentitycollection = "networks"
networks = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
strentitycollection = "characters"
characters = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
strentitycollection = "groups"
groups = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)
strentitycollection = "locations"
locations = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)

#Anonymized queries collection
strentitycollection = "anonymizedqueries"
anonymizedqueries = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)

cleanup.cleanup_anonymized_queries_collection(anonymizedqueries, strapiversion)

# How many rows per page in the result set
lngrowsperpage = 50
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
cleanup.cleanup_sql_cache(connection, strapiversion)


class TextExpr(BaseModel):
    text: str
    sql_query: str = ""

class Text2SQLRequest(BaseModel):
    question: Optional[str] = None
    question_hashed: Optional[str] = None  # For pagination/disambiguation
    page: Optional[int] = 1
    retrieve_from_cache: bool = True
    store_to_cache: bool = True
    llm_model_entity_extraction: Optional[str] = "default"
    llm_model_text2sql: Optional[str] = "default"
    
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

LOGS_FOLDER = "logs"

def f_getlogfilename(endpoint, contenttext):
    """Generate a unique log filename based on endpoint, timestamp, and content hash.
    
    Creates a filename in the format: YYYYMMDD-HHMMSS_endpoint_version_hash.json
    Ensures the logs folder exists before generating the filename.
    
    Args:
        endpoint (str): The API endpoint name (e.g., 'hello', 'text2sql')
        contenttext (str): The content to be logged (used for MD5 hash)
        
    Returns:
        str: Complete path to the log file
    """
    os.makedirs(LOGS_FOLDER, exist_ok=True)
    now = datetime.now()
    date_time_str = now.strftime("%Y%m%d-%H%M%S")
    md5_hash = hashlib.md5(contenttext.encode('utf-8')).hexdigest()
    filename = f"{LOGS_FOLDER}/{date_time_str}_{endpoint}_{strapiversion}_{md5_hash}.json"
    return filename

def log_usage(endpoint, content):
    """Log API usage data to a JSON file.
    
    Serializes the provided content to JSON format with custom handling for
    Decimal and datetime objects, then writes it to a uniquely named log file.
    
    Args:
        endpoint (str): The API endpoint name for log categorization
        content (dict): The data to be logged (request/response information)
        
    Note:
        Creates log files only if they don't already exist to avoid overwrites.
        Uses UTF-8 encoding and pretty-printed JSON format.
    """
    def decimal_serializer(obj):
        """JSON serializer for objects not serializable by default json code"""
        from decimal import Decimal
        import datetime
        
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")
    
    contenttext = json.dumps(content, indent=4, ensure_ascii=False, default=decimal_serializer)
    log_filename = f_getlogfilename(endpoint, contenttext)
    # Create the JSON file if it doesn't exist
    if not os.path.exists(log_filename):
        with open(log_filename, 'w', encoding='utf-8') as file:
            file.write(contenttext)

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
    log_usage("hello", result)
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
            messages.append(TextMessage(position=position_counter, text="Normalized characters in input question."))
            position_counter += 1
    
    lngpage = request.page or 1

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
    
    # Try to retrieve user question from cache if requested
    if request.retrieve_from_cache:
        messages.append(TextMessage(position=position_counter, text="Attempting to retrieve exact question from cache."))
        position_counter += 1
        with connection.cursor() as cursor:
            cache_result_exact = None
            
            # First, try to find by question_hashed if provided
            if request.question_hashed:
                messages.append(TextMessage(position=position_counter, text="Searching cache by question hash."))
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
                    messages.append(TextMessage(position=position_counter, text="Exact question hash not found in cache."))
                    position_counter += 1
            
            # If not found by hash and we have a question, try to find by question text
            if not cache_result_exact and request.question:
                messages.append(TextMessage(position=position_counter, text="Searching cache by question text."))
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
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing SQL query: {cache_query} | params: [{request.question}, {strapiversionformatted}]"
                ))
                position_counter += 1
                cursor.execute(cache_query, (request.question, strapiversionformatted))
                #print("Cache query executed")
                cache_result_exact = cursor.fetchone()
                if not cache_result_exact:
                    print("Exact question not found in the SQL cache")
                    messages.append(TextMessage(position=position_counter, text="Exact question not found in cache."))
                    position_counter += 1
            
            if cache_result_exact:
                # Found exact result in the SQL cache
                print("Found exact question in the SQL cache")
                cached_exact_question = True
                messages.append(TextMessage(position=position_counter, text="Exact question cache hit used for SQL query."))
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
        messages.append(TextMessage(position=position_counter, text="Cache retrieval disabled; proceeding with full processing."))
        position_counter += 1
    
    # If the exact question was not found in the exact cache, proceed to entity extraction and anonymization
    if not cached_exact_question:
        if request.question:
            messages.append(TextMessage(position=position_counter, text="Using provided question text for processing."))
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
        messages.append(TextMessage(position=position_counter, text="Processed question with entity extraction and anonymization."))
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
            text="Processed question with entity extraction and anonymization."
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
            text=f"Entity extraction result: {entity_extraction_json}"
        ))
        position_counter += 1
        
        # Check if entity extraction was successful
        if isinstance(entity_extraction, dict) and 'error' in entity_extraction:
            print(f"Entity extraction failed: {entity_extraction['error']}")
            print("Falling back to original question without entity extraction")
            messages.append(TextMessage(position=position_counter, text="Entity extraction failed; using original question without anonymization."))
            position_counter += 1
            input_text_anonymized = input_text  # Use original question as fallback
        else:
            print("Entity extraction successful and returned a dictionary:", entity_extraction)
            messages.append(TextMessage(position=position_counter, text="Entity extraction successful; question anonymized."))
            position_counter += 1
            input_text_anonymized = entity_extraction['question']
        cache_result_anonymized = None

        if request.retrieve_from_cache:
            messages.append(TextMessage(position=position_counter, text="Searching cache for anonymized question."))
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
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing SQL query: {cache_query} | params: [{input_text_anonymized}, {strapiversionformatted}]"
                ))
                position_counter += 1
                cursor.execute(cache_query, (input_text_anonymized, strapiversionformatted))
                #print("Cache query executed")
                cache_result_anonymized = cursor.fetchone()
            
            if cache_result_anonymized:
                # Found anonymized question in the SQL cache so we retrieved the question in cache and the SQL query
                print("Found anonymized question in the SQL cache")
                cached_anonymized_question = True
                messages.append(TextMessage(position=position_counter, text="Anonymized question cache hit used for SQL query."))
                position_counter += 1
                input_text_anonymized = cache_result_anonymized['QUESTION']
                sql_query = cache_result_anonymized['SQL_PROCESSED'] or cache_result_anonymized['SQL_QUERY']
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
                messages.append(TextMessage(position=position_counter, text="Anonymized question not found in SQL cache; searching questions embeddings cache."))
                position_counter += 1
                
                # Search for similar anonymized questions in the questions embeddings cache
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
                        messages.append(TextMessage(position=position_counter, text="Found potential matches in questions embeddings cache; filtering by entity variables."))
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
                            messages.append(TextMessage(position=position_counter, text="Embeddings cache hit used for SQL query based on anonymized question."))
                            position_counter += 1
                            
                            # Extract SQL query from metadata
                            metadata = embedding_results['metadatas'][0][valid_result_index]
                            if 'sql_query_anonymized' in metadata:
                                sql_query = metadata['sql_query_anonymized']
                                sql_query_anonymized = sql_query
                                justification = metadata.get('justification', '')
                                justification_anonymized = justification
                                print(f"Retrieved SQL query from questions embeddings cache: {sql_query}")
                                messages.append(TextMessage(position=position_counter, text="SQL query retrieved from questions embeddings cache metadata: " + sql_query_anonymized))
                                position_counter += 1
                            else:
                                print("Warning: No sql_query_anonymized found in metadata")
                                messages.append(TextMessage(position=position_counter, text="Warning: No SQL query found in questions embeddings cache metadata; invalidating cache hit."))
                                position_counter += 1
                                cached_anonymized_question_embedding = False
                        else:
                            print("No results found with all required entity variables and acceptable distance")
                            messages.append(TextMessage(position=position_counter, text="No valid matches found in questions embeddings cache with required entity variables and acceptable similarity."))
                            position_counter += 1
                    else:
                        print("No similar questions found in questions embeddings cache")
                        messages.append(TextMessage(position=position_counter, text="No similar questions found in questions embeddings cache."))
                        position_counter += 1
                        
                except Exception as e:
                    print(f"Error searching questions embeddings cache: {e}")
                    messages.append(TextMessage(position=position_counter, text=f"Error occurred while searching questions embeddings cache: {str(e)}"))
                    position_counter += 1
                    embeddings_cache_search_time = time.time() - embeddings_cache_start_time

        if not cached_exact_question and not cached_anonymized_question and not cached_anonymized_question_embedding:
            # Generate SQL query using existing text2sql function
            text2sql_start_time = time.time()
            json_content = t2s.f_text2sql(input_text_anonymized, strtext2sqlmodel)
            print("JSON content:", json_content)
            sql_query = json_content['sql_query']
            sql_query_anonymized = sql_query
            justification = json_content['justification']
            justification_anonymized = justification
            error_text2sql = json_content['error']
            text2sql_end_time = time.time()
            text2sql_processing_time = text2sql_end_time - text2sql_start_time
            messages.append(TextMessage(position=position_counter, text="Generated new SQL query from anonymized question using Text2SQL LLM."))
            position_counter += 1
            messages.append(TextMessage(position=position_counter, text="SQL query: " + sql_query))
            position_counter += 1
            messages.append(TextMessage(position=position_counter, text="Justification: " + justification))
            position_counter += 1
            messages.append(TextMessage(position=position_counter, text="Error: " + error_text2sql))
            position_counter += 1
    sql_query_llm = sql_query
    # if the error element is found in json content
    if error_text2sql!="" and error_text2sql!=None:
        print("Problem detected so the Text-to-SQL cannot produce a SQL query")
        print("Error: ", error_text2sql)
        ambiguous_question_for_text2sql = 1
        messages.append(TextMessage(position=position_counter, text="Problem detected so the Text-to-SQL cannot produce a SQL query."))
        position_counter += 1

    if not cached_exact_question:
        # Replace entity keys with their values in the SQL query
        if isinstance(entity_extraction, dict):
            messages.append(TextMessage(position=position_counter, text="Replacing entity placeholders with actual values in SQL query."))
            position_counter += 1
            for key, value in entity_extraction.items():
                if key != "question":
                    sql_query = sql_query.replace("{{" + key + "}}", str(value).replace("'", "''"))
                    justification = justification.replace("{{" + key + "}}", str(value).replace("'", "''"))
            print("SQL query after entity replacement:", sql_query)
    
    embeddings_start_time = time.time()
    if not cached_exact_question and not ambiguous_question_for_text2sql:
        # Now we compute embeddings for the SQL query 
        print("Computing embeddings for the SQL query")
        messages.append(TextMessage(position=position_counter, text="Processing entity values using embeddings for entity matching."))
        position_counter += 1
        arrentities = {1: "PERSON_NAME", 2: "MOVIE_TITLE", 3: "SERIE_TITLE", 4: "COMPANY_NAME", 5: "NETWORK_NAME", 6: "TOPIC_NAME", 7: "ITEM_NAME"}
        # Map entity types to their corresponding ChromaDB collections
        chromadb_collections = {1: persons, 2: movies, 3: series, 4: companies, 5: networks, 6: topics, 7: locations}
        
        for intentity,strfieldname in arrentities.items():
            if intentity == 1:
                # Extract values from patterns like PERSON_NAME = 'xxx'
                strtablename = "T_WC_T2S_PERSON"
                strtableid = "ID_PERSON"
                strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strfieldname + " = %s ORDER BY POPULARITY DESC"
            elif intentity == 2:
                # Extract values from patterns like MOVIE_TITLE = 'xxx'
                strtablename = "T_WC_T2S_MOVIE"
                strtableid = "ID_MOVIE"
                strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strfieldname + " = %s ORDER BY POPULARITY DESC"
            elif intentity == 3:
                # Extract values from patterns like SERIE_TITLE = 'xxx'
                strtablename = "T_WC_T2S_SERIE"
                strtableid = "ID_SERIE"
                strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strfieldname + " = %s ORDER BY POPULARITY DESC"
            elif intentity == 4:
                # Extract values from patterns like COMPANY_NAME = 'xxx'
                strtablename = "T_WC_T2S_COMPANY"
                strtableid = "ID_COMPANY"
                strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strfieldname + " = %s"
            elif intentity == 5:
                # Extract values from patterns like NETWORK_NAME = 'xxx'
                strtablename = "T_WC_T2S_NETWORK"
                strtableid = "ID_NETWORK"
                strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strfieldname + " = %s"
            elif intentity == 6:
                # Extract values from patterns like TOPIC_NAME = 'xxx'
                strtablename = "T_WC_T2S_TOPIC"
                strtableid = "ID_TOPIC"
                strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strfieldname + " = %s"
            elif intentity == 7:
                # Extract values from patterns like ITEM_NAME = 'xxx'
                strtablename = "T_WC_WIKIDATA_ITEM"
                strtableid = "ID_WIKIDATA"
                strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strfieldname + " = %s"
            #strfieldpattern = strfieldname + r"\s*=\s*'(.*?)'"
            #strfieldpattern = strfieldname + r"\s*=\s*'((?:[^']|'')*?)'"
            #strfieldpattern = strfieldname + r"\s*=\s*'((?:''|[^'])*?)'"
            # Pattern for FIELD_NAME = 'value' (not followed by another quote)
            strfieldpattern = strfieldname + r"\s*=\s*'((?:[^']|'')*)'(?!')"
            """
            # pattern for FIELD_NAME IN ('value1', 'value2', ...)
            strfieldpattern = strfieldname + r"\s*IN\s*\(\s*'[^']*'(?:\s*,\s*'[^']*')*\s*\)"
            The regex pattern is valid for finding the IN clause in the SQL string.

However, there is a logic issue: The re.findall function with this pattern will return the entire match string (e.g., ["FIELD_NAME IN ('value1', 'value2')"]) because there are no capturing groups around the values themselves.

Your subsequent code expects fieldname_values to be a list of individual values (e.g., ['value1', 'value2']) to iterate over and query the embeddings database.

To fix this, you should separate the logic:

Find the IN clause.
Extract the content inside the parentheses.
Split the values.
I can implement a parsing helper for you if you'd like.
            """
            print(f"DEBUG: Looking for pattern '{strfieldpattern}' in SQL query")
            fieldname_matches = re.findall(strfieldpattern, sql_query, re.IGNORECASE)
            print("Found matches:", fieldname_matches)
            print("Unescaping SQL quotes")
            # Unescape SQL quotes
            fieldname_matches = [match.replace("''", "'") for match in fieldname_matches]
            fieldname_values = [match for match in fieldname_matches]
            
            if fieldname_values:
                print("Extracted " + strfieldname + " values:", fieldname_values)
                messages.append(TextMessage(position=position_counter, text=f"Found {strfieldname} entities in SQL query; processing with embeddings."))
                position_counter += 1
                with connection.cursor() as cursor:
                    for fieldname_value in fieldname_values:
                        print("fieldname_value:", fieldname_value)
                        fieldname_value_escaped = fieldname_value.replace("'", "''")
                        print("Value escaped:", fieldname_value_escaped)
                        sql_query_results = None
                        """
                        print("Looking for SQL query results")
                        cursor.execute(strsql_query, (fieldname_value_escaped,))
                        sql_query_results = cursor.fetchall()
                        #print("SQL query results:", sql_query_results)
                        """
                        
                        # If query returned one or more records, read PERSON_NAME from first record
                        if sql_query_results:
                            """
                            This code is disabled because it is more pertinent to always use embeddings and not rely on exact SQL search 
                            first because when searching "movie le bonheur", for instance, if "le bonheur" was found in the MOVIE_TITLE 
                            field by SQL, it would have the final SQL query looking for "Le Bonheur" which is a French title with a condition
                            on the MOVIE_TITLE column which is for the movies English title 
                            In this case, that final result for "movie le bonheur" would find only two movies (MOVIE_TITLE = "Le Bonheur") 
                            and when searching in the MOVIE_TITLE_FR column (French title), it would find 4 movies which is more relevant 
                            (MOVIE_TITLE_FR = "Le Bonheur")
                            
                            first_record = sql_query_results[0]
                            first_record_value = first_record.get(strfieldname, '')
                            first_record_value_escaped = first_record_value.replace("'", "''")
                            print(f"First SQL record {strfieldname}: {first_record_value}")
                            
                            # Replace the original person_name in sql_query with first_person_name
                            sql_query = sql_query.replace(f"{strfieldname} = '{fieldname_value_escaped}'", f"{strfieldname} = '{first_record_value_escaped}'")
                            print(f"Updated SQL query with actual {strfieldname}")
                            """
                        else:
                            print(f"Not looking for SQL query results or no records found with SQL for {strfieldname}: {fieldname_value}")
                            # Query ChromaDB using a text-based search with the correct collection
                            start_time_chromadb = time.time()
                            #print("Selecting the vector database")
                            if chromadb_collections[intentity] is None:
                                print("No ChromaDB collection found for entity type", intentity)
                                end_time_chromadb = time.time()
                                search_duration_chromadb = end_time_chromadb - start_time_chromadb
                            else:
                                current_collection = chromadb_collections[intentity]
                                print("Querying the vector database")
                                results = current_collection.query(
                                    query_texts=[fieldname_value],  # Query is converted into a vector
                                    n_results=10
                                )
                                print("Querying the vector database done")
                                end_time_chromadb = time.time()
                                search_duration_chromadb = end_time_chromadb - start_time_chromadb
                                if results["documents"][0]:
                                    messages.append(TextMessage(position=position_counter, text=f"Found matching {strfieldname} entity in vector database."))
                                    position_counter += 1
                                    matched_result_position = 0
                                    found_match = False
                                    try:
                                        target_value_norm = str(fieldname_value).strip().lower()
                                    except Exception:
                                        target_value_norm = ""

                                    documents = results.get("documents", [[]])[0] or []
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
                                    
                                    first_record_id = results['ids'][0][matched_result_position]
                                    # Extract the 3 parts from first_record_id using underscore separator
                                    parts = first_record_id.split('_')
                                    docentity = parts[0]
                                    docid = parts[1]
                                    doclang = parts[2]
                                else:
                                    messages.append(TextMessage(position=position_counter, text=f"No matching {strfieldname} entity found in vector database."))
                                    position_counter += 1
                            strfieldnamenew = strfieldname
                            strtableidlookup = strfieldnamenew
                            print("first_record_id", first_record_id, docentity, docid, doclang)
                            if strfieldname == "MOVIE_TITLE":
                                if doclang == "en":
                                    strfieldnamenew = "MOVIE_TITLE"
                                    strtableidlookup = strfieldnamenew
                                elif doclang == "fr":
                                    strfieldnamenew = "MOVIE_TITLE_FR"
                                    strtableidlookup = strfieldnamenew
                                else:
                                    strfieldnamenew = "ORIGINAL_TITLE"
                                    strtableidlookup = strfieldnamenew
                            elif strfieldname == "SERIE_TITLE":
                                if doclang == "en":
                                    strfieldnamenew = "SERIE_TITLE"
                                    strtableidlookup = strfieldnamenew
                                elif doclang == "fr":
                                    strfieldnamenew = "SERIE_TITLE_FR"
                                    strtableidlookup = strfieldnamenew
                                else:
                                    strfieldnamenew = "ORIGINAL_TITLE"
                                    strtableidlookup = strfieldnamenew
                            elif strfieldname == "ITEM_NAME":
                                strfieldnamenew = "ID_ITEM"
                                strtableidlookup = "ID_WIKIDATA"
                            print("strfieldnamenew =", strfieldnamenew, "strtableidlookup =", strtableidlookup)
                            
                            #first_record_value = results['documents'][0][0]
                            strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strtableid + " = %s"
                            print("strsql_query =", strsql_query, docid)
                            messages.append(TextMessage(
                                position=position_counter,
                                text=f"Executing SQL query: {strsql_query} | params: [{docid}]"
                            ))
                            position_counter += 1
                            cursor.execute(strsql_query, (docid,))
                            sql_query_results = cursor.fetchall()
                            first_record = sql_query_results[0]
                            print("first_record:", first_record)
                            print("get", strtableidlookup)
                            first_record_value = first_record.get(strtableidlookup, '')
                            print("first_record_value:", first_record_value)
                            # Escape single quotes for SQL integration
                            first_record_value_escaped = first_record_value.replace("'", "''")
                            print("First record value escaped:", first_record_value_escaped)
                            
                            print(f"SQL query results for '{fieldname_value}'")
                            print(f"{strfieldname} query: {fieldname_value}")
                            print(f"Search time: {search_duration_chromadb:.4f} seconds")
                            print(f"First result ID: {first_record_id}")
                            print(f"{strfieldname}: {first_record_value}")
                            if chromadb_collections[intentity] is not None:
                                print(f"Distance: {results['distances'][0][0]:.4f}")
                            print(f"{strfieldname} = '{fieldname_value_escaped}'", f"{strfieldnamenew} = '{first_record_value_escaped}'")
                            sql_query = sql_query.replace(f"{strfieldname} = '{fieldname_value_escaped}'", f"{strfieldnamenew} = '{first_record_value_escaped}'")
                            print(f"Updated SQL query with actual {strfieldname}")
                            messages.append(TextMessage(position=position_counter, text=f"Updated SQL query: replaced {strfieldname} with matched entity value."))
                            position_counter += 1
    embeddings_end_time = time.time()
    embeddings_processing_time = embeddings_end_time - embeddings_start_time
    
    # Execute the SQL query and get results
    query_results = []
    query_execution_time = 0.0
    if not ambiguous_question_for_text2sql:
        messages.append(TextMessage(position=position_counter, text="Preparing to execute SQL query."))
        position_counter += 1
        with connection.cursor() as cursor:
            # Measure SQL query execution time
            query_start_time = time.time()
            # Calculate pagination parameters
            limit = lngrowsperpage
            calculated_offset = (lngpage - 1) * lngrowsperpage
            
            # Check if SQL query already has LIMIT/OFFSET
            match = re.search(r"\blimit\b\s+(\d+)(?:\s*,\s*(\d+))?", sql_query, re.IGNORECASE)
            if match:
                messages.append(TextMessage(position=position_counter, text="SQL query contains existing LIMIT/OFFSET clause; removing for pagination."))
                position_counter += 1
                # SQL query already has LIMIT, extract existing values
                llm_defined_limit = int(match.group(1))
                llm_defined_offset = int(match.group(2)) if match.group(2) else None
                print("FOUND EXISTING LIMIT:", llm_defined_limit, "OFFSET:", llm_defined_offset)
                
                # Remove existing LIMIT clause to replace with paginated version
                sql_query = re.sub(r"\blimit\b\s+\d+(?:\s*,\s*\d+)?", "", sql_query, flags=re.IGNORECASE).strip()
            
            # Add pagination: LIMIT and OFFSET based on page number
            if lngpage > 1:
                messages.append(TextMessage(position=position_counter, text=f"Adding pagination: LIMIT {limit} OFFSET {calculated_offset} for page {lngpage}."))
                position_counter += 1
                sql_query = sql_query + f" LIMIT {limit} OFFSET {calculated_offset}"
                offset = calculated_offset
            else:
                messages.append(TextMessage(position=position_counter, text=f"Adding pagination: LIMIT {limit} for first page."))
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
                messages.append(TextMessage(position=position_counter, text=f"Database query execution failed: {str(e)}"))
                position_counter += 1
                # Database errors not returned directly to clients
                # query_results = [{"error": str(e)}]
        query_end_time = time.time()
        query_execution_time = query_end_time - query_start_time
        messages.append(TextMessage(position=position_counter, text=f"Executed SQL query with pagination: page={lngpage}, limit={limit}, offset={offset}."))
        position_counter += 1
    else:
        messages.append(TextMessage(position=position_counter, text="Skipping SQL query execution due to ambiguous question."))
        position_counter += 1
    
    # Generate hash for the question if not provided
    if not ambiguous_question_for_text2sql:
        question_hash = request.question_hashed
        if not question_hash:
            messages.append(TextMessage(position=position_counter, text="Generating question hash for caching."))
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
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing SQL insert into cache: {insert_query} | params: [question={request.question}, hash={question_hash}]"
                ))
                position_counter += 1
                cursor2.execute(insert_query, (
                    request.question,
                    question_hash,
                    sql_query_llm,
                    sql_query,
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
            messages.append(TextMessage(position=position_counter, text="Storing anonymized question and SQL query to cache."))
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
                messages.append(TextMessage(
                    position=position_counter,
                    text=f"Executing SQL insert into cache (anonymized): {insert_query} | params: [question={input_text_anonymized}, hash={question_hash}]"
                ))
                position_counter += 1
                cursor2.execute(insert_query, (
                    input_text_anonymized,
                    question_hash,
                    sql_query_llm,
                    sql_query_anonymized,
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
        
        if request.store_to_cache and not cached_anonymized_question_embedding and input_text_anonymized:
            messages.append(TextMessage(position=position_counter, text="Checking if anonymized question exists in embeddings cache before storing."))
            position_counter += 1
            strdocid = hashlib.sha256(input_text_anonymized.encode('utf-8')).hexdigest()
            print("Anonymized query ID:", strdocid)
            existing_doc = anonymizedqueries.get(ids=[strdocid])
            if existing_doc and existing_doc['ids']:
                print("Anonymized question already exists in the embeddings cache")
                messages.append(TextMessage(position=position_counter, text="Anonymized question already exists in embeddings cache; skipping storage."))
                position_counter += 1
            else:
                messages.append(TextMessage(position=position_counter, text="Storing anonymized question and SQL query to embeddings cache."))
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
    messages.append(TextMessage(position=position_counter, text="Database connection closed."))
    position_counter += 1
    
    # Generate question hash if we have a question and no hash was provided
    response_question_hash = request.question_hashed
    if not response_question_hash and request.question:
        response_question_hash = hashlib.sha256(request.question.encode('utf-8')).hexdigest()
    
    # Compute the final global processing time with also the write cache operations (SQL and embeddings)
    total_end_time = time.time()
    total_processing_time = total_end_time - total_start_time
    
    messages.append(TextMessage(position=position_counter, text="Completed request processing and prepared response."))

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
    log_usage("text2sql_post", log_data)
    
    return response

if __name__ == "__main__":
    import uvicorn
    
    # Determine port based on version: even = API_PORT_BLUE, odd = API_PORT_GREEN
    version_parts = strapiversion.split('.')
    patch_version = int(version_parts[2])  # Use patch version (last number)
    api_port = API_PORT_BLUE if patch_version % 2 == 0 else API_PORT_GREEN
    
    result = {"message": f"Text2SQL API start version {strapiversion} on port {api_port}"}
    log_usage("start", result)
    print(f"Starting API version {strapiversion} on port {api_port} (patch version {patch_version} is {'even' if patch_version % 2 == 0 else 'odd'})")
    uvicorn.run(app, host="0.0.0.0", port=api_port)
