"""Pricing management API endpoints."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class ModelPricing(BaseModel):
    model_id: str
    input_price_per_1k: float  # USD per 1K tokens
    output_price_per_1k: float
    description: Optional[str] = None


class PricingListResponse(BaseModel):
    pricing: List[ModelPricing]


# Default pricing (based on Bedrock Claude pricing)
DEFAULT_PRICING = [
    ModelPricing(
        model_id="claude-opus-4-5-20251101",
        input_price_per_1k=0.015,
        output_price_per_1k=0.075,
        description="Claude Opus 4.5",
    ),
    ModelPricing(
        model_id="claude-opus-4-6",
        input_price_per_1k=0.015,
        output_price_per_1k=0.075,
        description="Claude Opus 4.6",
    ),
    ModelPricing(
        model_id="claude-sonnet-4-5-20250929",
        input_price_per_1k=0.003,
        output_price_per_1k=0.015,
        description="Claude Sonnet 4.5",
    ),
    ModelPricing(
        model_id="claude-haiku-4-5-20251001",
        input_price_per_1k=0.0008,
        output_price_per_1k=0.004,
        description="Claude Haiku 4.5",
    ),
    ModelPricing(
        model_id="claude-3-5-haiku-20241022",
        input_price_per_1k=0.0008,
        output_price_per_1k=0.004,
        description="Claude 3.5 Haiku",
    ),
]


@router.get("", response_model=PricingListResponse)
async def list_pricing(request: Request):
    """List all model pricing."""
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    
    if not dynamodb_client:
        return PricingListResponse(pricing=DEFAULT_PRICING)

    try:
        # Try to get pricing from DynamoDB
        table_name = f"openai-proxy-model-pricing-{settings.environment}"
        response = dynamodb_client.client.scan(TableName=table_name)
        
        pricing = []
        for item in response.get("Items", []):
            pricing.append(ModelPricing(
                model_id=item.get("model_id", {}).get("S", ""),
                input_price_per_1k=float(item.get("input_price_per_1k", {}).get("N", "0")),
                output_price_per_1k=float(item.get("output_price_per_1k", {}).get("N", "0")),
                description=item.get("description", {}).get("S"),
            ))
        
        if not pricing:
            return PricingListResponse(pricing=DEFAULT_PRICING)
            
        return PricingListResponse(pricing=pricing)
        
    except Exception:
        return PricingListResponse(pricing=DEFAULT_PRICING)


@router.put("/{model_id}")
async def update_pricing(
    model_id: str,
    pricing: ModelPricing,
    request: Request,
):
    """Update model pricing."""
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    
    if not dynamodb_client:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        table_name = f"openai-proxy-model-pricing-{settings.environment}"
        dynamodb_client.client.put_item(
            TableName=table_name,
            Item={
                "model_id": {"S": model_id},
                "input_price_per_1k": {"N": str(pricing.input_price_per_1k)},
                "output_price_per_1k": {"N": str(pricing.output_price_per_1k)},
                "description": {"S": pricing.description or ""},
            },
        )
        return {"message": "Pricing updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cost-estimate")
async def estimate_cost(
    request: Request,
    prompt_tokens: int = 1000,
    completion_tokens: int = 500,
    model_id: str = "claude-sonnet-4-5-20250929",
):
    """Estimate cost for given token usage."""
    # Find pricing for model
    pricing = next((p for p in DEFAULT_PRICING if p.model_id == model_id), None)
    
    if not pricing:
        raise HTTPException(status_code=404, detail=f"Pricing not found for model: {model_id}")

    input_cost = (prompt_tokens / 1000) * pricing.input_price_per_1k
    output_cost = (completion_tokens / 1000) * pricing.output_price_per_1k
    total_cost = input_cost + output_cost

    return {
        "model_id": model_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(total_cost, 6),
    }
