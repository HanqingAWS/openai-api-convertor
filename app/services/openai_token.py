"""OpenAI token manager for Bedrock Mantle endpoint."""
import time
from typing import Optional

from app.core.config import settings

DEFAULT_OPENAI_BASE_URL = "https://bedrock-mantle.us-east-2.api.aws/openai/v1"
# Token valid ~12h but IAM role credentials rotate ~6h on ECS.
# Cache for 5.5h to stay well within both limits.
TOKEN_CACHE_SECONDS = 5.5 * 3600  # 5.5 hours


class OpenAITokenManager:
    """Manages authentication for Bedrock Mantle (OpenAI-compatible endpoint).

    Supports two modes:
    - dynamic: generates bearer tokens from IAM role credentials, cached ~5.5h,
      with automatic refresh on 401 (call invalidate_token() then retry)
    - static: uses a user-provided bearer token stored in DynamoDB
    """

    def __init__(self, dynamodb_client=None):
        self._dynamodb_client = dynamodb_client
        self._cached_token: Optional[str] = None
        self._token_expiry: float = 0

    def _get_config_manager(self):
        if not self._dynamodb_client:
            return None
        from app.db.dynamodb import ConfigManager
        return ConfigManager(self._dynamodb_client)

    def get_base_url(self) -> str:
        manager = self._get_config_manager()
        if manager:
            url = manager.get_config("openai_base_url")
            if url:
                return url
        return DEFAULT_OPENAI_BASE_URL

    def get_auth_mode(self) -> str:
        manager = self._get_config_manager()
        if manager:
            mode = manager.get_config("openai_auth_mode")
            if mode in ("dynamic", "static"):
                return mode
        return "dynamic"

    def get_api_key(self) -> str:
        mode = self.get_auth_mode()
        if mode == "static":
            return self._get_static_token()
        return self._get_dynamic_token()

    def invalidate_token(self) -> None:
        """Force token refresh on next get_api_key() call.
        Call this when a 401 is received from Bedrock Mantle."""
        self._cached_token = None
        self._token_expiry = 0

    def _get_static_token(self) -> str:
        manager = self._get_config_manager()
        if manager:
            token = manager.get_config("openai_bearer_token")
            if token:
                return token
        return ""

    def _get_dynamic_token(self) -> str:
        now = time.time()
        if self._cached_token and now < self._token_expiry:
            return self._cached_token

        try:
            from aws_bedrock_token_generator import BedrockTokenGenerator
            generator = BedrockTokenGenerator(region="us-east-2")
            token = generator.generate_token()
            self._cached_token = token
            self._token_expiry = now + TOKEN_CACHE_SECONDS
            return token
        except Exception as e:
            print(f"[OpenAITokenManager] Error generating dynamic token: {e}")
            return self._cached_token or ""
