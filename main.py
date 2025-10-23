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

# Load environment variables from .env file
load_dotenv()

# Change API version each time the prompt file in the data folder is updated and text2sql API container is restarted
strapiversion = "1.1.4"
# Convert API version to XXX.YYY.ZZZ format
version_parts = strapiversion.split('.')
strapiversionformatted = f"{int(version_parts[0]):03d}.{int(version_parts[1]):03d}.{int(version_parts[2]):03d}"

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
#Anonymized queries collection
strentitycollection = "anonymizedqueries"
anonymizedqueries = chroma_client.get_or_create_collection(
    name=strentitycollection,
    embedding_function=embedding_function  # Custom embedding model
)

lngrowsperpage=50

app = FastAPI(title="Text2SQL API", version=strapiversion, description="Text2SQL API for text to SQL query conversion")

# Database connection function
def get_db_connection():
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

class TextExpr(BaseModel):
    text: str
    sql_query: str = ""

class Text2SQLRequest(BaseModel):
    question: Optional[str] = None
    question_hashed: Optional[str] = None  # For pagination/disambiguation
    page: Optional[int] = 1
    disambiguation_data: Optional[dict] = None  # Flexible structure
    retrieve_from_cache: bool = True
    store_to_cache: bool = True
    llm_model: Optional[str] = "default"
    
    @model_validator(mode='after')
    def validate_question_or_hashed(self):
        if not self.question and not self.question_hashed:
            raise ValueError('Either question or question_hashed must be provided')
        return self

class Text2SQLResponse(BaseModel):
    question: str
    question_hashed: Optional[str] = None
    sql_query: str
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
    llm_model: str
    result: List[dict] = []  # Array of records with index and data

class ResultItem(BaseModel):
    sql_query: str

LOGS_FOLDER = "logs"

def f_getlogfilename(endpoint, contenttext):
    os.makedirs(LOGS_FOLDER, exist_ok=True)
    now = datetime.now()
    date_time_str = now.strftime("%Y%m%d-%H%M%S")
    md5_hash = hashlib.md5(contenttext.encode('utf-8')).hexdigest()
    filename = f"{LOGS_FOLDER}/{date_time_str}_{endpoint}_{strapiversion}_{md5_hash}.json"
    return filename

def log_usage(endpoint, content):
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
    global answer
    result = {"message": "hello world! The universal answer is " + str(answer)}
    log_usage("hello", result)
    return result

@app.post("/search/text2sql", response_model=Text2SQLResponse)
async def search_text2sql(request: Text2SQLRequest, api_key: str = Depends(get_api_key)):
    total_start_time = time.time()
    
    # Strip whitespace and carriage return characters from question if provided
    if request.question:
        request.question = request.question.strip().strip('\n').strip('\r').strip('\n')
    
    lngpage = request.page or 1

    # Open database connection once at the start
    connection = get_db_connection()
    print("Database connection established")
    
    # Initialize variables
    cached_exact_question = False
    cached_anonymized_question = False
    cached_anonymized_question_embedding = False
    sql_query = None
    llm_defined_limit = None
    llm_defined_offset = None
    limit = None
    offset = None
    input_text = None
    input_text_anonymized = None
    entity_extraction_processing_time = 0.0
    text2sql_processing_time = 0.0
    embeddings_processing_time = 0.0
    embeddings_cache_search_time = 0.0
    query_execution_time = 0.0
    total_processing_time = 0.0
    ambiguous_question_for_text2sql = 0
    
    # Try to retrieve user question from cache if requested
    if request.retrieve_from_cache:
        with connection.cursor() as cursor:
            cache_result_exact = None
            
            # First, try to find by question_hashed if provided
            if request.question_hashed:
                cache_query = """
SELECT QUESTION, SQL_QUERY, SQL_PROCESSED, ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME 
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
            
            # If not found by hash and we have a question, try to find by question text
            if not cache_result_exact and request.question:
                cache_query = """
SELECT QUESTION, SQL_QUERY, SQL_PROCESSED, ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME 
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
            
            if cache_result_exact:
                # Found exact result in the SQL cache
                print("Found exact question in the SQL cache")
                cached_exact_question = True
                input_text = cache_result_exact['QUESTION']
                sql_query = cache_result_exact['SQL_PROCESSED'] or cache_result_exact['SQL_QUERY']
                # Because the SQL query can be updated in the t2scache.php back-office script,
                # we need to replace &#039; by ' because the back-office script stores &#039; instead of ' in the database
                sql_query = sql_query.replace("&#039;", "'")
                #entity_extraction_processing_time = cache_result_exact['ENTITY_EXTRACTION_PROCESSING_TIME']
                #text2sql_processing_time = cache_result_exact['TEXT2SQL_PROCESSING_TIME']
                #embeddings_processing_time = cache_result_exact['EMBEDDINGS_TIME']
                #query_execution_time = cache_result_exact['QUERY_TIME']
    
    # If the exact question was not found in the exact cache, proceed to entity extraction and anonymization
    if not cached_exact_question:
        if request.question:
            input_text = request.question
        elif request.question_hashed:
            # If we have question_hashed but no cache hit, we can't proceed without the original question
            raise ValueError("question_hashed provided but no entry found in the SQL cache and no original question provided")
        else:
            raise ValueError("Either question or question_hashed must be provided")
        
        # Anonymize question by entity extraction
        entity_extraction_start_time = time.time()
        entity_extraction = t2s.f_entity_extraction(input_text)
        print("Entity extraction:", entity_extraction)
        entity_extraction_end_time = time.time()
        entity_extraction_processing_time = entity_extraction_end_time - entity_extraction_start_time
        
        # Check if entity extraction was successful
        if isinstance(entity_extraction, dict) and 'error' in entity_extraction:
            print(f"Entity extraction failed: {entity_extraction['error']}")
            print("Falling back to original question without entity extraction")
            input_text_anonymized = input_text  # Use original question as fallback
        else:
            print("Entity extraction successful and returned a dictionary:", entity_extraction)
            input_text_anonymized = entity_extraction['question']
        cache_result_anonymized = None

        if request.retrieve_from_cache:
            # Is this anonymized query in the SQL cache?
            with connection.cursor() as cursor:
                cache_query = """
SELECT QUESTION, SQL_QUERY, SQL_PROCESSED, ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME 
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
                if not cache_result_anonymized:
                    print("Anonymized question not found in the SQL cache")
            
            if cache_result_anonymized:
                # Found anonymized question in the SQL cache so we retrieved the question in cache and the SQL query
                print("Found anonymized question in the SQL cache")
                cached_anonymized_question = True
                input_text_anonymized = cache_result_anonymized['QUESTION']
                sql_query = cache_result_anonymized['SQL_PROCESSED'] or cache_result_anonymized['SQL_QUERY']
                # Because the SQL query can be updated in the t2scache.php back-office script,
                # we need to replace &#039; by ' because the back-office script stores &#039; instead of ' in the database
                sql_query = sql_query.replace("&#039;", "'")
                sql_query_anonymized = sql_query
                #entity_extraction_processing_time = cache_result_anonymized['ENTITY_EXTRACTION_PROCESSING_TIME']
                #text2sql_processing_time = cache_result_anonymized['TEXT2SQL_PROCESSING_TIME']
                #embeddings_processing_time = cache_result_anonymized['EMBEDDINGS_TIME']
                #query_execution_time = cache_result_anonymized['QUERY_TIME']
            else:
                print("Anonymized question not found in the SQL cache")
                print("So we will look for the anonymized question in the embeddings cache")
                
                # Search for similar anonymized questions in the embeddings cache
                embeddings_cache_start_time = time.time()
                try:
                    print(f"Searching embeddings cache for: {input_text_anonymized}")
                    embedding_results = anonymizedqueries.query(
                        query_texts=[input_text_anonymized],
                        n_results=1,
                        include=['documents', 'metadatas', 'distances']
                    )
                    embeddings_cache_end_time = time.time()
                    embeddings_cache_search_time = embeddings_cache_end_time - embeddings_cache_start_time
                    
                    print(f"Embeddings cache search completed in {embeddings_cache_search_time:.4f} seconds")
                    
                    if embedding_results['documents'][0] and len(embedding_results['documents'][0]) > 0:
                        # Found similar question in embeddings cache
                        distance = embedding_results['distances'][0][0]
                        print(f"Found similar anonymized question in embeddings cache with distance: {distance}")
                        
                        # Use a similarity threshold (e.g., distance < 0.1 for very similar questions)
                        similarity_threshold = 0.1
                        if distance < similarity_threshold:
                            print("Distance is below threshold, using cached result")
                            cached_anonymized_question_embedding = True
                            
                            # Extract SQL query from metadata
                            metadata = embedding_results['metadatas'][0][0]
                            if 'sql_query_anonymized' in metadata:
                                sql_query = metadata['sql_query_anonymized']
                                sql_query_anonymized = sql_query
                                print(f"Retrieved SQL query from embeddings cache: {sql_query}")
                            else:
                                print("Warning: No sql_query_anonymized found in metadata")
                                cached_anonymized_question_embedding = False
                        else:
                            print(f"Distance {distance} is above threshold {similarity_threshold}, not using cached result")
                    else:
                        print("No similar questions found in embeddings cache")
                        
                except Exception as e:
                    print(f"Error searching embeddings cache: {e}")
                    embeddings_cache_search_time = time.time() - embeddings_cache_start_time

        if not cached_exact_question and not cached_anonymized_question and not cached_anonymized_question_embedding:
            # Generate SQL query using existing text2sql function
            text2sql_start_time = time.time()
            sql_query = t2s.f_text2sql(input_text_anonymized)
            sql_query_anonymized = sql_query
            text2sql_end_time = time.time()
            text2sql_processing_time = text2sql_end_time - text2sql_start_time
    sql_query_llm = sql_query
    # if the ##AMBIGUOUS## string is found in sql_query
    if "##AMBIGUOUS##" in sql_query:
        print("AMBIGUOUS question so the Text-to-SQL cannot produce a SQL query")
        ambiguous_question_for_text2sql = 1

    if not cached_exact_question:
        # Replace entity keys with their values in the SQL query
        if isinstance(entity_extraction, dict):
            for key, value in entity_extraction.items():
                if key != "question":
                    sql_query = sql_query.replace("{{" + key + "}}", str(value).replace("'", "''"))
            print("SQL query after entity replacement:", sql_query)
    
    embeddings_start_time = time.time()
    if not cached_exact_question and not ambiguous_question_for_text2sql:
        # Now we compute embeddings for the SQL query 
        print("Computing embeddings for the SQL query")
        arrentities = {1: "PERSON_NAME", 2: "MOVIE_TITLE", 3: "SERIE_TITLE", 4: "COMPANY_NAME", 5: "NETWORK_NAME", 6: "TOPIC_NAME"}
        # Map entity types to their corresponding ChromaDB collections
        chromadb_collections = {1: persons, 2: movies, 3: series, 4: companies, 5: networks, 6: topics}
        
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
            #strfieldpattern = strfieldname + r"\s*=\s*'(.*?)'"
            #strfieldpattern = strfieldname + r"\s*=\s*'((?:[^']|'')*?)'"
            #strfieldpattern = strfieldname + r"\s*=\s*'((?:''|[^'])*?)'"
            strfieldpattern = strfieldname + r"\s*=\s*'((?:[^']|'')*)'(?!')"
            print(f"DEBUG: Looking for pattern '{strfieldpattern}' in SQL query")
            fieldname_matches = re.findall(strfieldpattern, sql_query, re.IGNORECASE)
            print("Found matches:", fieldname_matches)
            print("Unescaping SQL quotes")
            # Unescape SQL quotes
            fieldname_matches = [match.replace("''", "'") for match in fieldname_matches]
            fieldname_values = [match for match in fieldname_matches]
            
            if fieldname_values:
                print("Extracted " + strfieldname + " values:", fieldname_values)
                with connection.cursor() as cursor:
                    for fieldname_value in fieldname_values:
                        print("fieldname_value:", fieldname_value)
                        fieldname_value_escaped = fieldname_value.replace("'", "''")
                        print("Value escaped:", fieldname_value_escaped)
                        cursor.execute(strsql_query, (fieldname_value_escaped,))
                        sql_query_results = cursor.fetchall()
                        #print("SQL query results:", sql_query_results)
                        
                        # If query returned one or more records, read PERSON_NAME from first record
                        if sql_query_results:
                            first_record = sql_query_results[0]
                            first_record_value = first_record.get(strfieldname, '')
                            first_record_value_escaped = first_record_value.replace("'", "''")
                            print(f"First SQL record {strfieldname}: {first_record_value}")
                            
                            # Replace the original person_name in sql_query with first_person_name
                            sql_query = sql_query.replace(f"{strfieldname} = '{fieldname_value_escaped}'", f"{strfieldname} = '{first_record_value_escaped}'")
                            print(f"Updated SQL query with actual {strfieldname}")
                        else:
                            print(f"No records found with SQL for {strfieldname}: {fieldname_value}")
                            # Query ChromaDB using a text-based search with the correct collection
                            start_time_chromadb = time.time()
                            #print("Selecting the vector database")
                            current_collection = chromadb_collections[intentity]
                            print("Querying the vector database")
                            results = current_collection.query(
                                query_texts=[fieldname_value],  # Query is converted into a vector
                                n_results=1
                            )
                            print("Querying the vector database done")
                            end_time_chromadb = time.time()
                            search_duration_chromadb = end_time_chromadb - start_time_chromadb
                            if results["documents"][0]:
                                first_record_id = results['ids'][0][0]
                                # Extract the 3 parts from first_record_id using underscore separator
                                parts = first_record_id.split('_')
                                docentity = parts[0]
                                docid = parts[1]
                                doclang = parts[2]
                                strfieldnamenew = strfieldname
                                if strfieldname == "MOVIE_TITLE":
                                    if doclang == "en":
                                        strfieldnamenew = "MOVIE_TITLE"
                                    elif doclang == "fr":
                                        strfieldnamenew = "MOVIE_TITLE_FR"
                                    else:
                                        strfieldnamenew = "ORIGINAL_TITLE"
                                elif strfieldname == "SERIE_TITLE":
                                    if doclang == "en":
                                        strfieldnamenew = "SERIE_TITLE"
                                    elif doclang == "fr":
                                        strfieldnamenew = "SERIE_TITLE_FR"
                                    else:
                                        strfieldnamenew = "ORIGINAL_TITLE"
                                
                                #first_record_value = results['documents'][0][0]
                                strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strtableid + " = %s"
                                cursor.execute(strsql_query, (docid,))
                                sql_query_results = cursor.fetchall()
                                first_record = sql_query_results[0]
                                first_record_value = first_record.get(strfieldnamenew, '')
                                # Escape single quotes for SQL integration
                                first_record_value_escaped = first_record_value.replace("'", "''")
                                print("First record value escaped:", first_record_value_escaped)
                                
                                print(f"SQL query results for '{fieldname_value}'")
                                print(f"{strfieldname} query: {fieldname_value}")
                                print(f"Search time: {search_duration_chromadb:.4f} seconds")
                                print(f"First result ID: {first_record_id}")
                                print(f"{strfieldname}: {first_record_value}")
                                print(f"Distance: {results['distances'][0][0]:.4f}")
                                sql_query = sql_query.replace(f"{strfieldname} = '{fieldname_value_escaped}'", f"{strfieldnamenew} = '{first_record_value_escaped}'")
                                print(f"Updated SQL query with actual {strfieldname}")
    embeddings_end_time = time.time()
    embeddings_processing_time = embeddings_end_time - embeddings_start_time
    
    # Execute the SQL query and get results
    query_results = []
    query_execution_time = 0.0
    if not ambiguous_question_for_text2sql:
        with connection.cursor() as cursor:
            # Measure SQL query execution time
            query_start_time = time.time()
            # Calculate pagination parameters
            limit = lngrowsperpage
            calculated_offset = (lngpage - 1) * lngrowsperpage
            
            # Check if SQL query already has LIMIT/OFFSET
            match = re.search(r"\blimit\b\s+(\d+)(?:\s*,\s*(\d+))?", sql_query, re.IGNORECASE)
            if match:
                # SQL query already has LIMIT, extract existing values
                llm_defined_limit = int(match.group(1))
                llm_defined_offset = int(match.group(2)) if match.group(2) else None
                print("FOUND EXISTING LIMIT:", llm_defined_limit, "OFFSET:", llm_defined_offset)
                
                # Remove existing LIMIT clause to replace with paginated version
                sql_query = re.sub(r"\blimit\b\s+\d+(?:\s*,\s*\d+)?", "", sql_query, flags=re.IGNORECASE).strip()
            
            # Add pagination: LIMIT and OFFSET based on page number
            if lngpage > 1:
                sql_query = sql_query + f" LIMIT {limit} OFFSET {calculated_offset}"
                offset = calculated_offset
            else:
                sql_query = sql_query + f" LIMIT {limit}"
                offset = 0
                
            print(f"PAGINATION: Page={lngpage}, LIMIT={limit}, OFFSET={offset}")
            print("LIMIT:", limit, "OFFSET:", offset)
            print("SQL query execution:", sql_query)
            try: 
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
                query_results = [{"error": str(e)}]
        query_end_time = time.time()
        query_execution_time = query_end_time - query_start_time
    
        # Generate hash for the question if not provided
        question_hash = request.question_hashed
        if not question_hash:
            question_hash = hashlib.sha256(request.question.encode('utf-8')).hexdigest()
        
        # Compute the temporary global processing time before the write cache operations (SQL and embeddings)
        total_end_time = time.time()
        total_processing_time = total_end_time - total_start_time
        # Store to SQL cache if requested and not already stored as exact question or anonymized question
        if request.store_to_cache and not cached_exact_question and request.question:
            with connection.cursor() as cursor2:
                # Insert exact question into cache table
                insert_query = """
INSERT INTO T_WC_T2S_CACHE 
(QUESTION, QUESTION_HASHED, SQL_QUERY, SQL_PROCESSED, API_VERSION, 
ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME, TOTAL_PROCESSING_TIME, 
DELETED, DAT_CREAT, TIM_UPDATED) 
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), NOW())
"""
                print("Insert query:", insert_query)
                # Use the actual measured query execution time
                query_time = query_execution_time
                cursor2.execute(insert_query, (
                    request.question,
                    question_hash,
                    sql_query_llm,
                    sql_query,
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
            with connection.cursor() as cursor2:
                # Insert anonymized question into cache table
                insert_query = """
INSERT INTO T_WC_T2S_CACHE 
(QUESTION, QUESTION_HASHED, SQL_QUERY, SQL_PROCESSED, API_VERSION, 
ENTITY_EXTRACTION_PROCESSING_TIME, TEXT2SQL_PROCESSING_TIME, EMBEDDINGS_TIME, QUERY_TIME, TOTAL_PROCESSING_TIME, 
DELETED, DAT_CREAT, TIM_UPDATED) 
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), NOW())
"""
                print("Insert query:", insert_query)
                # Use the actual measured query execution time
                query_time = query_execution_time
                cursor2.execute(insert_query, (
                    input_text_anonymized,
                    question_hash,
                    sql_query_llm,
                    sql_query_anonymized,
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
            strdocid = hashlib.md5(input_text_anonymized.encode('utf-8')).hexdigest()
            print("Anonymized query ID:", strdocid)
            existing_doc = anonymizedqueries.get(ids=[strdocid])
            if existing_doc and existing_doc['ids']:
                print("Anonymized question already exists in the embeddings cache")
            else:
                anonymizedqueries.add(
                    ids=[strdocid],
                    documents=[input_text_anonymized],
                    metadatas=[{
                            "sql_query_anonymized": sql_query_anonymized,
                            "api_version": strapiversionformatted,
                            "entity_extraction_processing_time": entity_extraction_processing_time,
                            "text2sql_processing_time": text2sql_processing_time,
                            "dat_creat": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }]
                )
                print("Anonymized question added to the embeddings cache with the anonymized SQL query")
    
    connection.close()
    
    # Generate question hash if we have a question and no hash was provided
    response_question_hash = request.question_hashed
    if not response_question_hash and request.question:
        response_question_hash = hashlib.sha256(request.question.encode('utf-8')).hexdigest()
    
    # Compute the final global processing time with also the write cache operations (SQL and embeddings)
    total_end_time = time.time()
    total_processing_time = total_end_time - total_start_time
    response = Text2SQLResponse(
        question=input_text,
        question_hashed=response_question_hash,
        sql_query=sql_query,
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
        llm_model=request.llm_model,
        result=query_results
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

