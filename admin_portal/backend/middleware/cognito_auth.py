"""Cognito authentication middleware."""
import os
from typing import Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class CognitoAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for Cognito JWT token validation."""

    def __init__(self, app, exclude_paths: Optional[list] = None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or ["/health", "/api/auth/login"]
        self.user_pool_id = os.environ.get("COGNITO_USER_POOL_ID")
        self.client_id = os.environ.get("COGNITO_CLIENT_ID")
        self.region = os.environ.get("COGNITO_REGION", "us-west-2")

    async def dispatch(self, request: Request, call_next):
        # Skip auth for excluded paths
        if any(request.url.path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        # Skip auth if Cognito not configured
        if not self.user_pool_id:
            return await call_next(request)

        # Get token from header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        token = auth_header.split(" ")[1]

        # TODO: Validate JWT token with Cognito
        # For now, just pass through
        # In production, use python-jose or similar to validate

        return await call_next(request)
