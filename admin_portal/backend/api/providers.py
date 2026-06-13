"""Provider management routes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import APIRouter, HTTPException, status

from app.db.dynamodb import DynamoDBClient, ProviderManager
from admin_portal.backend.schemas.provider import (
    ProviderCreate,
    ProviderUpdate,
    ProviderResponse,
    ProviderListResponse,
)

router = APIRouter()


def get_manager():
    db_client = DynamoDBClient()
    return ProviderManager(db_client)


def _to_response(item: dict) -> ProviderResponse:
    return ProviderResponse(
        provider_id=item.get("provider_id", ""),
        name=item.get("name", ""),
        aws_region=item.get("aws_region", ""),
        auth_type=item.get("auth_type", ""),
        has_access_key=bool(item.get("access_key_id")),
        has_bearer_token=bool(item.get("bearer_token")),
        endpoint_url=item.get("endpoint_url"),
        is_active=item.get("is_active", True),
        created_at=item.get("created_at", 0),
        updated_at=item.get("updated_at", 0),
    )


@router.get("", response_model=ProviderListResponse)
async def list_providers():
    manager = get_manager()
    result = manager.list_providers()
    items = [_to_response(i) for i in result.get("items", [])]
    return ProviderListResponse(items=items, count=len(items))


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: str):
    manager = get_manager()
    item = manager.get_provider(provider_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return _to_response(item)


@router.post("", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_provider(request: ProviderCreate):
    if request.auth_type not in ("ak_sk", "bearer_token"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="auth_type must be 'ak_sk' or 'bearer_token'",
        )
    if request.auth_type == "ak_sk" and (not request.access_key_id or not request.secret_access_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="access_key_id and secret_access_key are required for ak_sk auth type",
        )
    if request.auth_type == "bearer_token" and not request.bearer_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bearer_token is required for bearer_token auth type",
        )

    manager = get_manager()
    item = manager.create_provider(
        name=request.name,
        aws_region=request.aws_region,
        auth_type=request.auth_type,
        access_key_id=request.access_key_id,
        secret_access_key=request.secret_access_key,
        bearer_token=request.bearer_token,
        endpoint_url=request.endpoint_url,
    )
    return _to_response(item)


@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(provider_id: str, request: ProviderUpdate):
    manager = get_manager()
    existing = manager.get_provider(provider_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    update_fields = {}
    if request.name is not None:
        update_fields["name"] = request.name
    if request.aws_region is not None:
        update_fields["aws_region"] = request.aws_region
    if request.auth_type is not None:
        if request.auth_type not in ("ak_sk", "bearer_token"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="auth_type must be 'ak_sk' or 'bearer_token'",
            )
        update_fields["auth_type"] = request.auth_type
    if request.access_key_id is not None:
        update_fields["access_key_id"] = request.access_key_id
    if request.secret_access_key is not None:
        update_fields["secret_access_key"] = request.secret_access_key
    if request.bearer_token is not None:
        update_fields["bearer_token"] = request.bearer_token
    if request.endpoint_url is not None:
        update_fields["endpoint_url"] = request.endpoint_url
    if request.is_active is not None:
        update_fields["is_active"] = request.is_active

    if not update_fields:
        return _to_response(existing)

    updated = manager.update_provider(provider_id, **update_fields)
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update provider")
    return _to_response(updated)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: str):
    manager = get_manager()
    existing = manager.get_provider(provider_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    manager.delete_provider(provider_id)


@router.post("/{provider_id}/test")
async def test_provider(provider_id: str):
    """Test provider credentials by making a lightweight API call."""
    manager = get_manager()
    provider = manager.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    base_url = "https://bedrock-mantle.us-east-2.api.aws/openai/v1"
    auth_type = provider.get("auth_type", "")

    try:
        if auth_type == "bearer_token":
            token = provider.get("bearer_token", "")
            if not token:
                return {"success": False, "message": "No bearer token configured"}
        elif auth_type == "ak_sk":
            ak = provider.get("access_key_id", "")
            sk = provider.get("secret_access_key", "")
            if not ak or not sk:
                return {"success": False, "message": "No AK/SK configured"}
            import boto3
            from aws_bedrock_token_generator import BedrockTokenGenerator
            session = boto3.Session(
                aws_access_key_id=ak,
                aws_secret_access_key=sk,
                region_name="us-east-2",
            )
            credentials = session.get_credentials().get_frozen_credentials()
            generator = BedrockTokenGenerator()
            token = generator.get_token(credentials, "us-east-2")
        else:
            return {"success": False, "message": f"Unknown auth_type: {auth_type}"}

        import httpx
        resp = httpx.post(
            f"{base_url}/responses",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-5.5", "input": "hi", "max_output_tokens": 16},
            timeout=15.0,
        )
        if resp.status_code == 200:
            return {"success": True, "message": "OK - credentials valid"}
        elif resp.status_code == 401 or resp.status_code == 403:
            return {"success": False, "message": f"Auth failed ({resp.status_code})"}
        elif resp.status_code == 404:
            return {"success": True, "message": "OK - credentials valid (model not enabled)"}
        else:
            return {"success": True, "message": f"OK - credentials valid (status {resp.status_code})"}
    except Exception as e:
        return {"success": False, "message": str(e)}
