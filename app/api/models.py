"""Models API endpoint."""
from fastapi import APIRouter, Depends

from app.middleware.auth import get_api_key_info
from app.schemas.openai import Model, ModelList
from app.services.bedrock_service import BedrockService

router = APIRouter(tags=["Models"])


def get_bedrock_service() -> BedrockService:
    return BedrockService()


@router.get("/v1/models", response_model=ModelList)
async def list_models(
    api_key_info: dict = Depends(get_api_key_info),
    bedrock_service: BedrockService = Depends(get_bedrock_service),
):
    """List available models."""
    models_data = bedrock_service.list_models()
    models = [Model(**m) for m in models_data]
    return ModelList(data=models)


@router.get("/v1/models/{model_id}", response_model=Model)
async def get_model(
    model_id: str,
    api_key_info: dict = Depends(get_api_key_info),
):
    """Get model details."""
    return Model(id=model_id, owned_by="anthropic")
