"""Convert OpenAI API format to Bedrock Converse API format."""
import base64
import json as json_module
import re
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings
from app.schemas.openai import ChatCompletionRequest, Message, Tool

# Reasoning effort to thinking budget_tokens mapping
REASONING_EFFORT_MAP = {
    "low": 1024,
    "medium": 10000,
    "high": 32000,
}

# Models that do not support prompt caching
CACHING_UNSUPPORTED_MODELS = {
    "claude-3-5-haiku",
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
}


class OpenAIToBedrockConverter:
    """Converts OpenAI Chat Completion requests to Bedrock Converse format."""

    def __init__(self, dynamodb_client=None):
        self.model_mapping = settings.default_model_mapping
        self.dynamodb_client = dynamodb_client
        self._resolved_model_id: Optional[str] = None

    def convert_request(
        self, request: ChatCompletionRequest, cache_ttl: Optional[str] = None
    ) -> Dict[str, Any]:
        """Convert OpenAI request to Bedrock Converse format.

        Args:
            cache_ttl: Resolved cache TTL ("5m", "1h") or None to disable caching.
        """
        self._resolved_model_id = self._convert_model_id(request.model)

        bedrock_request = {
            "modelId": self._resolved_model_id,
            "messages": self._convert_messages(request.messages),
            "inferenceConfig": self._build_inference_config(request),
        }

        # Check for explicit cache_control in user content
        has_explicit_cache = self._has_explicit_cache_control(request)

        # Extract system message and inject response_format instructions
        system_content = self._extract_system(request.messages)
        if request.response_format:
            format_instruction = self._build_response_format_instruction(request.response_format)
            if format_instruction:
                if system_content is None:
                    system_content = []
                system_content.append({"text": format_instruction})
        if system_content:
            bedrock_request["system"] = system_content

        # Convert tools
        if request.tools and settings.enable_tool_use:
            bedrock_request["toolConfig"] = self._convert_tools(request.tools, request.tool_choice)

        # Inject cache points (automatic mode)
        if cache_ttl and not has_explicit_cache:
            if self._model_supports_caching(request.model, self._resolved_model_id):
                self._inject_cache_points(bedrock_request, cache_ttl)

        # Handle explicit cache_control from client
        if has_explicit_cache and cache_ttl:
            if self._model_supports_caching(request.model, self._resolved_model_id):
                self._apply_explicit_cache_control(bedrock_request, request, cache_ttl)

        # Extended thinking: explicit thinking takes precedence over reasoning_effort
        thinking_config = None
        if request.thinking and settings.enable_extended_thinking:
            thinking_config = request.thinking
        elif request.reasoning_effort and settings.enable_extended_thinking:
            budget = REASONING_EFFORT_MAP.get(request.reasoning_effort, 10000)
            thinking_config = {"type": "enabled", "budget_tokens": budget}

        if thinking_config:
            additional = bedrock_request.get("additionalModelRequestFields", {})
            additional["thinking"] = thinking_config
            bedrock_request["additionalModelRequestFields"] = additional
            # Extended thinking requires temperature=1 and no top_p
            bedrock_request["inferenceConfig"].pop("topP", None)
            bedrock_request["inferenceConfig"]["temperature"] = 1.0
            # max_tokens must be > budget_tokens
            budget = thinking_config.get("budget_tokens", 0)
            current_max = bedrock_request["inferenceConfig"].get("maxTokens", 4096)
            if current_max <= budget:
                bedrock_request["inferenceConfig"]["maxTokens"] = budget + 4096

        return bedrock_request

    def _convert_model_id(self, openai_model_id: str) -> str:
        """Convert OpenAI model ID to Bedrock model ID."""
        # Check DynamoDB custom mapping first
        if self.dynamodb_client:
            try:
                from app.db.dynamodb import ModelMappingManager
                manager = ModelMappingManager(self.dynamodb_client)
                custom = manager.get_mapping(openai_model_id)
                if custom:
                    return custom
            except Exception:
                pass

        # Default mapping
        if openai_model_id in self.model_mapping:
            return self.model_mapping[openai_model_id]

        # Pass-through
        return openai_model_id

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert messages, excluding system messages."""
        bedrock_messages = []

        for msg in messages:
            if msg.role == "system":
                continue  # System handled separately

            bedrock_msg = {
                "role": "user" if msg.role in ("user", "tool") else "assistant",
                "content": self._convert_content(msg),
            }
            bedrock_messages.append(bedrock_msg)

        return bedrock_messages

    def _convert_content(self, msg: Message) -> List[Dict[str, Any]]:
        """Convert message content to Bedrock format."""
        content = []

        # Handle tool result
        if msg.role == "tool" and msg.tool_call_id:
            content.append({
                "toolResult": {
                    "toolUseId": msg.tool_call_id,
                    "content": [{"text": msg.content or ""}],
                    "status": "success",
                }
            })
            return content

        # Handle assistant tool calls
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                content.append({
                    "toolUse": {
                        "toolUseId": tc.id,
                        "name": tc.function.name,
                        "input": self._parse_json_safe(tc.function.arguments),
                    }
                })
            if msg.content:
                content.insert(0, {"text": msg.content})
            return content

        # Handle string content
        if isinstance(msg.content, str):
            return [{"text": msg.content}]

        # Handle array content (vision)
        if isinstance(msg.content, list):
            for part in msg.content:
                if hasattr(part, "type"):
                    if part.type == "text":
                        content.append({"text": part.text})
                    elif part.type == "image_url" and settings.enable_vision:
                        image_data = self._process_image(part.image_url.url)
                        if image_data:
                            content.append({"image": image_data})
                elif isinstance(part, dict):
                    if part.get("type") == "text":
                        content.append({"text": part.get("text", "")})
                    elif part.get("type") == "image_url" and settings.enable_vision:
                        url = part.get("image_url", {}).get("url", "")
                        image_data = self._process_image(url)
                        if image_data:
                            content.append({"image": image_data})

        return content if content else [{"text": ""}]

    def _process_image(self, url: str) -> Optional[Dict[str, Any]]:
        """Process image URL to Bedrock format."""
        if url.startswith("data:"):
            # Base64 data URL
            match = re.match(r"data:image/(\w+);base64,(.+)", url)
            if match:
                fmt = match.group(1)
                data = match.group(2)
                return {
                    "format": fmt,
                    "source": {"bytes": base64.b64decode(data)},
                }
        elif url.startswith(("http://", "https://")):
            # Download image
            try:
                resp = httpx.get(url, timeout=30)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "image/jpeg")
                fmt = content_type.split("/")[-1].split(";")[0]
                return {
                    "format": fmt,
                    "source": {"bytes": resp.content},
                }
            except Exception:
                return None
        return None

    def _extract_system(self, messages: List[Message]) -> Optional[List[Dict[str, Any]]]:
        """Extract system messages."""
        system_parts = []
        for msg in messages:
            if msg.role == "system" and msg.content:
                if isinstance(msg.content, str):
                    system_parts.append({"text": msg.content})
                elif isinstance(msg.content, list):
                    for part in msg.content:
                        if hasattr(part, "text"):
                            system_parts.append({"text": part.text})
        return system_parts if system_parts else None

    def _build_inference_config(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Build inference configuration."""
        config = {}
        if request.max_tokens:
            config["maxTokens"] = request.max_tokens
        if request.temperature is not None:
            config["temperature"] = min(request.temperature, 1.0)  # Bedrock max is 1.0
        elif request.top_p is not None:
            # Claude doesn't allow both temperature and top_p
            config["topP"] = request.top_p
        if request.stop:
            stops = request.stop if isinstance(request.stop, list) else [request.stop]
            config["stopSequences"] = stops[:4]  # Bedrock max 4
        return config

    def _convert_tools(
        self, tools: List[Tool], tool_choice: Optional[Any]
    ) -> Dict[str, Any]:
        """Convert tools to Bedrock format."""
        bedrock_tools = []
        for tool in tools:
            if tool.type == "function":
                bedrock_tool = {
                    "toolSpec": {
                        "name": tool.function.name,
                        "description": tool.function.description or "",
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": tool.function.parameters.properties
                                if tool.function.parameters
                                else {},
                                "required": tool.function.parameters.required
                                if tool.function.parameters
                                else [],
                            }
                        },
                    }
                }
                bedrock_tools.append(bedrock_tool)

        tool_config = {"tools": bedrock_tools}

        # Tool choice
        if tool_choice:
            if tool_choice == "none":
                tool_config["toolChoice"] = {"auto": {}}  # Bedrock doesn't have "none"
            elif tool_choice == "auto":
                tool_config["toolChoice"] = {"auto": {}}
            elif tool_choice == "required":
                tool_config["toolChoice"] = {"any": {}}
            elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
                tool_config["toolChoice"] = {"tool": {"name": tool_choice["function"]["name"]}}

        return tool_config

    def _build_response_format_instruction(self, response_format) -> Optional[str]:
        """Build system prompt instruction for response_format."""
        if response_format.type == "text":
            return None
        elif response_format.type == "json_object":
            return (
                "\n\n[RESPONSE FORMAT REQUIREMENT] "
                "Your entire response must be a single valid JSON object. "
                "Do NOT include ```json or ``` markers. "
                "Do NOT include any explanatory text before or after the JSON. "
                "Start your response with { and end with }."
            )
        elif response_format.type == "json_schema" and response_format.json_schema:
            schema = response_format.json_schema
            schema_dict = schema.schema_ or {}
            schema_json = json_module.dumps(schema_dict, indent=2)
            return (
                f"\n\n[RESPONSE FORMAT REQUIREMENT] "
                f"Your entire response must be a single valid JSON object that strictly conforms to this schema:\n"
                f"Schema name: {schema.name}\n"
                f"{schema_json}\n"
                f"Do NOT include ```json or ``` markers. "
                f"Do NOT include any explanatory text before or after the JSON. "
                f"Start your response with {{ and end with }}."
            )
        return None

    def _parse_json_safe(self, s: str) -> Dict[str, Any]:
        """Safely parse JSON string."""
        import json
        try:
            return json.loads(s)
        except Exception:
            return {}

    def _model_supports_caching(self, openai_model: str, bedrock_model: str) -> bool:
        """Check if the model supports prompt caching."""
        return (
            openai_model not in CACHING_UNSUPPORTED_MODELS
            and bedrock_model not in CACHING_UNSUPPORTED_MODELS
        )

    def _has_explicit_cache_control(self, request: ChatCompletionRequest) -> bool:
        """Check if any message content has explicit cache_control."""
        for msg in request.messages:
            if isinstance(msg.content, list):
                for part in msg.content:
                    if hasattr(part, "cache_control") and part.cache_control:
                        return True
        return False

    def _inject_cache_points(self, bedrock_request: dict, ttl: str) -> None:
        """Auto-inject cachePoints for system, last assistant message, and tools."""
        cache_point = {"cachePoint": {"type": "default", "ttl": ttl}}

        # 1. System prompt end
        if "system" in bedrock_request:
            system_text = " ".join(
                b.get("text", "") for b in bedrock_request["system"] if "text" in b
            )
            estimated_tokens = len(system_text) / 4
            if estimated_tokens >= settings.prompt_cache_min_tokens:
                bedrock_request["system"].append(dict(cache_point))

        # 2. Last assistant message end (cache conversation history)
        messages = bedrock_request.get("messages", [])
        if len(messages) >= 3:
            for i in range(len(messages) - 2, -1, -1):
                if messages[i]["role"] == "assistant":
                    messages[i]["content"].append(dict(cache_point))
                    break

        # 3. Tools definition end
        if "toolConfig" in bedrock_request:
            tools = bedrock_request["toolConfig"].get("tools", [])
            if tools:
                tools.append(dict(cache_point))

    def _apply_explicit_cache_control(
        self, bedrock_request: dict, request: ChatCompletionRequest, ttl: str
    ) -> None:
        """Convert explicit cache_control markers to Bedrock cachePoints."""
        cache_point = {"cachePoint": {"type": "default", "ttl": ttl}}

        # Rebuild messages with cachePoints after marked content
        for bedrock_msg, orig_msg in zip(
            bedrock_request.get("messages", []),
            [m for m in request.messages if m.role != "system"],
        ):
            if isinstance(orig_msg.content, list):
                new_content = []
                for part, bedrock_block in zip(orig_msg.content, bedrock_msg.get("content", [])):
                    new_content.append(bedrock_block)
                    if hasattr(part, "cache_control") and part.cache_control:
                        new_content.append(dict(cache_point))
                if new_content:
                    bedrock_msg["content"] = new_content

    def get_resolved_model_id(self) -> Optional[str]:
        return self._resolved_model_id
