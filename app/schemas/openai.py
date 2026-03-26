"""OpenAI API compatible schemas."""
import time
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# Stream options
class StreamOptions(BaseModel):
    include_usage: Optional[bool] = False


# Response format
class JsonSchema(BaseModel):
    name: str
    strict: Optional[bool] = None
    schema_: Optional[Dict[str, Any]] = Field(default=None, alias="schema")

    class Config:
        populate_by_name = True


class ResponseFormat(BaseModel):
    type: Literal["text", "json_object", "json_schema"] = "text"
    json_schema: Optional[JsonSchema] = None


# Cache control
class CacheControl(BaseModel):
    type: str = "ephemeral"


# Message content types
class TextContent(BaseModel):
    type: Literal["text"] = "text"
    text: str
    cache_control: Optional[CacheControl] = None


class ImageURL(BaseModel):
    url: str
    detail: Optional[Literal["auto", "low", "high"]] = "auto"


class ImageContent(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageURL


ContentPart = Union[TextContent, ImageContent]


# Tool/Function definitions
class FunctionParameters(BaseModel):
    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: Optional[List[str]] = None


class FunctionDefinition(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: Optional[FunctionParameters] = None


class Tool(BaseModel):
    type: Literal["function"] = "function"
    function: FunctionDefinition


class FunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


# Messages
class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[Union[str, List[ContentPart]]] = None
    name: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None


# Request
class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    max_tokens: Optional[int] = Field(default=4096, ge=1)
    max_completion_tokens: Optional[int] = Field(default=None, ge=1)
    temperature: Optional[float] = Field(default=1.0, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    n: Optional[int] = Field(default=1, ge=1, le=1)  # Only support n=1
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    tools: Optional[List[Tool]] = None
    tool_choice: Optional[Union[Literal["none", "auto", "required"], Dict[str, Any]]] = None
    user: Optional[str] = None
    # Structured output
    response_format: Optional[ResponseFormat] = None
    # Stream options
    stream_options: Optional[StreamOptions] = None
    # Reasoning effort (OpenAI standard)
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = None
    # Extended thinking (custom extension)
    thinking: Optional[Dict[str, Any]] = Field(default=None, alias="thinking")
    # Prompt caching control
    caching: Optional[bool] = None
    cache_ttl: Optional[str] = None

    class Config:
        populate_by_name = True


# Response
class PromptTokensDetails(BaseModel):
    cached_tokens: int = 0


class CacheCreation(BaseModel):
    ephemeral_5m_input_tokens: int = 0
    ephemeral_1h_input_tokens: int = 0


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_details: Optional[PromptTokensDetails] = None
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation: Optional[CacheCreation] = None


class ChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    # Extended thinking (custom extension)
    thinking: Optional[str] = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: Optional[Literal["stop", "length", "tool_calls", "content_filter"]] = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[Choice]
    usage: Usage


# Streaming response
class DeltaMessage(BaseModel):
    role: Optional[Literal["assistant"]] = None
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: Optional[Literal["stop", "length", "tool_calls", "content_filter"]] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[StreamChoice]
    usage: Optional[Usage] = None


# Models API
class Model(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "anthropic"
    capabilities: Optional[Dict[str, Any]] = None


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: List[Model]
