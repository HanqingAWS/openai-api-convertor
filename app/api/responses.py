"""OpenAI Responses API passthrough endpoint (OpenAI models only).

Transparently forwards POST /v1/responses to Bedrock Mantle's native Responses
API. Only OpenAI models (openai.*) are allowed — Claude uses Bedrock Converse
and has no Responses API.

Auth: the client's proxy API key is verified here (same auth as chat
completions) and is NEVER forwarded upstream — the provider's (or host's)
bearer token is used to build a fresh Authorization header for Mantle.
"""
import logging
import time
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.chat import (
    get_bedrock_service,
    get_openai_service,
    get_usage_tracker,
    is_openai_model,
    resolve_provider,
    validate_provider_for_model,
)
from app.core.exceptions import InvalidRequestError
from app.db.dynamodb import UsageTracker
from app.middleware.auth import get_api_key_info
from app.middleware.rate_limit import check_rate_limit
from app.services.bedrock_service import BedrockService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Responses"])


def _record_usage(usage_tracker, api_key_info, request_id, model, payload, start_time):
    """Record token usage from a non-streaming Responses API payload (best-effort)."""
    try:
        usage = payload.get("usage") or {}
        prompt_tokens = usage.get("input_tokens", 0) or 0
        completion_tokens = usage.get("output_tokens", 0) or 0
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
        usage_tracker.record_usage(
            api_key=api_key_info.get("api_key", "anonymous"),
            request_id=request_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            success=True,
            latency_ms=int((time.time() - start_time) * 1000),
            cached_tokens=cached,
        )
    except Exception as e:  # never let usage recording break the response
        logger.warning("failed to record /v1/responses usage: %s", e)


@router.post("/v1/responses")
async def create_response(
    request: Request,
    api_key_info: dict = Depends(get_api_key_info),
    _rate_limit: None = Depends(check_rate_limit),
    bedrock_service: BedrockService = Depends(get_bedrock_service),
    usage_tracker: Optional[UsageTracker] = Depends(get_usage_tracker),
):
    """Transparent passthrough to Bedrock Mantle Responses API (OpenAI models only)."""
    request_id = f"resp-{uuid4().hex[:24]}"
    start_time = time.time()
    # For rate limiting (check_rate_limit reads request.state.api_key_info).
    request.state.api_key_info = api_key_info

    body = await request.json()
    if not isinstance(body, dict):
        raise InvalidRequestError("Request body must be a JSON object")

    model = body.get("model")
    if not model:
        raise InvalidRequestError("Missing 'model' in request body", param="model")

    # Fail-closed provider resolution (raises if a bound provider is unusable).
    provider_info = resolve_provider(api_key_info, request)

    # Only OpenAI models are valid on /v1/responses.
    resolved = bedrock_service.resolve_model_id(model)
    if not is_openai_model(resolved):
        raise InvalidRequestError(
            f"/v1/responses only supports OpenAI models (e.g. gpt-5.5). "
            f"'{model}' is not an OpenAI model — use /v1/chat/completions for Claude.",
            param="model",
        )
    validate_provider_for_model(provider_info, resolved)
    body["model"] = resolved  # forward the resolved openai.* id to Mantle

    openai_service = get_openai_service(request)

    if bool(body.get("stream")):
        return StreamingResponse(
            openai_service.responses_passthrough_stream(body, provider_info),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Request-ID": request_id,
            },
        )

    status_code, payload = await openai_service.responses_passthrough(body, provider_info)
    if usage_tracker and status_code < 400 and isinstance(payload, dict):
        _record_usage(usage_tracker, api_key_info, request_id, model, payload, start_time)
    return JSONResponse(status_code=status_code, content=payload)
