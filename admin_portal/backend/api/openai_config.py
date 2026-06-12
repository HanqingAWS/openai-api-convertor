"""OpenAI Configuration management routes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import APIRouter

from app.db.dynamodb import DynamoDBClient, ConfigManager
from admin_portal.backend.schemas.openai_config import (
    OpenAIConfigResponse,
    OpenAIConfigUpdate,
)

router = APIRouter()

DEFAULT_BASE_URL = "https://bedrock-mantle.us-east-2.api.aws/openai/v1"


def get_manager():
    db_client = DynamoDBClient()
    return ConfigManager(db_client)


@router.get("", response_model=OpenAIConfigResponse)
async def get_openai_config():
    """Get current OpenAI configuration."""
    manager = get_manager()
    configs = manager.get_all_configs()

    return OpenAIConfigResponse(
        base_url=configs.get("openai_base_url", DEFAULT_BASE_URL),
        auth_mode=configs.get("openai_auth_mode", "dynamic"),
        updated_at=configs.get("openai_updated_at"),
    )


@router.put("", response_model=OpenAIConfigResponse)
async def update_openai_config(request: OpenAIConfigUpdate):
    """Update OpenAI configuration."""
    manager = get_manager()

    if request.base_url is not None:
        manager.set_config("openai_base_url", request.base_url)

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    manager.set_config("openai_updated_at", ts)

    configs = manager.get_all_configs()
    return OpenAIConfigResponse(
        base_url=configs.get("openai_base_url", DEFAULT_BASE_URL),
        auth_mode=configs.get("openai_auth_mode", "dynamic"),
        updated_at=configs.get("openai_updated_at"),
    )
