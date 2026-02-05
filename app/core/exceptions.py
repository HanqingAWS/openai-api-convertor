"""Custom exceptions."""
from typing import Optional


class OpenAIProxyError(Exception):
    """Base exception for OpenAI Proxy."""

    def __init__(
        self,
        message: str,
        error_type: str = "server_error",
        param: Optional[str] = None,
        code: Optional[str] = None,
        http_status: int = 500,
    ):
        self.message = message
        self.error_type = error_type
        self.param = param
        self.code = code
        self.http_status = http_status
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error": {
                "message": self.message,
                "type": self.error_type,
                "param": self.param,
                "code": self.code,
            }
        }


class AuthenticationError(OpenAIProxyError):
    """Authentication failed."""

    def __init__(self, message: str = "Invalid API key"):
        super().__init__(
            message=message,
            error_type="authentication_error",
            code="invalid_api_key",
            http_status=401,
        )


class RateLimitError(OpenAIProxyError):
    """Rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(
            message=message,
            error_type="rate_limit_error",
            code="rate_limit_exceeded",
            http_status=429,
        )


class InvalidRequestError(OpenAIProxyError):
    """Invalid request."""

    def __init__(self, message: str, param: Optional[str] = None):
        super().__init__(
            message=message,
            error_type="invalid_request_error",
            param=param,
            code="invalid_request",
            http_status=400,
        )


class BedrockAPIError(OpenAIProxyError):
    """Bedrock API error."""

    def __init__(self, message: str, code: Optional[str] = None, http_status: int = 500):
        super().__init__(
            message=message,
            error_type="server_error",
            code=code or "bedrock_error",
            http_status=http_status,
        )
