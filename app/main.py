"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, models, health
from app.core.config import settings
from app.core.exceptions import OpenAIProxyError
from app.db.dynamodb import DynamoDBClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    try:
        app.state.dynamodb_client = DynamoDBClient()
    except Exception as e:
        print(f"Warning: Could not initialize DynamoDB client: {e}")
        app.state.dynamodb_client = None

    yield

    # Shutdown
    pass


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="OpenAI-compatible API proxy for AWS Bedrock Claude models",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(OpenAIProxyError)
async def openai_proxy_error_handler(request: Request, exc: OpenAIProxyError):
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


# Include routers
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(models.router)


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
