#cd fastapi-text2sql
#python main.py

from typing import List
from fastapi import FastAPI, Depends
from auth import get_api_key
from pydantic import BaseModel

import pandas as pd 
import numpy as np 
import text2sql as t2s
import os
import json
import hashlib
from datetime import datetime
import time
from urllib.parse import unquote_plus

# Change API version each time the prompt file in the data folder is updated and text2sql API container is restarted
strapiversion = "1.0.12"

app = FastAPI(title="Text2SQL API", version=strapiversion, description="Text2SQL API for text to SQL query conversion")

answer=42

class TextExpr(BaseModel):
    text: str
    sqlquery: str = ""
    processing_time: float

class ResultItem(BaseModel):
    sqlquery: str

LOGS_FOLDER = "logs"

def f_getlogfilename(endpoint, contenttext):
    os.makedirs(LOGS_FOLDER, exist_ok=True)
    now = datetime.now()
    date_time_str = now.strftime("%Y%m%d-%H%M%S")
    md5_hash = hashlib.md5(contenttext.encode('utf-8')).hexdigest()
    filename = f"{LOGS_FOLDER}/{date_time_str}_{endpoint}_{strapiversion}_{md5_hash}.json"
    return filename

def log_usage(endpoint, content):
    contenttext = json.dumps(content, indent=4, ensure_ascii=False)
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

@app.get("/search/text2sql/{text}", response_model=TextExpr)
async def get_text(text: str, api_key: str = Depends(get_api_key)):
    start_time = time.time()
    decoded_text = unquote_plus(text)
    sqlquery = t2s.f_text2sql(decoded_text)
    end_time = time.time()
    processing_time = end_time - start_time
    
    result = {
        "text": decoded_text,
        "sqlquery": sqlquery,
        "processing_time": processing_time
    }
    log_usage("text", result)
    return result

if __name__ == "__main__":
    import uvicorn
    result = {"message": "Text2SQL API start version " + strapiversion}
    log_usage("start", result)
    uvicorn.run(app, host="0.0.0.0", port=8000)

