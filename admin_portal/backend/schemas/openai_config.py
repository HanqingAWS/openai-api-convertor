"""OpenAI Configuration schemas."""
from typing import Optional
from pydantic import BaseModel


class OpenAIConfigResponse(BaseModel):
    base_url: str
    auth_mode: Optional[str] = None  # kept for backward compat read-only
    updated_at: Optional[str] = None


class OpenAIConfigUpdate(BaseModel):
    base_url: Optional[str] = None
