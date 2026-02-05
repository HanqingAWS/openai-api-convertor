"""API Keys management endpoints."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.db.dynamodb import DynamoDBClient, APIKeyManager

router = APIRouter()


class CreateAPIKeyRequest(BaseModel):
    user_id: str
    name: str
    rate_limit: int = 100


class APIKeyResponse(BaseModel):
    api_key: str
    user_id: str
    name: str
    rate_limit: int
    is_active: bool = True
    created_at: Optional[str] = None


class APIKeyListResponse(BaseModel):
    keys: List[APIKeyResponse]
    total: int


def get_api_key_manager(request: Request) -> APIKeyManager:
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    if not dynamodb_client:
        raise HTTPException(status_code=503, detail="Database not available")
    return APIKeyManager(dynamodb_client)


@router.get("", response_model=APIKeyListResponse)
async def list_api_keys(
    request: Request,
    manager: APIKeyManager = Depends(get_api_key_manager),
):
    """List all API keys."""
    try:
        # Scan all keys (for admin use only)
        response = manager.client.scan(TableName=manager.table_name)
        keys = []
        for item in response.get("Items", []):
            keys.append(APIKeyResponse(
                api_key=item.get("api_key", {}).get("S", "")[:20] + "...",  # Mask key
                user_id=item.get("user_id", {}).get("S", ""),
                name=item.get("name", {}).get("S", ""),
                rate_limit=int(item.get("rate_limit", {}).get("N", "100")),
                is_active=item.get("is_active", {}).get("BOOL", True),
                created_at=item.get("created_at", {}).get("S"),
            ))
        return APIKeyListResponse(keys=keys, total=len(keys))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=APIKeyResponse)
async def create_api_key(
    request: Request,
    data: CreateAPIKeyRequest,
    manager: APIKeyManager = Depends(get_api_key_manager),
):
    """Create a new API key."""
    try:
        result = manager.create_api_key(
            user_id=data.user_id,
            name=data.name,
            rate_limit=data.rate_limit,
        )
        return APIKeyResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{api_key}")
async def delete_api_key(
    api_key: str,
    request: Request,
    manager: APIKeyManager = Depends(get_api_key_manager),
):
    """Delete (deactivate) an API key."""
    try:
        manager.client.update_item(
            TableName=manager.table_name,
            Key={"api_key": {"S": api_key}},
            UpdateExpression="SET is_active = :val",
            ExpressionAttributeValues={":val": {"BOOL": False}},
        )
        return {"message": "API key deactivated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{api_key}/rate-limit")
async def update_rate_limit(
    api_key: str,
    rate_limit: int,
    request: Request,
    manager: APIKeyManager = Depends(get_api_key_manager),
):
    """Update API key rate limit."""
    try:
        manager.client.update_item(
            TableName=manager.table_name,
            Key={"api_key": {"S": api_key}},
            UpdateExpression="SET rate_limit = :val",
            ExpressionAttributeValues={":val": {"N": str(rate_limit)}},
        )
        return {"message": "Rate limit updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
