"""Convert OpenAI API format to Bedrock Converse API format."""
import base64
import re
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings
from app.schemas.openai import ChatCompletionRequest, Message, Tool


class OpenAIToBedrockConverter:
    """Converts OpenAI Chat Completion requests to Bedrock Converse format."""

    def __init__(self, dynamodb_client=None):
        self.model_mapping = settings.default_model_mapping
        self.dynamodb_client = dynamodb_client
        self._resolved_model_id: Optional[str] = None

    def convert_request(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Convert OpenAI request to Bedrock Converse format."""
        self._resolved_model_id = self._convert_model_id(request.model)

        bedrock_request = {
            "modelId": self._resolved_model_id,
            "messages": self._convert_messages(request.messages),
            "inferenceConfig": self._build_inference_config(request),
        }

        # Extract system message
        system_content = self._extract_system(request.messages)
        if system_content:
            bedrock_request["system"] = system_content

        # Convert tools
        if request.tools and settings.enable_tool_use:
            bedrock_request["toolConfig"] = self._convert_tools(request.tools, request.tool_choice)

        # Extended thinking
        if request.thinking and settings.enable_extended_thinking:
            additional = bedrock_request.get("additionalModelRequestFields", {})
            additional["thinking"] = request.thinking
            bedrock_request["additionalModelRequestFields"] = additional

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
        if request.top_p is not None:
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

    def _parse_json_safe(self, s: str) -> Dict[str, Any]:
        """Safely parse JSON string."""
        import json
        try:
            return json.loads(s)
        except Exception:
            return {}

    def get_resolved_model_id(self) -> Optional[str]:
        return self._resolved_model_id
