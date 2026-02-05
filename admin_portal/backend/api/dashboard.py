"""Dashboard API endpoints."""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class UsageStats(BaseModel):
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int


class ModelUsage(BaseModel):
    model: str
    requests: int
    tokens: int


class DailyUsage(BaseModel):
    date: str
    requests: int
    tokens: int


class DashboardResponse(BaseModel):
    stats: UsageStats
    by_model: List[ModelUsage]
    daily: List[DailyUsage]


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    request: Request,
    days: int = 7,
):
    """Get dashboard statistics."""
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    
    if not dynamodb_client:
        # Return mock data for development
        return DashboardResponse(
            stats=UsageStats(
                total_requests=1000,
                successful_requests=980,
                failed_requests=20,
                total_prompt_tokens=500000,
                total_completion_tokens=200000,
                total_tokens=700000,
            ),
            by_model=[
                ModelUsage(model="claude-sonnet-4-5-20250929", requests=600, tokens=400000),
                ModelUsage(model="claude-haiku-4-5-20251001", requests=400, tokens=300000),
            ],
            daily=[
                DailyUsage(date=(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d"), 
                          requests=100 + i * 10, tokens=50000 + i * 5000)
                for i in range(days)
            ],
        )

    try:
        # Query usage data from DynamoDB
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        # Aggregate stats
        stats = UsageStats(
            total_requests=0,
            successful_requests=0,
            failed_requests=0,
            total_prompt_tokens=0,
            total_completion_tokens=0,
            total_tokens=0,
        )
        
        model_stats: Dict[str, Dict] = {}
        daily_stats: Dict[str, Dict] = {}

        # Scan usage table (in production, use query with proper indexes)
        response = dynamodb_client.client.scan(
            TableName=settings.dynamodb_usage_table,
            FilterExpression="#ts BETWEEN :start AND :end",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":start": {"N": str(start_time)},
                ":end": {"N": str(end_time)},
            },
        )

        for item in response.get("Items", []):
            stats.total_requests += 1
            
            success = item.get("success", {}).get("BOOL", True)
            if success:
                stats.successful_requests += 1
            else:
                stats.failed_requests += 1

            prompt_tokens = int(item.get("prompt_tokens", {}).get("N", "0"))
            completion_tokens = int(item.get("completion_tokens", {}).get("N", "0"))
            
            stats.total_prompt_tokens += prompt_tokens
            stats.total_completion_tokens += completion_tokens
            stats.total_tokens += prompt_tokens + completion_tokens

            # By model
            model = item.get("model", {}).get("S", "unknown")
            if model not in model_stats:
                model_stats[model] = {"requests": 0, "tokens": 0}
            model_stats[model]["requests"] += 1
            model_stats[model]["tokens"] += prompt_tokens + completion_tokens

            # By day
            ts = int(item.get("timestamp", {}).get("N", "0"))
            date = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            if date not in daily_stats:
                daily_stats[date] = {"requests": 0, "tokens": 0}
            daily_stats[date]["requests"] += 1
            daily_stats[date]["tokens"] += prompt_tokens + completion_tokens

        return DashboardResponse(
            stats=stats,
            by_model=[
                ModelUsage(model=m, requests=s["requests"], tokens=s["tokens"])
                for m, s in model_stats.items()
            ],
            daily=[
                DailyUsage(date=d, requests=s["requests"], tokens=s["tokens"])
                for d, s in sorted(daily_stats.items())
            ],
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/usage/{api_key}")
async def get_api_key_usage(
    api_key: str,
    request: Request,
    days: int = 7,
):
    """Get usage statistics for a specific API key."""
    dynamodb_client = getattr(request.app.state, "dynamodb_client", None)
    
    if not dynamodb_client:
        return {"message": "Database not available"}

    try:
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        response = dynamodb_client.client.query(
            TableName=settings.dynamodb_usage_table,
            KeyConditionExpression="api_key = :key AND #ts BETWEEN :start AND :end",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":key": {"S": api_key},
                ":start": {"N": str(start_time)},
                ":end": {"N": str(end_time)},
            },
        )

        total_requests = len(response.get("Items", []))
        total_tokens = sum(
            int(item.get("total_tokens", {}).get("N", "0"))
            for item in response.get("Items", [])
        )

        return {
            "api_key": api_key[:20] + "...",
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "period_days": days,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
