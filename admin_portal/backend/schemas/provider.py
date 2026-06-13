"""Provider schemas."""
from typing import List, Optional
from pydantic import BaseModel


class ProviderCreate(BaseModel):
    name: str
    aws_region: str
    auth_type: str  # "ak_sk" or "bearer_token"
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    bearer_token: Optional[str] = None
    endpoint_url: Optional[str] = None


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    aws_region: Optional[str] = None
    auth_type: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    bearer_token: Optional[str] = None
    endpoint_url: Optional[str] = None
    is_active: Optional[bool] = None


class ProviderResponse(BaseModel):
    provider_id: str
    name: str
    aws_region: str
    auth_type: str
    has_access_key: bool = False
    has_secret_access_key: bool = False
    has_bearer_token: bool = False
    endpoint_url: Optional[str] = None
    is_active: bool = True
    created_at: int = 0
    updated_at: int = 0


class ProviderListResponse(BaseModel):
    items: List[ProviderResponse]
    count: int
