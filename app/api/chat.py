"""Chat completions API endpoint."""
import time
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings
from app.db.dynamodb import UsageTracker
from app.middleware.auth import get_api_key_info
from app.middleware.rate_limit import check_rate_limit
from app.schemas.openai import ChatCompletionRequest, ChatCompletionResponse
from app.services.bedrock_service import BedrockService

router = APIRouter(tags=["Chat"])


def get_bedrock_service(request: Request) -> BedrockService:
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    return BedrockService(dynamodb_client)


def get_usage_tracker(request: Request) -> Optional[UsageTracker]:
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    if dynamodb_client:
        return UsageTracker(dynamodb_client)
    return None


@router.post("/v1/chat/completions")
async def create_chat_completion(
    request_data: ChatCompletionRequest,
    request: Request,
    api_key_info: dict = Depends(get_api_key_info),
    _rate_limit: None = Depends(check_rate_limit),
    bedrock_service: BedrockService = Depends(get_bedrock_service),
    usage_tracker: Optional[UsageTracker] = Depends(get_usage_tracker),
):
    """Create a chat completion (OpenAI-compatible)."""
    request_id = f"chatcmpl-{uuid4().hex[:24]}"
    start_time = time.time()

    # Store api_key_info in request state for rate limiting
    request.state.api_key_info = api_key_info

    try:
        if request_data.stream:
            # Streaming response
            return StreamingResponse(
                _stream_response(
                    request_data,
                    request_id,
                    api_key_info,
                    bedrock_service,
                    usage_tracker,
                    start_time,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Request-ID": request_id,
                },
            )
        else:
            # Non-streaming response
            response = await bedrock_service.chat_completion(request_data, request_id)

            # Record usage
            if usage_tracker:
                latency_ms = int((time.time() - start_time) * 1000)
                usage_tracker.record_usage(
                    api_key=api_key_info.get("api_key", "anonymous"),
                    request_id=request_id,
                    model=request_data.model,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    success=True,
                    latency_ms=latency_ms,
                )

            return response

    except HTTPException:
        raise
    except Exception as e:
        # Record failed usage
        if usage_tracker:
            usage_tracker.record_usage(
                api_key=api_key_info.get("api_key", "anonymous"),
                request_id=request_id,
                model=request_data.model,
                prompt_tokens=0,
                completion_tokens=0,
                success=False,
                error_message=str(e),
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": f"Internal server error: {str(e)}",
                    "type": "server_error",
                    "code": "internal_error",
                }
            },
        )


async def _stream_response(
    request_data: ChatCompletionRequest,
    request_id: str,
    api_key_info: dict,
    bedrock_service: BedrockService,
    usage_tracker: Optional[UsageTracker],
    start_time: float,
):
    """Stream chat completion response."""
    prompt_tokens = 0
    completion_tokens = 0
    success = True
    error_message = None

    try:
        async for chunk in bedrock_service.chat_completion_stream(request_data, request_id):
            yield chunk

    except Exception as e:
        success = False
        error_message = str(e)
        yield f"data: {{'error': {{'message': '{str(e)}', 'type': 'server_error'}}}}\n\n"

    finally:
        # Record usage
        if usage_tracker:
            latency_ms = int((time.time() - start_time) * 1000)
            usage_tracker.record_usage(
                api_key=api_key_info.get("api_key", "anonymous"),
                request_id=request_id,
                model=request_data.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=success,
                error_message=error_message,
                latency_ms=latency_ms,
            )
