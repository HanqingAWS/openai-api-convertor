"""DynamoDB operations for API keys and usage tracking."""
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import boto3
from botocore.config import Config

from app.core.config import settings


class DynamoDBClient:
    """DynamoDB client wrapper."""

    def __init__(self):
        config = Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=10,
        )

        client_kwargs = {
            "service_name": "dynamodb",
            "region_name": settings.aws_region,
            "config": config,
        }

        if settings.dynamodb_endpoint_url:
            client_kwargs["endpoint_url"] = settings.dynamodb_endpoint_url

        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self.client = boto3.client(**client_kwargs)
        self.resource = boto3.resource(**client_kwargs)


class APIKeyManager:
    """Manage API keys in DynamoDB."""

    def __init__(self, dynamodb_client: DynamoDBClient):
        self.client = dynamodb_client.client
        self.table_name = settings.dynamodb_api_keys_table

    def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Validate API key and return key info if valid."""
        try:
            response = self.client.get_item(
                TableName=self.table_name,
                Key={"api_key": {"S": api_key}},
            )
            item = response.get("Item")
            if not item:
                return None

            is_active = item.get("is_active", {}).get("BOOL", True)
            if not is_active:
                return None

            return {
                "api_key": item.get("api_key", {}).get("S"),
                "user_id": item.get("user_id", {}).get("S"),
                "name": item.get("name", {}).get("S"),
                "rate_limit": int(item.get("rate_limit", {}).get("N", "100")),
                "created_at": item.get("created_at", {}).get("S"),
            }
        except Exception:
            return None

    def create_api_key(
        self,
        user_id: str,
        name: str,
        rate_limit: int = 100,
    ) -> Dict[str, Any]:
        """Create a new API key."""
        api_key = f"sk-{uuid4().hex}"
        created_at = datetime.utcnow().isoformat()

        self.client.put_item(
            TableName=self.table_name,
            Item={
                "api_key": {"S": api_key},
                "user_id": {"S": user_id},
                "name": {"S": name},
                "rate_limit": {"N": str(rate_limit)},
                "is_active": {"BOOL": True},
                "created_at": {"S": created_at},
            },
        )

        return {
            "api_key": api_key,
            "user_id": user_id,
            "name": name,
            "rate_limit": rate_limit,
            "created_at": created_at,
        }


class UsageTracker:
    """Track API usage in DynamoDB."""

    def __init__(self, dynamodb_client: DynamoDBClient):
        self.client = dynamodb_client.client
        self.table_name = settings.dynamodb_usage_table

    def record_usage(
        self,
        api_key: str,
        request_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        success: bool = True,
        error_message: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ):
        """Record API usage."""
        try:
            timestamp = int(time.time() * 1000)
            item = {
                "api_key": {"S": api_key},
                "timestamp": {"N": str(timestamp)},
                "request_id": {"S": request_id},
                "model": {"S": model},
                "prompt_tokens": {"N": str(prompt_tokens)},
                "completion_tokens": {"N": str(completion_tokens)},
                "total_tokens": {"N": str(prompt_tokens + completion_tokens)},
                "success": {"BOOL": success},
            }

            if error_message:
                item["error_message"] = {"S": error_message}
            if latency_ms:
                item["latency_ms"] = {"N": str(latency_ms)}

            self.client.put_item(TableName=self.table_name, Item=item)
        except Exception:
            pass  # Don't fail request on usage tracking error


class ModelMappingManager:
    """Manage model ID mappings in DynamoDB."""

    def __init__(self, dynamodb_client: DynamoDBClient):
        self.client = dynamodb_client.client
        self.table_name = settings.dynamodb_model_mapping_table

    def get_mapping(self, openai_model_id: str) -> Optional[str]:
        """Get Bedrock model ID for OpenAI model ID."""
        try:
            response = self.client.get_item(
                TableName=self.table_name,
                Key={"openai_model_id": {"S": openai_model_id}},
            )
            item = response.get("Item")
            if item:
                return item.get("bedrock_model_id", {}).get("S")
        except Exception:
            pass
        return None

    def set_mapping(self, openai_model_id: str, bedrock_model_id: str):
        """Set model ID mapping."""
        self.client.put_item(
            TableName=self.table_name,
            Item={
                "openai_model_id": {"S": openai_model_id},
                "bedrock_model_id": {"S": bedrock_model_id},
                "updated_at": {"S": datetime.utcnow().isoformat()},
            },
        )

    def list_mappings(self) -> List[Dict[str, str]]:
        """List all model mappings."""
        try:
            response = self.client.scan(TableName=self.table_name)
            mappings = []
            for item in response.get("Items", []):
                mappings.append({
                    "openai_model_id": item.get("openai_model_id", {}).get("S"),
                    "bedrock_model_id": item.get("bedrock_model_id", {}).get("S"),
                })
            return mappings
        except Exception:
            return []
