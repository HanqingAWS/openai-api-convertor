"""Authentication middleware."""
import re
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.db.dynamodb import APIKeyManager


def extract_api_key(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
) -> Optional[str]:
    """Extract API key from headers."""
    # Try Authorization: Bearer <key>
    if authorization:
        match = re.match(r"Bearer\s+(.+)", authorization, re.IGNORECASE)
        if match:
            return match.group(1)

    # Try x-api-key header
    if x_api_key:
        return x_api_key

    return None


async def get_api_key_info(
    request: Request,
    api_key: Optional[str] = Depends(extract_api_key),
) -> dict:
    """Validate API key and return key info."""
    # Skip auth if disabled
    if not settings.require_api_key:
        return {"api_key": "anonymous", "user_id": "anonymous"}

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "message": "Missing API key. Include it in Authorization header as 'Bearer <key>' or in x-api-key header.",
                    "type": "authentication_error",
                    "code": "missing_api_key",
                }
            },
        )

    # Check master key
    if settings.master_api_key and api_key == settings.master_api_key:
        return {"api_key": api_key, "user_id": "master", "rate_limit": 10000}

    # Validate against DynamoDB
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    if dynamodb_client:
        api_key_manager = APIKeyManager(dynamodb_client)
        key_info = api_key_manager.validate_api_key(api_key)
        if key_info:
            return key_info

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "message": "Invalid API key provided.",
                "type": "authentication_error",
                "code": "invalid_api_key",
            }
        },
    )
