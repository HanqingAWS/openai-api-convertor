"""Authentication API endpoints."""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Login endpoint - integrates with Cognito."""
    # TODO: Implement Cognito authentication
    # For now, return a mock token for development
    if request.username == "admin" and request.password == "admin":
        return LoginResponse(
            access_token="mock-token-for-development",
            expires_in=3600,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )


@router.post("/logout")
async def logout():
    """Logout endpoint."""
    return {"message": "Logged out successfully"}


@router.get("/me")
async def get_current_user():
    """Get current user info."""
    # TODO: Implement with Cognito token validation
    return {
        "username": "admin",
        "email": "admin@example.com",
    }
