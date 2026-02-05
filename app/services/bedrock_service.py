"""Bedrock service for invoking Claude models."""
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
        self, request: ChatCompletionRequest, request_id: Optional[str] = None
    ) -> ChatCompletionResponse:
        """Handle non-streaming chat completion."""
        request_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"

        try:
            bedrock_request = self.openai_to_bedrock.convert_request(request)
            model_id = bedrock_request.pop("modelId")

            response = self.client.converse(modelId=model_id, **bedrock_request)

            return self.bedrock_to_openai.convert_response(
                response, request.model, request_id
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
        self, request: ChatCompletionRequest, request_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Handle streaming chat completion."""
        request_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"

        try:
            bedrock_request = self.openai_to_bedrock.convert_request(request)
            model_id = bedrock_request.pop("modelId")

            response = self.client.converse_stream(modelId=model_id, **bedrock_request)

            current_index = 0
            for event in response.get("stream", []):
                sse_events = self.bedrock_to_openai.convert_stream_event(
                    event, request.model, request_id, current_index
                )
                for sse in sse_events:
                    yield sse

                # Track content block index
                if "contentBlockStart" in event:
                    current_index += 1

        except self.client.exceptions.ValidationException as e:
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'validation_error'}})}\n\n"
        except self.client.exceptions.ThrottlingException as e:
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'rate_limit_error'}})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"

    def list_models(self) -> list[Dict[str, Any]]:
        """List available models."""
        models = []
        for model_id in settings.default_model_mapping.keys():
            models.append({
                "id": model_id,
                "object": "model",
                "created": 1700000000,
                "owned_by": "anthropic",
            })
        return models
