"""OpenAI Configuration schemas."""
from typing import Optional
from pydantic import BaseModel


class OpenAIConfigResponse(BaseModel):
    base_url: str
    auth_mode: str  # "dynamic" or "static"
    bearer_token: Optional[str] = None
    updated_at: Optional[str] = None


class OpenAIConfigUpdate(BaseModel):
    base_url: Optional[str] = None
    auth_mode: Optional[str] = None  # "dynamic" or "static"
    bearer_token: Optional[str] = None
