"""OpenAI model service via Bedrock Mantle Responses API."""
import asyncio
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

from openai import OpenAI

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
    Usage,
)
from app.services.openai_token import OpenAITokenManager


class OpenAIService:
    """Routes OpenAI model requests to Bedrock Mantle via Responses API."""

    def __init__(self, dynamodb_client=None):
        self.token_manager = OpenAITokenManager(dynamodb_client)
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        return OpenAI(
            base_url=self.token_manager.get_base_url(),
            api_key=self.token_manager.get_api_key(),
        )

    def _convert_to_responses_input(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Convert Chat Completions messages to Responses API params."""
        instructions = None
        input_items: List[Dict[str, Any]] = []

        for msg in request.messages:
            if msg.role == "system":
                text = msg.content if isinstance(msg.content, str) else ""
                if instructions:
                    instructions += "\n" + text
                else:
                    instructions = text

            elif msg.role == "user":
                content = msg.content if isinstance(msg.content, str) else ""
                input_items.append({"role": "user", "content": content})

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
                            "role": "assistant", "content": msg.content
                        })
                else:
                    input_items.append({
                        "role": "assistant",
                        "content": msg.content or "",
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

    def _build_responses_kwargs(self, request: ChatCompletionRequest, model_id: str) -> Dict[str, Any]:
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
                    tools.append({
                        "type": "function",
                        "name": tool.function.name,
                        "description": tool.function.description or "",
                        "parameters": tool.function.parameters.model_dump() if tool.function.parameters else {},
                    })
            if tools:
                kwargs["tools"] = tools

        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice

        return kwargs

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        model_id: str,
        request_id: Optional[str] = None,
    ) -> tuple[ChatCompletionResponse, Dict[str, Any]]:
        """Non-streaming completion via Responses API."""
        request_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"
        kwargs = self._build_responses_kwargs(request, model_id)

        loop = asyncio.get_running_loop()
        client = self._get_client()
        response = await loop.run_in_executor(
            None, lambda: client.responses.create(**kwargs)
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

        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

        return (
            ChatCompletionResponse(
                id=request_id,
                created=int(time.time()),
                model=request.model,
                choices=[Choice(index=0, message=choice_message, finish_reason=finish_reason)],
                usage=usage,
            ),
            {"cached_tokens": 0, "cache_write_tokens": 0, "cache_write_ttl": None},
        )

    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        model_id: str,
        request_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming completion via Responses API."""
        request_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"
        kwargs = self._build_responses_kwargs(request, model_id)
        kwargs["stream"] = True

        _SENTINEL = object()
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _stream_in_thread():
            try:
                client = self._get_client()
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
                    usage_chunk = ChatCompletionChunk(
                        id=request_id,
                        model=request.model,
                        choices=[],
                        usage=Usage(
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=prompt_tokens + completion_tokens,
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
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        f"__usage__:{json.dumps({'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens, 'total_tokens': prompt_tokens + completion_tokens, 'cached_tokens': 0, 'cache_write_tokens': 0})}"
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
            item = await queue.get()
            if item is _SENTINEL:
                break
            yield item
