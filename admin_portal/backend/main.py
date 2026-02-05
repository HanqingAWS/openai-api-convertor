"""Admin Portal FastAPI application."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from admin_portal.backend.api import auth, api_keys, dashboard, pricing
from admin_portal.backend.middleware.cognito_auth import CognitoAuthMiddleware
from app.db.dynamodb import DynamoDBClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    try:
        app.state.dynamodb_client = DynamoDBClient()
    except Exception as e:
        print(f"Warning: Could not initialize DynamoDB: {e}")
        app.state.dynamodb_client = None
    yield


app = FastAPI(
    title="OpenAI Proxy Admin Portal",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(api_keys.router, prefix="/api/keys", tags=["API Keys"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(pricing.router, prefix="/api/pricing", tags=["Pricing"])


@app.get("/health")
async def health():
    return {"status": "healthy"}


# Serve static files (frontend build)
static_path = Path(__file__).parent.parent / "frontend" / "dist"
if static_path.exists():
    app.mount("/admin", StaticFiles(directory=str(static_path), html=True), name="admin")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("admin_portal.backend.main:app", host="0.0.0.0", port=8005, reload=True)
