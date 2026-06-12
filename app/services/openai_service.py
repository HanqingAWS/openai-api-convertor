"""OpenAI model service via Bedrock Mantle Responses API."""
import asyncio
import hashlib
import json
import re
import threading
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from uuid import uuid4

from openai import OpenAI

from app.core.config import settings
from app.schemas.openai import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
    Choice,
    ChoiceMessage,
    StreamChoice,
    DeltaMessage,
    ToolCall,
    FunctionCall,
    PromptTokensDetails,
    Usage,
)
from app.services.openai_token import OpenAITokenManager, TOKEN_CACHE_SECONDS


class OpenAIService:
    """Routes OpenAI model requests to Bedrock Mantle via Responses API."""

    def __init__(self, dynamodb_client=None):
        self.token_manager = OpenAITokenManager(dynamodb_client)
        self._client: Optional[OpenAI] = None
        self._provider_token_cache: Dict[str, Tuple[str, float]] = {}
        self._provider_token_lock = threading.Lock()

    def _get_provider_ak_sk_token(self, provider_info: Dict[str, Any]) -> str:
        """Generate a short-lived bearer token from provider's AK/SK credentials."""
        provider_id = provider_info.get("provider_id", "")
        now = time.time()

        cached = self._provider_token_cache.get(provider_id)
        if cached and now < cached[1]:
            return cached[0]

        with self._provider_token_lock:
            cached = self._provider_token_cache.get(provider_id)
            if cached and now < cached[1]:
                return cached[0]

            import boto3
            from aws_bedrock_token_generator import BedrockTokenGenerator

            session = boto3.Session(
                aws_access_key_id=provider_info["access_key_id"],
                aws_secret_access_key=provider_info["secret_access_key"],
                region_name="us-east-2",
            )
            generator = BedrockTokenGenerator(region="us-east-2", session=session)
            token = generator.generate_token()
            self._provider_token_cache[provider_id] = (token, now + TOKEN_CACHE_SECONDS)
            return token

    def _invalidate_provider_token(self, provider_info: Dict[str, Any]) -> None:
        provider_id = provider_info.get("provider_id", "")
        self._provider_token_cache.pop(provider_id, None)

    def _get_client(self, provider_info: Optional[Dict[str, Any]] = None) -> OpenAI:
        if provider_info:
            auth_type = provider_info.get("auth_type")
            if auth_type == "bearer_token" and provider_info.get("bearer_token"):
                return OpenAI(
                    base_url=self.token_manager.get_base_url(),
                    api_key=provider_info["bearer_token"],
                )
            if auth_type == "ak_sk" and provider_info.get("access_key_id"):
                token = self._get_provider_ak_sk_token(provider_info)
                return OpenAI(
                    base_url=self.token_manager.get_base_url(),
                    api_key=token,
                )
        return OpenAI(
            base_url=self.token_manager.get_base_url(),
            api_key=self.token_manager.get_api_key(),
        )

    @staticmethod
    def _part_field(part: Any, name: str, default: Any = None) -> Any:
        """Read a field from a content part that may be a pydantic model or a dict."""
        if isinstance(part, dict):
            return part.get(name, default)
        return getattr(part, name, default)

    def _text_from_content(self, content: Any) -> str:
        """Flatten str-or-list content to plain text (used for system/assistant)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                self._part_field(p, "text", "") or ""
                for p in content
                if self._part_field(p, "type") == "text"
            )
        return ""

    def _convert_user_content(self, content: Any) -> Any:
        """Convert Chat Completions user content to Responses API input content.

        A plain string stays a string; a multimodal array is converted to
        input_text / input_image parts so text and images survive instead of
        being silently dropped to "".
        """
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: List[Dict[str, Any]] = []
        for part in content:
            ptype = self._part_field(part, "type")
            if ptype == "text":
                parts.append({"type": "input_text", "text": self._part_field(part, "text", "") or ""})
            elif ptype == "image_url" and settings.enable_vision:
                img = self._part_field(part, "image_url")
                url = self._part_field(img, "url", "") or ""
                if url:
                    item: Dict[str, Any] = {"type": "input_image", "image_url": url}
                    detail = self._part_field(img, "detail")
                    if detail:
                        item["detail"] = detail
                    parts.append(item)
        return parts

    def _convert_to_responses_input(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Convert Chat Completions messages to Responses API params."""
        instructions = None
        input_items: List[Dict[str, Any]] = []

        for msg in request.messages:
            if msg.role == "system":
                text = self._text_from_content(msg.content)
                if instructions:
                    instructions += "\n" + text
                else:
                    instructions = text

            elif msg.role == "user":
                input_items.append({"role": "user", "content": self._convert_user_content(msg.content)})

            elif msg.role == "assistant":
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        input_items.append({
                            "type": "function_call",
                            "call_id": tc.id,
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        })
                    if msg.content:
                        input_items.insert(len(input_items) - len(msg.tool_calls), {
                            "role": "assistant", "content": self._text_from_content(msg.content)
                        })
                else:
                    input_items.append({
                        "role": "assistant",
                        "content": self._text_from_content(msg.content),
                    })

            elif msg.role == "tool":
                input_items.append({
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id or "",
                    "output": msg.content or "",
                })

        params: Dict[str, Any] = {"input": input_items}
        if instructions:
            params["instructions"] = instructions

        return params

    def _caching_enabled(self, request: ChatCompletionRequest) -> bool:
        """Auto prompt caching is on unless globally disabled or the request opts out."""
        if not settings.enable_prompt_caching:
            return False
        if request.caching is False:
            return False
        return True

    def _prompt_cache_key(self, api_key: Optional[str], instructions: Optional[str]) -> str:
        """Routing hint stable per (client, system prompt).

        Bedrock Mantle uses prompt_cache_key to route requests sharing a prefix to the
        same cache, so repeated turns of the same agent setup reuse the cached
        instructions. Opaque to the client.
        """
        h = hashlib.sha256()
        h.update((api_key or "anonymous").encode("utf-8"))
        h.update(b"\x00")
        h.update((instructions or "").encode("utf-8"))
        return h.hexdigest()[:32]

    def _prompt_cache_retention(self, model_id: str) -> str:
        """GPT-5.5+ supports 24h disk retention; earlier models only in-memory."""
        m = re.search(r"gpt-(\d+)\.(\d+)", model_id)
        if m and (int(m.group(1)), int(m.group(2))) >= (5, 5):
            return "24h"
        return "in_memory"

    @staticmethod
    def _extract_cached_tokens(usage_data: Any) -> int:
        """Pull cached prompt tokens from Responses API usage (subset of input_tokens)."""
        details = getattr(usage_data, "input_tokens_details", None)
        if details is not None:
            return getattr(details, "cached_tokens", 0) or 0
        return 0

    def _build_responses_kwargs(
        self,
        request: ChatCompletionRequest,
        model_id: str,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build full kwargs for client.responses.create()."""
        kwargs = self._convert_to_responses_input(request)
        kwargs["model"] = model_id

        max_tok = request.max_completion_tokens or request.max_tokens
        if max_tok:
            kwargs["max_output_tokens"] = max_tok

        if request.temperature is not None and request.temperature != 1.0:
            kwargs["temperature"] = request.temperature
        elif request.top_p is not None and request.top_p != 1.0:
            kwargs["top_p"] = request.top_p

        if request.reasoning_effort:
            kwargs["reasoning"] = {"effort": request.reasoning_effort}

        if request.tools:
            tools = []
            for tool in request.tools:
                if tool.type == "function":
                    params = {}
                    if tool.function.parameters:
                        params = {
                            "type": tool.function.parameters.type,
                            "properties": tool.function.parameters.properties or {},
                            "required": tool.function.parameters.required or [],
                        }
                    tools.append({
                        "type": "function",
                        "name": tool.function.name,
                        "description": tool.function.description or "",
                        "parameters": params,
                    })
            if tools:
                kwargs["tools"] = tools

        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice

        # Auto prompt caching: transparent cache key + model-appropriate retention.
        if self._caching_enabled(request):
            kwargs["prompt_cache_key"] = self._prompt_cache_key(api_key, kwargs.get("instructions"))
            kwargs["prompt_cache_retention"] = self._prompt_cache_retention(model_id)

        return kwargs

    def _call_with_retry(self, kwargs: Dict[str, Any], provider_info: Optional[Dict[str, Any]] = None):
        """Call Responses API with one retry on 401 (token expired)."""
        from openai import AuthenticationError
        client = self._get_client(provider_info)
        try:
            return client.responses.create(**kwargs)
        except AuthenticationError:
            if provider_info:
                if provider_info.get("auth_type") == "bearer_token":
                    raise
                if provider_info.get("auth_type") == "ak_sk":
                    self._invalidate_provider_token(provider_info)
                    client = self._get_client(provider_info)
                    return client.responses.create(**kwargs)
            self.token_manager.invalidate_token()
            client = self._get_client(provider_info)
            return client.responses.create(**kwargs)

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        model_id: str,
        request_id: Optional[str] = None,
        api_key: Optional[str] = None,
        provider_info: Optional[Dict[str, Any]] = None,
    ) -> tuple[ChatCompletionResponse, Dict[str, Any]]:
        """Non-streaming completion via Responses API."""
        request_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"
        kwargs = self._build_responses_kwargs(request, model_id, api_key=api_key)

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: self._call_with_retry(kwargs, provider_info)
        )

        # Convert response
        text_content = ""
        tool_calls = []
        reasoning_content = None

        for item in response.output:
            if item.type == "message":
                for content_block in item.content:
                    if content_block.type == "output_text":
                        text_content += content_block.text
            elif item.type == "function_call":
                tool_calls.append(
                    ToolCall(
                        index=len(tool_calls),
                        id=item.call_id,
                        type="function",
                        function=FunctionCall(
                            name=item.name,
                            arguments=item.arguments,
                        ),
                    )
                )
            elif item.type == "reasoning":
                if hasattr(item, "summary") and item.summary:
                    reasoning_content = "\n".join(
                        s.text for s in item.summary if hasattr(s, "text")
                    )

        finish_reason = "stop"
        if tool_calls:
            finish_reason = "tool_calls"
        elif response.status == "incomplete":
            finish_reason = "length"

        choice_message = ChoiceMessage(
            role="assistant",
            content=text_content if text_content else None,
            tool_calls=tool_calls if tool_calls else None,
            reasoning_content=reasoning_content,
            thinking=reasoning_content,
        )

        usage_data = response.usage
        prompt_tokens = getattr(usage_data, "input_tokens", 0)
        completion_tokens = getattr(usage_data, "output_tokens", 0)
        cached_tokens = self._extract_cached_tokens(usage_data)

        # input_tokens already includes cached_tokens (OpenAI semantics), so
        # prompt_tokens stays as-is and we just expose the cached subset.
        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            prompt_tokens_details=(
                PromptTokensDetails(cached_tokens=cached_tokens) if cached_tokens else None
            ),
            cache_read_input_tokens=cached_tokens,
        )

        return (
            ChatCompletionResponse(
                id=request_id,
                created=int(time.time()),
                model=request.model,
                choices=[Choice(index=0, message=choice_message, finish_reason=finish_reason)],
                usage=usage,
            ),
            {"cached_tokens": cached_tokens, "cache_write_tokens": 0, "cache_write_ttl": None},
        )

    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        model_id: str,
        request_id: Optional[str] = None,
        api_key: Optional[str] = None,
        provider_info: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming completion via Responses API."""
        request_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"
        kwargs = self._build_responses_kwargs(request, model_id, api_key=api_key)
        kwargs["stream"] = True

        _SENTINEL = object()
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _stream_in_thread():
            try:
                from openai import AuthenticationError
                try:
                    client = self._get_client(provider_info)
                    stream = client.responses.create(**kwargs)
                except AuthenticationError:
                    if provider_info:
                        if provider_info.get("auth_type") == "bearer_token":
                            raise
                        if provider_info.get("auth_type") == "ak_sk":
                            self._invalidate_provider_token(provider_info)
                            client = self._get_client(provider_info)
                            stream = client.responses.create(**kwargs)
                    else:
                        self.token_manager.invalidate_token()
                        client = self._get_client(provider_info)
                        stream = client.responses.create(**kwargs)

                # Emit role chunk
                role_chunk = ChatCompletionChunk(
                    id=request_id,
                    model=request.model,
                    choices=[StreamChoice(index=0, delta=DeltaMessage(role="assistant"))],
                )
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    f"data: {role_chunk.model_dump_json(exclude_none=True)}\n\n"
                )

                tool_call_index = 0
                usage_data = None

                for event in stream:
                    event_type = event.type

                    if event_type == "response.output_text.delta":
                        chunk = ChatCompletionChunk(
                            id=request_id,
                            model=request.model,
                            choices=[StreamChoice(
                                index=0,
                                delta=DeltaMessage(content=event.delta),
                            )],
                        )
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                        )

                    elif event_type == "response.reasoning_summary_text.delta":
                        chunk = ChatCompletionChunk(
                            id=request_id,
                            model=request.model,
                            choices=[StreamChoice(
                                index=0,
                                delta=DeltaMessage(reasoning_content=event.delta),
                            )],
                        )
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                        )

                    elif event_type == "response.function_call_arguments.delta":
                        tc = ToolCall(
                            index=tool_call_index,
                            id=getattr(event, "call_id", f"call_{tool_call_index}"),
                            type="function",
                            function=FunctionCall(
                                name=getattr(event, "name", ""),
                                arguments=event.delta,
                            ),
                        )
                        chunk = ChatCompletionChunk(
                            id=request_id,
                            model=request.model,
                            choices=[StreamChoice(
                                index=0,
                                delta=DeltaMessage(tool_calls=[tc]),
                            )],
                        )
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                        )

                    elif event_type == "response.output_item.added":
                        if hasattr(event, "item") and getattr(event.item, "type", "") == "function_call":
                            tc = ToolCall(
                                index=tool_call_index,
                                id=getattr(event.item, "call_id", f"call_{tool_call_index}"),
                                type="function",
                                function=FunctionCall(
                                    name=getattr(event.item, "name", ""),
                                    arguments="",
                                ),
                            )
                            chunk = ChatCompletionChunk(
                                id=request_id,
                                model=request.model,
                                choices=[StreamChoice(
                                    index=0,
                                    delta=DeltaMessage(tool_calls=[tc]),
                                )],
                            )
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                            )
                            tool_call_index += 1

                    elif event_type == "response.completed":
                        if hasattr(event, "response") and hasattr(event.response, "usage"):
                            usage_data = event.response.usage

                        finish = "stop"
                        if tool_call_index > 0:
                            finish = "tool_calls"

                        chunk = ChatCompletionChunk(
                            id=request_id,
                            model=request.model,
                            choices=[StreamChoice(
                                index=0,
                                delta=DeltaMessage(),
                                finish_reason=finish,
                            )],
                        )
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                        )

                # Usage chunk if requested
                if request.stream_options and request.stream_options.include_usage and usage_data:
                    prompt_tokens = getattr(usage_data, "input_tokens", 0)
                    completion_tokens = getattr(usage_data, "output_tokens", 0)
                    cached_tokens = self._extract_cached_tokens(usage_data)
                    usage_chunk = ChatCompletionChunk(
                        id=request_id,
                        model=request.model,
                        choices=[],
                        usage=Usage(
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=prompt_tokens + completion_tokens,
                            prompt_tokens_details=(
                                PromptTokensDetails(cached_tokens=cached_tokens) if cached_tokens else None
                            ),
                            cache_read_input_tokens=cached_tokens,
                        ),
                    )
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        f"data: {usage_chunk.model_dump_json(exclude_none=True)}\n\n"
                    )

                loop.call_soon_threadsafe(queue.put_nowait, "data: [DONE]\n\n")

                # Internal usage marker
                if usage_data:
                    prompt_tokens = getattr(usage_data, "input_tokens", 0)
                    completion_tokens = getattr(usage_data, "output_tokens", 0)
                    cached_tokens = self._extract_cached_tokens(usage_data)
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        f"__usage__:{json.dumps({'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens, 'total_tokens': prompt_tokens + completion_tokens, 'cached_tokens': cached_tokens, 'cache_write_tokens': 0})}"
                    )

            except Exception as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"
                )
                loop.call_soon_threadsafe(queue.put_nowait, "data: [DONE]\n\n")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        loop.run_in_executor(None, _stream_in_thread)

        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if item is _SENTINEL:
                break
            yield item
