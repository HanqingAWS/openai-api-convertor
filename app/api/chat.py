"""Chat completions API endpoint."""
import json
import logging
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings
from app.core.exceptions import InvalidRequestError, OpenAIProxyError, ProviderConfigError
from app.db.dynamodb import UsageTracker, ProviderManager
from app.middleware.auth import get_api_key_info
from app.middleware.rate_limit import check_rate_limit
from app.schemas.openai import ChatCompletionRequest, ChatCompletionResponse
from app.services.bedrock_service import BedrockService
from app.services.openai_service import OpenAIService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


def get_bedrock_service(request: Request) -> BedrockService:
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    return BedrockService(dynamodb_client)


def get_openai_service(request: Request) -> OpenAIService:
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    return OpenAIService(dynamodb_client)


def is_openai_model(resolved_model_id: str) -> bool:
    return resolved_model_id.startswith("openai.")


def get_usage_tracker(request: Request) -> Optional[UsageTracker]:
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    if dynamodb_client:
        return UsageTracker(dynamodb_client)
    return None


def resolve_provider(api_key_info: dict, request: Request) -> Optional[Dict[str, Any]]:
    """Resolve provider credentials from api_key_info.provider_id.

    Fail-closed: an empty provider_id means the key is unbound (host IAM role is
    used by design). But once a provider_id IS set, any failure to resolve a
    usable provider raises ProviderConfigError instead of silently falling back
    to the host account — multi-tenant isolation is a hard boundary.
    """
    provider_id = api_key_info.get("provider_id", "")
    if not provider_id:
        return None  # unbound key — host IAM role by design

    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    if not dynamodb_client:
        logger.warning("provider %s bound but provider store unavailable", provider_id)
        raise ProviderConfigError(
            f"API key is bound to provider '{provider_id}' but the provider store is unavailable; "
            "refusing to fall back to host credentials."
        )

    manager = ProviderManager(dynamodb_client)
    provider = manager.get_provider(provider_id)
    if not provider:
        logger.warning("bound provider %s not found", provider_id)
        raise ProviderConfigError(
            f"API key is bound to provider '{provider_id}' but it no longer exists; "
            "refusing to fall back to host credentials."
        )
    if not provider.get("is_active", False):
        logger.warning("bound provider %s is inactive", provider_id)
        raise ProviderConfigError(
            f"API key is bound to provider '{provider.get('name', provider_id)}' but it is inactive; "
            "refusing to fall back to host credentials."
        )
    return provider


def validate_provider_for_model(provider_info: Optional[Dict[str, Any]], resolved_model_id: str) -> None:
    """Fail-closed check that a bound provider can actually serve this model.

    Covers BOTH paths: Claude (Bedrock Converse, needs ak_sk) and OpenAI
    (Bedrock Mantle, accepts bearer_token or ak_sk-derived token). Raises
    rather than letting the request silently run on host credentials.
    """
    if not provider_info:
        return  # unbound — host role by design

    auth_type = provider_info.get("auth_type", "")
    name = provider_info.get("name", provider_info.get("provider_id", ""))
    ak = provider_info.get("access_key_id")
    sk = provider_info.get("secret_access_key")
    bearer = provider_info.get("bearer_token")

    if is_openai_model(resolved_model_id):
        # OpenAI/Mantle path: bearer_token used directly, or ak_sk → short-lived token
        if auth_type == "bearer_token":
            if not bearer:
                logger.warning("provider %s bearer_token empty", name)
                raise ProviderConfigError(f"Provider '{name}' has no bearer token configured.")
        elif auth_type == "ak_sk":
            if not ak or not sk:
                logger.warning("provider %s ak_sk incomplete", name)
                raise ProviderConfigError(f"Provider '{name}' has incomplete AK/SK credentials.")
        else:
            logger.warning("provider %s unknown auth_type %r", name, auth_type)
            raise ProviderConfigError(f"Provider '{name}' has unknown auth_type '{auth_type}'.")
        return

    # Claude / Bedrock Converse path: only ak_sk can authenticate boto3
    if auth_type != "ak_sk":
        logger.warning("provider %s auth_type %r cannot serve Claude", name, auth_type)
        raise InvalidRequestError(
            f"Provider '{name}' uses '{auth_type}', which cannot authenticate AWS Bedrock "
            "Converse (Claude models). Bind an AK/SK provider, or use an OpenAI model."
        )
    if not ak or not sk:
        logger.warning("provider %s ak_sk incomplete (claude)", name)
        raise ProviderConfigError(f"Provider '{name}' has incomplete AK/SK credentials.")


def resolve_cache_ttl(request_data: ChatCompletionRequest, api_key_info: dict) -> Optional[str]:
    """Resolve cache TTL based on priority: Per-Request > Per-API-Key > Global."""
    if not settings.enable_prompt_caching:
        return None

    # Per-Request: explicit disable
    if request_data.caching is False:
        return None

    # Per-Request: explicit cache_ttl
    if request_data.cache_ttl:
        return request_data.cache_ttl

    # Per-API-Key
    key_ttl = api_key_info.get("cache_ttl", "")
    if key_ttl == "disabled":
        return None
    if key_ttl in ("5m", "1h"):
        return key_ttl

    # Global default
    return settings.default_cache_ttl


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

    # Resolve provider credentials (if API key is bound to a provider).
    # Fail-closed: raises if a bound provider is missing/inactive.
    provider_info = resolve_provider(api_key_info, request)

    # Resolve model ID to detect OpenAI vs Claude
    resolved_model_id = bedrock_service.resolve_model_id(request_data.model)

    # Fail-closed: a bound provider must be able to serve this model (both paths)
    validate_provider_for_model(provider_info, resolved_model_id)

    # Route to OpenAI service if model is an OpenAI model
    if is_openai_model(resolved_model_id):
        openai_service = get_openai_service(request)
        return await _handle_openai_request(
            request_data, request_id, resolved_model_id,
            openai_service, usage_tracker, api_key_info, start_time,
            provider_info,
        )

    # Resolve cache TTL (Claude models only)
    cache_ttl = resolve_cache_ttl(request_data, api_key_info)

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
                    cache_ttl,
                    provider_info,
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
            response, cache_usage = await bedrock_service.chat_completion(
                request_data, request_id, cache_ttl=cache_ttl, provider_info=provider_info
            )

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
                    cached_tokens=cache_usage.get("cached_tokens", 0),
                    cache_write_tokens=cache_usage.get("cache_write_tokens", 0),
                    cache_write_ttl=cache_usage.get("cache_write_ttl") or cache_ttl,
                )

            return JSONResponse(content=response.model_dump(exclude_none=True))

    except HTTPException:
        raise
    except OpenAIProxyError:
        # Fail-closed provider/validation errors carry their own status + message;
        # let the global OpenAIProxyError handler render them, don't mask as 500.
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
    cache_ttl: Optional[str],
    provider_info: Optional[Dict[str, Any]] = None,
):
    """Stream chat completion response."""
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    cache_write_tokens = 0
    cache_write_ttl = None
    success = True
    error_message = None

    try:
        async for chunk in bedrock_service.chat_completion_stream(
            request_data, request_id, cache_ttl=cache_ttl, provider_info=provider_info
        ):
            # Internal usage marker — extract but don't send to client
            if chunk.startswith("__usage__:"):
                try:
                    usage_data = json.loads(chunk[len("__usage__:"):])
                    prompt_tokens = usage_data.get("prompt_tokens", 0)
                    completion_tokens = usage_data.get("completion_tokens", 0)
                    cached_tokens = usage_data.get("cached_tokens", 0)
                    cache_write_tokens = usage_data.get("cache_write_tokens", 0)
                    cache_write_ttl = usage_data.get("cache_write_ttl")
                except Exception:
                    pass
                continue
            yield chunk

    except Exception as e:
        success = False
        error_message = str(e)
        yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"

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
                cached_tokens=cached_tokens,
                cache_write_tokens=cache_write_tokens,
                cache_write_ttl=cache_write_ttl or cache_ttl,
            )


async def _handle_openai_request(
    request_data: ChatCompletionRequest,
    request_id: str,
    resolved_model_id: str,
    openai_service: OpenAIService,
    usage_tracker: Optional[UsageTracker],
    api_key_info: dict,
    start_time: float,
    provider_info: Optional[Dict[str, Any]] = None,
):
    """Handle requests for OpenAI models routed to Bedrock Mantle."""
    try:
        if request_data.stream:
            return StreamingResponse(
                _stream_openai_response(
                    request_data, request_id, resolved_model_id,
                    openai_service, usage_tracker, api_key_info, start_time,
                    provider_info,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Request-ID": request_id,
                },
            )
        else:
            response, cache_usage = await openai_service.chat_completion(
                request_data, resolved_model_id, request_id,
                api_key=api_key_info.get("api_key"),
                provider_info=provider_info,
            )

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
                    cached_tokens=cache_usage.get("cached_tokens", 0),
                )

            return JSONResponse(content=response.model_dump(exclude_none=True))

    except OpenAIProxyError:
        # Fail-closed provider errors keep their own status + message.
        raise
    except Exception as e:
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


async def _stream_openai_response(
    request_data: ChatCompletionRequest,
    request_id: str,
    resolved_model_id: str,
    openai_service: OpenAIService,
    usage_tracker: Optional[UsageTracker],
    api_key_info: dict,
    start_time: float,
    provider_info: Optional[Dict[str, Any]] = None,
):
    """Stream OpenAI model response."""
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    success = True
    error_message = None

    try:
        async for chunk in openai_service.chat_completion_stream(
            request_data, resolved_model_id, request_id,
            api_key=api_key_info.get("api_key"),
            provider_info=provider_info,
        ):
            if chunk.startswith("__usage__:"):
                try:
                    usage_data = json.loads(chunk[len("__usage__:"):])
                    prompt_tokens = usage_data.get("prompt_tokens", 0)
                    completion_tokens = usage_data.get("completion_tokens", 0)
                    cached_tokens = usage_data.get("cached_tokens", 0)
                except Exception:
                    pass
                continue
            yield chunk

    except Exception as e:
        success = False
        error_message = str(e)
        yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"

    finally:
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
                cached_tokens=cached_tokens,
            )
