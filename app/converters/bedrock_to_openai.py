"""Convert Bedrock Converse API response to OpenAI format."""
import json
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.schemas.openai import (
    ChatCompletionResponse,
    ChatCompletionChunk,
    Choice,
    ChoiceMessage,
    StreamChoice,
    DeltaMessage,
    ToolCall,
    FunctionCall,
    Usage,
    PromptTokensDetails,
    CacheCreation,
)


class BedrockToOpenAIConverter:
    """Converts Bedrock Converse responses to OpenAI format."""

    def __init__(self):
        # Streaming state: maps content block index -> (toolUseId, name, tool_call_index)
        self._stream_tool_state: Dict[int, Dict[str, Any]] = {}
        self._stream_tool_call_count: int = 0

    STOP_REASON_MAP = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "content_filtered": "content_filter",
    }

    def convert_response(
        self, bedrock_response: Dict[str, Any], model: str, request_id: Optional[str] = None,
        cache_ttl: Optional[str] = None,
    ) -> ChatCompletionResponse:
        """Convert Bedrock response to OpenAI ChatCompletion format."""
        response_id = request_id or f"chatcmpl-{uuid4().hex[:24]}"

        # Extract content
        output = bedrock_response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])

        # Build response content
        text_content = ""
        tool_calls = []
        thinking_content = None

        for block in content_blocks:
            if "text" in block:
                text_content += block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(
                    ToolCall(
                        id=tu.get("toolUseId", f"call_{uuid4().hex[:24]}"),
                        type="function",
                        function=FunctionCall(
                            name=tu.get("name", ""),
                            arguments=json.dumps(tu.get("input", {})),
                        ),
                    )
                )
            elif "reasoningContent" in block:
                rc = block["reasoningContent"]
                if "reasoningText" in rc:
                    thinking_content = rc["reasoningText"].get("text", "")

        # Build message
        choice_message = ChoiceMessage(
            role="assistant",
            content=text_content if text_content else None,
            tool_calls=tool_calls if tool_calls else None,
            thinking=thinking_content,
        )

        # Stop reason
        stop_reason = bedrock_response.get("stopReason", "end_turn")
        finish_reason = self.STOP_REASON_MAP.get(stop_reason, "stop")
        if tool_calls:
            finish_reason = "tool_calls"

        # Usage - prompt_tokens includes all input tokens (OpenAI convention)
        # Bedrock splits: inputTokens (non-cached) + cacheReadInputTokens + cacheWriteInputTokens
        usage_data = bedrock_response.get("usage", {})
        input_tokens = usage_data.get("inputTokens", 0)
        cache_read = usage_data.get("cacheReadInputTokens", 0)
        cache_write = usage_data.get("cacheWriteInputTokens", 0)
        output_tokens = usage_data.get("outputTokens", 0)
        prompt_tokens = input_tokens + cache_read + cache_write

        prompt_details = None
        cache_creation = None
        if cache_read > 0 or cache_write > 0:
            prompt_details = PromptTokensDetails(cached_tokens=cache_read)
            ttl = cache_ttl or "5m"
            cache_creation = CacheCreation(
                ephemeral_5m_input_tokens=cache_write if ttl == "5m" else 0,
                ephemeral_1h_input_tokens=cache_write if ttl == "1h" else 0,
            )

        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=output_tokens,
            total_tokens=prompt_tokens + output_tokens,
            prompt_tokens_details=prompt_details,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,
            cache_creation=cache_creation,
        )

        return ChatCompletionResponse(
            id=response_id,
            created=int(time.time()),
            model=model,
            choices=[
                Choice(
                    index=0,
                    message=choice_message,
                    finish_reason=finish_reason,
                )
            ],
            usage=usage,
        )

    def convert_stream_event(
        self,
        event: Dict[str, Any],
        model: str,
        request_id: str,
        current_index: int = 0,
    ) -> List[str]:
        """Convert Bedrock stream event to OpenAI SSE format."""
        events = []

        # Message start
        if "messageStart" in event:
            self._stream_tool_state.clear()
            self._stream_tool_call_count = 0
            chunk = ChatCompletionChunk(
                id=request_id,
                model=model,
                choices=[
                    StreamChoice(
                        index=0,
                        delta=DeltaMessage(role="assistant"),
                        finish_reason=None,
                    )
                ],
            )
            events.append(f"data: {chunk.model_dump_json()}\n\n")

        # Content block start (for tool use) — must be before delta to populate state
        elif "contentBlockStart" in event:
            block_index = event["contentBlockStart"].get("contentBlockIndex", current_index)
            start = event["contentBlockStart"].get("start", {})
            if "toolUse" in start:
                tu = start["toolUse"]
                tool_id = tu.get("toolUseId", f"call_{current_index}")
                tool_name = tu.get("name", "")
                tool_call_idx = self._stream_tool_call_count
                self._stream_tool_call_count += 1
                # Save state so subsequent deltas can reference it
                self._stream_tool_state[block_index] = {
                    "id": tool_id, "name": tool_name, "index": tool_call_idx
                }
                tool_call = ToolCall(
                    index=tool_call_idx,
                    id=tool_id,
                    type="function",
                    function=FunctionCall(
                        name=tool_name,
                        arguments="",
                    ),
                )
                chunk = ChatCompletionChunk(
                    id=request_id,
                    model=model,
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=DeltaMessage(tool_calls=[tool_call]),
                            finish_reason=None,
                        )
                    ],
                )
                events.append(f"data: {chunk.model_dump_json()}\n\n")

        # Content block delta
        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})

            if "text" in delta:
                chunk = ChatCompletionChunk(
                    id=request_id,
                    model=model,
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=DeltaMessage(content=delta["text"]),
                            finish_reason=None,
                        )
                    ],
                )
                events.append(f"data: {chunk.model_dump_json()}\n\n")

            elif "toolUse" in delta:
                tu = delta["toolUse"]
                if "input" in tu:
                    input_chunk = tu.get("input", "")
                    if input_chunk:
                        # Look up id/name/index from contentBlockStart state using block index
                        block_index = event["contentBlockDelta"].get("contentBlockIndex", current_index)
                        state = self._stream_tool_state.get(
                            block_index, {"id": f"call_{current_index}", "name": "", "index": 0}
                        )
                        tool_call = ToolCall(
                            index=state["index"],
                            id=state["id"],
                            type="function",
                            function=FunctionCall(
                                name=state["name"],
                                arguments=input_chunk,
                            ),
                        )
                        chunk = ChatCompletionChunk(
                            id=request_id,
                            model=model,
                            choices=[
                                StreamChoice(
                                    index=0,
                                    delta=DeltaMessage(tool_calls=[tool_call]),
                                    finish_reason=None,
                                )
                            ],
                        )
                        events.append(f"data: {chunk.model_dump_json()}\n\n")

        # Message stop
        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason", "end_turn")
            finish_reason = self.STOP_REASON_MAP.get(stop_reason, "stop")

            chunk = ChatCompletionChunk(
                id=request_id,
                model=model,
                choices=[
                    StreamChoice(
                        index=0,
                        delta=DeltaMessage(),
                        finish_reason=finish_reason,
                    )
                ],
            )
            events.append(f"data: {chunk.model_dump_json()}\n\n")
            # Note: [DONE] is appended by the caller after optional usage chunk

        # Metadata event (contains usage)
        elif "metadata" in event:
            # Usage is extracted by the caller via extract_stream_usage()
            pass

        return events

    def extract_stream_usage(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract usage data from a metadata stream event."""
        if "metadata" not in event:
            return None
        metadata = event["metadata"]
        usage = metadata.get("usage", {})
        if not usage:
            return None

        input_tokens = usage.get("inputTokens", 0)
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        prompt_tokens = input_tokens + cache_read + cache_write

        # Parse cacheDetails for write TTL
        cache_write_ttl = None
        for detail in usage.get("cacheDetails", []):
            if detail.get("inputTokens", 0) > 0:
                cache_write_ttl = detail.get("ttl")
                break

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
            "cached_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "cache_write_ttl": cache_write_ttl,
        }

    def extract_cache_usage(self, bedrock_response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract cache usage from a non-streaming Bedrock response."""
        usage_data = bedrock_response.get("usage", {})
        cache_read = usage_data.get("cacheReadInputTokens", 0)
        cache_write = usage_data.get("cacheWriteInputTokens", 0)

        cache_write_ttl = None
        for detail in usage_data.get("cacheDetails", []):
            if detail.get("inputTokens", 0) > 0:
                cache_write_ttl = detail.get("ttl")
                break

        return {
            "cached_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "cache_write_ttl": cache_write_ttl,
        }

    def build_usage_chunk(
        self, request_id: str, model: str, usage_data: Dict[str, Any],
        cache_ttl: Optional[str] = None,
    ) -> str:
        """Build a final SSE chunk containing usage statistics."""
        prompt_details = None
        cache_creation = None
        cached = usage_data.get("cached_tokens", 0)
        cache_write = usage_data.get("cache_write_tokens", 0)

        if cached > 0 or cache_write > 0:
            prompt_details = PromptTokensDetails(cached_tokens=cached)
            ttl = cache_ttl or "5m"
            cache_creation = CacheCreation(
                ephemeral_5m_input_tokens=cache_write if ttl == "5m" else 0,
                ephemeral_1h_input_tokens=cache_write if ttl == "1h" else 0,
            )

        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            prompt_tokens_details=prompt_details,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cached,
            cache_creation=cache_creation,
        )
        chunk = ChatCompletionChunk(
            id=request_id,
            model=model,
            choices=[],
            usage=usage,
        )
        return f"data: {chunk.model_dump_json()}\n\n"
