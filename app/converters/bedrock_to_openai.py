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
)


class BedrockToOpenAIConverter:
    """Converts Bedrock Converse responses to OpenAI format."""

    STOP_REASON_MAP = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "content_filtered": "content_filter",
    }

    def convert_response(
        self, bedrock_response: Dict[str, Any], model: str, request_id: Optional[str] = None
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

        # Usage
        usage_data = bedrock_response.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("inputTokens", 0),
            completion_tokens=usage_data.get("outputTokens", 0),
            total_tokens=usage_data.get("inputTokens", 0) + usage_data.get("outputTokens", 0),
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
                # Tool call streaming - send partial arguments
                if "input" in tu:
                    # Bedrock sends input as string chunks
                    input_chunk = tu.get("input", "")
                    if input_chunk:
                        tool_call = ToolCall(
                            id=tu.get("toolUseId", f"call_{current_index}"),
                            type="function",
                            function=FunctionCall(
                                name=tu.get("name", ""),
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

        # Content block start (for tool use)
        elif "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            if "toolUse" in start:
                tu = start["toolUse"]
                tool_call = ToolCall(
                    id=tu.get("toolUseId", f"call_{current_index}"),
                    type="function",
                    function=FunctionCall(
                        name=tu.get("name", ""),
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
            events.append("data: [DONE]\n\n")

        return events
