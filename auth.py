import os
import secrets
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("API_KEY environment variable is required. Please set it in your .env file.")
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME)

def get_api_key(api_key_header: str = Security(api_key_header)):
    """Validate API key from request header.
    
    Securely compares the provided API key with the expected key using
    constant-time comparison to prevent timing attacks.
    
    Args:
        api_key_header (str): API key from X-API-Key header (injected by FastAPI Security)
        
    Returns:
        str: The validated API key if authentication succeeds
        
    Raises:
        HTTPException: 401 Unauthorized if API key is invalid or missing
        
    Note:
        Uses secrets.compare_digest() for secure string comparison.
    """
    if secrets.compare_digest(api_key_header, API_KEY):
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
    )
