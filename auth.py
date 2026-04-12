import os
import secrets
from typing import List
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

_raw_keys = os.getenv("API_KEYS") or os.getenv("API_KEY", "")
API_KEYS: List[str] = [k.strip() for k in _raw_keys.split(",") if k.strip()]
if not API_KEYS:
    raise ValueError(
        "No API keys configured. Set API_KEYS (comma-separated) or API_KEY in your .env file."
    )
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME)

def get_api_key(api_key_header: str = Security(api_key_header)):
    """Validate API key from request header.

    Accepts any key present in the API_KEYS list (comma-separated env var).
    Falls back to the legacy API_KEY single-value env var for backward compatibility.
    Uses constant-time comparison for every candidate to prevent timing attacks.

    Args:
        api_key_header (str): API key from X-API-Key header (injected by FastAPI Security)

    Returns:
        str: The validated API key if authentication succeeds

    Raises:
        HTTPException: 401 Unauthorized if the key does not match any configured key
    """
    if any(secrets.compare_digest(api_key_header, key) for key in API_KEYS):
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
    )
