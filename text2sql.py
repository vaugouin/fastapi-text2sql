import pandas as pd 
import numpy as np 
#pip install psutil
import psutil

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

strprompttemplate = "prompt-chatgpt-4o-1-0-9-20250724.txt"

# Read the prompt_template from the data/prompt.txt file
with open('./data/' + strprompttemplate, 'r') as file:
    prompt_template = file.read()
    
def f_text2sql(user_question: str):
    """Convert natural language question to SQL query using LangChain and LLM.
    
    Args:
        user_question (str): The user's natural language question
        
    Returns:
        str: The generated SQL query
    """
    import os
    from dotenv import load_dotenv
    import openai
    from langchain_core.prompts import PromptTemplate
    from langchain_openai import OpenAI
    
    # Load environment variables (OPENAI_API_KEY)
    load_dotenv()
    
    # Check if API key is available
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Warning: OPENAI_API_KEY not found in environment variables")
        return "Error: API key not configured"
    
    try:
        # Set up the OpenAI client
        client = openai.OpenAI(api_key=api_key)
        
       
        # Use the prompt_template from the data/prompt.txt file
        formatted_prompt = prompt_template.format(user_question=user_question)
        
        # Make a direct call to OpenAI API
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
            sql_query = sql_query[6:]
        
        # Check if sql_query ends with ``` and remove it
        if sql_query.endswith("```"):
            sql_query = sql_query[:-3]
            
        # Replace escaped newlines (\n) with spaces
        sql_query = sql_query.replace("\\n", " ")
            
        # Strip any remaining whitespace
        sql_query = sql_query.strip()
        
        print(sql_query)
        return sql_query
    
    except Exception as e:
        print(f"Error in text2sql conversion: {str(e)}")
        return f"Error: {str(e)}"

