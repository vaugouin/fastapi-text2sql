import pandas as pd 
import numpy as np 
#pip install psutil
import psutil

import os
import json
from dotenv import load_dotenv
import openai
from langchain_core.prompts import PromptTemplate
from langchain_openai import OpenAI

# Get the virtual memory details
memory_info = psutil.virtual_memory()
# Print the available memory
print("Démarrage de l'API")
print(f"Total Memory: {memory_info.total / (1024 ** 3):.2f} GB")
print(f"Available Memory: {memory_info.available / (1024 ** 3):.2f} GB")
print(f"Used Memory: {memory_info.used / (1024 ** 3):.2f} GB")
print(f"Free Memory: {memory_info.free / (1024 ** 3):.2f} GB")
print(f"Memory Usage: {memory_info.percent}%")

dblavailableram=memory_info.available / (1024 ** 3)

strtext2sqlprompttemplate = "prompt-chatgpt-4o-1-1-4-20251008.txt"

# Entity extraction feature
strentityextractionprompttemplate = "entity-extraction-chatgpt-4o-1-1-4-20251008.txt"

#print("Text to SQL prompt template", strtext2sqlprompttemplate)
#print("Entity extraction prompt template", strentityextractionprompttemplate)

# Read the text2sql_prompt_template from the data/prompt.txt file
with open('./data/' + strtext2sqlprompttemplate, 'r') as file:
    text2sql_prompt_template = file.read()

# Read the entity_extraction_prompt_template from the data/prompt.txt file
with open('./data/' + strentityextractionprompttemplate, 'r') as file:
    entity_extraction_prompt_template = file.read()

# Load environment variables (OPENAI_API_KEY)
load_dotenv()

# Check if API key is available
api_key = os.getenv("OPENAI_API_KEY")

def f_entity_extraction(user_question: str):
    """Extract entities from natural language question using LangChain and LLM.
    
    Args:
        user_question (str): The user's natural language question
    
    Returns:
        dict: A dictionary containing the extracted entities
    """
    print("Entity extraction")
    print("User question:", user_question)
    if not api_key:
        print("Warning: OPENAI_API_KEY not found in environment variables")
        return "Error: API key not configured"
    
    try:
        # Set up the OpenAI client
        #print("Setting up OpenAI client")
        client = openai.OpenAI(api_key=api_key)
        
        # Use the entity_extraction_prompt_template from the data/prompt.txt file
        #print("Entity extraction prompt template")
        try:
            # Replace the placeholder with the actual user question
            formatted_prompt = entity_extraction_prompt_template.replace("{user_question}", user_question)
        except Exception as format_error:
            print(f"Error formatting prompt template: {str(format_error)}")
            #print(f"Template content preview: {entity_extraction_prompt_template[:200]}...")
            print(f"User question: '{user_question}'")
            return {"error": f"Prompt formatting failed: {str(format_error)}"}
        
        # Make a direct call to OpenAI API
        #print("Making a direct call to OpenAI API")
        #print(f"Formatted prompt length: {len(formatted_prompt)}")
        #print(f"Formatted prompt preview: {formatted_prompt[:200]}...")
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",  # Using GPT-4o for better result
                temperature=0,  # Use deterministic output for entity extraction
                messages=[
                    {"role": "system", "content": "You are a powerful entity extraction tool. Respond only with the JSON content, no explanations."},
                    {"role": "user", "content": formatted_prompt}
                ]
            )
        except Exception as api_error:
            print(f"OpenAI API call failed: {str(api_error)}")
            print(f"API error type: {type(api_error)}")
            return {"error": f"OpenAI API call failed: {str(api_error)}"}
        
        # Extract the JSON content from the response
        print(f"Response object: {response}")
        print(f"Response choices: {response.choices}")
        
        if not response.choices or len(response.choices) == 0:
            print("ERROR: No choices in API response")
            return {"error": "No choices in API response"}
        
        if not response.choices[0].message or not response.choices[0].message.content:
            print("ERROR: No content in API response message")
            return {"error": "No content in API response message"}
        
        json_content = response.choices[0].message.content.strip()

        # Check if json_content starts with ```json and remove it
        if json_content.startswith("```json"):
            json_content = json_content[7:].strip()
        
        # Check if json_content ends with ``` and remove it
        if json_content.endswith("```"):
            json_content = json_content[:-3].strip()
        
        print(f"Raw API response: '{json_content}'")
        print(f"Response length: {len(json_content)}")
        print(f"Response type: {type(json_content)}")
        
        # Try to clean up the response and handle common issues
        cleaned_content = json_content.strip().strip('\n').strip('\r').strip('\n')
        
        # Check if the response looks like it might be truncated or incomplete
        if not cleaned_content.startswith('{') or not cleaned_content.endswith('}'):
            print("WARNING: Response doesn't look like complete JSON")
            # Try to fix common issues
            if cleaned_content.startswith('"question"'):
                # If it starts with "question", try to wrap it in braces
                cleaned_content = '{' + cleaned_content + '}'
                print(f"Attempting to fix malformed JSON: {cleaned_content}")
            else:
                return {"error": "Incomplete JSON response from API", "raw_content": json_content}
        
        # Parse the JSON string into a Python dictionary
        try:
            entity_extraction = json.loads(cleaned_content)
            print(f"Successfully parsed JSON: {entity_extraction}")
            return entity_extraction
        except json.JSONDecodeError as json_error:
            print(f"JSON parsing error in entity extraction: {str(json_error)}")
            print(f"Raw response content: '{json_content}'")
            print(f"Cleaned content: '{cleaned_content}'")
            return {"error": f"JSON parsing failed: {str(json_error)}", "raw_content": json_content}
    
    except Exception as e:
        print(f"Error in entity extraction: {str(e)}")
        return {"error": str(e)}

def f_text2sql(user_question: str):
    """Convert natural language question to SQL query using LangChain and LLM.
    
    Args:
        user_question (str): The user's natural language question
        
    Returns:
        str: The generated SQL query
    """
    """
    import os
    from dotenv import load_dotenv
    import openai
    from langchain_core.prompts import PromptTemplate
    from langchain_openai import OpenAI
    """
    print("Text to SQL")
    print("User question:", user_question)
    if not api_key:
        print("Warning: OPENAI_API_KEY not found in environment variables")
        return "Error: API key not configured"
    
    try:
        # Set up the OpenAI client
        #print("Setting up OpenAI client")
        client = openai.OpenAI(api_key=api_key)
        
        # Use the text2sql_prompt_template from the data/prompt.txt file
        #print("Text to SQL prompt template")
        formatted_prompt = text2sql_prompt_template.replace("{user_question}", user_question)
        
        # Make a direct call to OpenAI API
        #print("Making a direct call to OpenAI API")
        response = client.chat.completions.create(
            model="gpt-4o",  # Using GPT-4o for better SQL generation
            temperature=0,  # Use deterministic output for SQL queries
            messages=[
                {"role": "system", "content": "You are a SQL query generator. Respond only with the SQL query, no explanations."},
                {"role": "user", "content": formatted_prompt}
            ]
        )
        
        # Extract the SQL query from the response
        sql_query = response.choices[0].message.content.strip()
        
        # Check if sql_query starts with ```sql and remove it
        if sql_query.startswith("```sql"):
            sql_query = sql_query[6:].strip()
        
        # Check if sql_query ends with ``` and remove it
        if sql_query.endswith("```"):
            sql_query = sql_query[:-3].strip()

        if sql_query.endswith(";"):
            sql_query = sql_query[:-1].strip()
            
        # Replace escaped newlines (\n) with spaces
        sql_query = sql_query.replace("\\n", " ")
            
        # Strip any remaining whitespace
        sql_query = sql_query.strip()
        
        print(f"Generated SQL query: {sql_query}")
        return sql_query
    
    except Exception as e:
        print(f"Error in text2sql conversion: {str(e)}")
        return f"Error: {str(e)}"

