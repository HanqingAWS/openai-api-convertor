"""Bedrock service for invoking Claude models."""
import asyncio
import json
from typing import Any, AsyncGenerator, Dict, Optional
from uuid import uuid4

import boto3
from botocore.config import Config

from app.core.config import settings
from app.core.exceptions import BedrockAPIError
from app.converters.openai_to_bedrock import OpenAIToBedrockConverter
from app.converters.bedrock_to_openai import BedrockToOpenAIConverter
from app.schemas.openai import ChatCompletionRequest, ChatCompletionResponse


class BedrockService:
    """Service for interacting with AWS Bedrock."""

    def __init__(self, dynamodb_client=None):
        config = Config(
            read_timeout=settings.bedrock_timeout,
            connect_timeout=30,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )

        client_kwargs = {
            "service_name": "bedrock-runtime",
            "region_name": settings.aws_region,
            "config": config,
        }

        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        if settings.bedrock_endpoint_url:
            client_kwargs["endpoint_url"] = settings.bedrock_endpoint_url

        self.client = boto3.client(**client_kwargs)
        self.openai_to_bedrock = OpenAIToBedrockConverter(dynamodb_client)
        self.bedrock_to_openai = BedrockToOpenAIConverter()

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        request_id: Optional[str] = None,
        cache_ttl: Optional[str] = None,
    ) -> tuple[ChatCompletionResponse, Dict[str, Any]]:
        """Handle non-streaming chat completion.

        Returns:
            Tuple of (response, cache_usage) where cache_usage contains
            cached_tokens, cache_write_tokens, cache_write_ttl.
        """
        request_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"

        try:
            bedrock_request = self.openai_to_bedrock.convert_request(request, cache_ttl=cache_ttl)
            model_id = bedrock_request.pop("modelId")

            response = self.client.converse(modelId=model_id, **bedrock_request)

            cache_usage = self.bedrock_to_openai.extract_cache_usage(response)

            return (
                self.bedrock_to_openai.convert_response(response, request.model, request_id, cache_ttl=cache_ttl),
                cache_usage,
            )

        except self.client.exceptions.ValidationException as e:
            raise BedrockAPIError(str(e), code="validation_error", http_status=400)
        except self.client.exceptions.ThrottlingException as e:
            raise BedrockAPIError(str(e), code="rate_limit", http_status=429)
        except self.client.exceptions.ModelNotReadyException as e:
            raise BedrockAPIError(str(e), code="model_not_ready", http_status=503)
        except Exception as e:
            raise BedrockAPIError(f"Bedrock error: {str(e)}", http_status=500)

    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        request_id: Optional[str] = None,
        cache_ttl: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Handle streaming chat completion.

        Yields SSE strings. If stream_options.include_usage is True,
        a final chunk with usage is emitted before [DONE].
        The last yielded item may be a special "__usage__:..." line for internal tracking.

        Uses a thread pool for the synchronous boto3 stream iteration to avoid
        blocking the async event loop, enabling true incremental streaming.
        """
        request_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"
        include_usage = (
            request.stream_options
            and request.stream_options.include_usage
        )

        _SENTINEL = object()
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _stream_in_thread():
            try:
                bedrock_request = self.openai_to_bedrock.convert_request(request, cache_ttl=cache_ttl)
                model_id = bedrock_request.pop("modelId")
                response = self.client.converse_stream(modelId=model_id, **bedrock_request)

                current_index = 0
                usage_data = None

                for event in response.get("stream", []):
                    extracted = self.bedrock_to_openai.extract_stream_usage(event)
                    if extracted:
                        usage_data = extracted

                    sse_events = self.bedrock_to_openai.convert_stream_event(
                        event, request.model, request_id, current_index
                    )
                    for sse in sse_events:
                        loop.call_soon_threadsafe(queue.put_nowait, sse)

                    if "contentBlockStart" in event:
                        current_index += 1

                # Emit usage chunk if requested
                if include_usage and usage_data:
                    chunk = self.bedrock_to_openai.build_usage_chunk(
                        request_id, request.model, usage_data, cache_ttl=cache_ttl
                    )
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)

                # Always emit [DONE]
                loop.call_soon_threadsafe(queue.put_nowait, "data: [DONE]\n\n")

                # Emit internal usage marker
                if usage_data:
                    loop.call_soon_threadsafe(
                        queue.put_nowait, f"__usage__:{json.dumps(usage_data)}"
                    )

            except Exception as e:
                error_type = "server_error"
                if "ValidationException" in type(e).__name__:
                    error_type = "validation_error"
                elif "ThrottlingException" in type(e).__name__:
                    error_type = "rate_limit_error"
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    f"data: {json.dumps({'error': {'message': str(e), 'type': error_type}})}\n\n"
                )
                loop.call_soon_threadsafe(queue.put_nowait, "data: [DONE]\n\n")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        loop.run_in_executor(None, _stream_in_thread)

        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            yield item

    def list_models(self) -> list[Dict[str, Any]]:
        """List available models."""
        models = []
        for model_id in settings.default_model_mapping.keys():
            models.append({
                "id": model_id,
                "object": "model",
                "created": 1700000000,
                "owned_by": "anthropic",
                "capabilities": {
                    "vision": settings.enable_vision,
                    "tool_use": settings.enable_tool_use,
                    "function_calling": settings.enable_tool_use,
                    "extended_thinking": settings.enable_extended_thinking,
                    "streaming": True,
                },
            })
        return models
