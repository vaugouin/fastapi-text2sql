from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

API_KEY = "1131b472feea1239884f172070ab84e83cab061f4f1f97b737299e88777d9b7c"
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME)

def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
    )
