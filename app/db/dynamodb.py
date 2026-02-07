"""DynamoDB operations for API keys, usage tracking, model pricing, and usage stats."""
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
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
        self.resource = dynamodb_client.resource
        self.table_name = settings.dynamodb_api_keys_table
        self.table = self.resource.Table(self.table_name)

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
                "service_tier": item.get("service_tier", {}).get("S", "default"),
            }
        except Exception:
            return None

    def create_api_key(
        self,
        user_id: str,
        name: str,
        owner_name: Optional[str] = None,
        role: Optional[str] = "Full Access",
        monthly_budget: Optional[float] = 0,
        rate_limit: Optional[int] = 100,
        service_tier: Optional[str] = "default",
    ) -> str:
        """Create a new API key. Returns the api_key string."""
        api_key = f"sk-{uuid4().hex}"
        now = int(time.time())

        item = {
            "api_key": api_key,
            "user_id": user_id,
            "name": name,
            "owner_name": owner_name or "",
            "role": role or "Full Access",
            "monthly_budget": Decimal(str(monthly_budget or 0)),
            "budget_used": Decimal("0"),
            "budget_used_mtd": Decimal("0"),
            "budget_mtd_month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "rate_limit": rate_limit or 100,
            "service_tier": service_tier or "default",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        self.table.put_item(Item=item)
        return api_key

    def get_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Get full details of a specific API key."""
        try:
            response = self.table.get_item(Key={"api_key": api_key})
            item = response.get("Item")
            if not item:
                return None
            return self._serialize_item(item)
        except Exception:
            return None

    def list_all_api_keys(
        self,
        limit: int = 100,
        status_filter: Optional[str] = None,
        last_key: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """List all API keys with optional filtering."""
        try:
            scan_kwargs = {"Limit": limit}
            if last_key:
                scan_kwargs["ExclusiveStartKey"] = last_key

            response = self.table.scan(**scan_kwargs)
            items = [self._serialize_item(item) for item in response.get("Items", [])]

            # Apply status filter
            if status_filter:
                if status_filter == "active":
                    items = [i for i in items if i.get("is_active", False)]
                elif status_filter == "revoked":
                    items = [i for i in items if not i.get("is_active", False)]

            result = {"items": items}
            if "LastEvaluatedKey" in response:
                result["last_key"] = response["LastEvaluatedKey"]
            return result
        except Exception as e:
            print(f"[APIKeyManager] Error listing keys: {e}")
            return {"items": []}

    def update_api_key(self, api_key: str, **kwargs) -> bool:
        """Update fields on an API key."""
        try:
            update_parts = []
            expr_names = {}
            expr_values = {}

            for key, value in kwargs.items():
                attr_name = f"#{key}"
                attr_value = f":{key}"
                update_parts.append(f"{attr_name} = {attr_value}")
                expr_names[attr_name] = key
                if isinstance(value, float):
                    expr_values[attr_value] = Decimal(str(value))
                else:
                    expr_values[attr_value] = value

            # Always update updated_at
            update_parts.append("#updated_at = :updated_at")
            expr_names["#updated_at"] = "updated_at"
            expr_values[":updated_at"] = int(time.time())

            self.table.update_item(
                Key={"api_key": api_key},
                UpdateExpression="SET " + ", ".join(update_parts),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
            return True
        except Exception as e:
            print(f"[APIKeyManager] Error updating key: {e}")
            return False

    def deactivate_api_key(self, api_key: str) -> bool:
        """Deactivate (revoke) an API key."""
        return self.update_api_key(api_key, is_active=False, deactivated_reason="manual")

    def reactivate_api_key(self, api_key: str) -> bool:
        """Reactivate a revoked API key."""
        try:
            self.table.update_item(
                Key={"api_key": api_key},
                UpdateExpression="SET #active = :active, #updated = :updated REMOVE #reason",
                ExpressionAttributeNames={
                    "#active": "is_active",
                    "#updated": "updated_at",
                    "#reason": "deactivated_reason",
                },
                ExpressionAttributeValues={
                    ":active": True,
                    ":updated": int(time.time()),
                },
            )
            return True
        except Exception as e:
            print(f"[APIKeyManager] Error reactivating key: {e}")
            return False

    def delete_api_key(self, api_key: str) -> bool:
        """Permanently delete an API key."""
        try:
            self.table.delete_item(Key={"api_key": api_key})
            return True
        except Exception as e:
            print(f"[APIKeyManager] Error deleting key: {e}")
            return False

    def deactivate_for_budget_exceeded(self, api_key: str) -> bool:
        """Deactivate an API key because budget was exceeded."""
        return self.update_api_key(api_key, is_active=False, deactivated_reason="budget_exceeded")

    def _serialize_item(self, item: Dict) -> Dict[str, Any]:
        """Convert DynamoDB item (boto3 resource format) to plain dict."""
        result = {}
        for key, value in item.items():
            if isinstance(value, Decimal):
                # Convert Decimal to int or float
                if value == int(value):
                    result[key] = int(value)
                else:
                    result[key] = float(value)
            else:
                result[key] = value
        return result


class UsageTracker:
    """Track API usage in DynamoDB."""

    def __init__(self, dynamodb_client: DynamoDBClient):
        self.client = dynamodb_client.client
        self.resource = dynamodb_client.resource
        self.table_name = settings.dynamodb_usage_table
        self.table = self.resource.Table(self.table_name)

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
        cached_tokens: int = 0,
        cache_write_tokens: int = 0,
    ):
        """Record API usage."""
        try:
            timestamp = int(time.time() * 1000)
            item = {
                "api_key": api_key,
                "timestamp": timestamp,
                "request_id": request_id,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "cached_tokens": cached_tokens,
                "cache_write_tokens": cache_write_tokens,
                "success": success,
            }

            if error_message:
                item["error_message"] = error_message
            if latency_ms:
                item["latency_ms"] = latency_ms

            self.table.put_item(Item=item)
        except Exception:
            pass  # Don't fail request on usage tracking error

    def get_usage_stats(self, api_key: str, days: int = 30) -> Dict[str, Any]:
        """Get usage statistics for an API key from the usage table."""
        try:
            # Calculate timestamp for N days ago
            cutoff = int((time.time() - days * 86400) * 1000)

            response = self.table.query(
                KeyConditionExpression=Key("api_key").eq(api_key) & Key("timestamp").gte(cutoff),
            )

            items = response.get("Items", [])
            total_input = sum(int(i.get("prompt_tokens", 0)) for i in items)
            total_output = sum(int(i.get("completion_tokens", 0)) for i in items)
            total_cached = sum(int(i.get("cached_tokens", 0)) for i in items)
            total_cache_write = sum(int(i.get("cache_write_tokens", 0)) for i in items)
            total_requests = len(items)
            successful = sum(1 for i in items if i.get("success", True))

            # Group by model
            model_usage = {}
            for item in items:
                model = item.get("model", "unknown")
                if model not in model_usage:
                    model_usage[model] = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
                model_usage[model]["requests"] += 1
                model_usage[model]["input_tokens"] += int(item.get("prompt_tokens", 0))
                model_usage[model]["output_tokens"] += int(item.get("completion_tokens", 0))

            return {
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_cached_tokens": total_cached,
                "total_cache_write_tokens": total_cache_write,
                "total_requests": total_requests,
                "successful_requests": successful,
                "failed_requests": total_requests - successful,
                "model_usage": model_usage,
                "period_days": days,
            }
        except Exception as e:
            print(f"[UsageTracker] Error getting stats: {e}")
            return {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cached_tokens": 0,
                "total_cache_write_tokens": 0,
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "model_usage": {},
                "period_days": days,
            }


class ModelMappingManager:
    """Manage model ID mappings in DynamoDB."""

    def __init__(self, dynamodb_client: DynamoDBClient):
        self.client = dynamodb_client.client
        self.resource = dynamodb_client.resource
        self.table_name = settings.dynamodb_model_mapping_table
        self.table = self.resource.Table(self.table_name)

    def get_mapping(self, openai_model_id: str) -> Optional[str]:
        """Get Bedrock model ID for OpenAI/Anthropic model ID."""
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
                "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
            },
        )

    def list_mappings(self) -> List[Dict[str, str]]:
        """List all model mappings. Returns anthropic_model_id for admin portal compatibility."""
        try:
            response = self.client.scan(TableName=self.table_name)
            mappings = []
            for item in response.get("Items", []):
                openai_id = item.get("openai_model_id", {}).get("S", "")
                bedrock_id = item.get("bedrock_model_id", {}).get("S", "")
                updated_at = item.get("updated_at", {}).get("S")
                mappings.append({
                    "openai_model_id": openai_id,
                    "anthropic_model_id": openai_id,  # Alias for admin portal
                    "bedrock_model_id": bedrock_id,
                    "updated_at": updated_at,
                })
            return mappings
        except Exception:
            return []

    def delete_mapping(self, openai_model_id: str) -> bool:
        """Delete a model mapping."""
        try:
            self.client.delete_item(
                TableName=self.table_name,
                Key={"openai_model_id": {"S": openai_model_id}},
            )
            return True
        except Exception as e:
            print(f"[ModelMappingManager] Error deleting mapping: {e}")
            return False


class ModelPricingManager:
    """Manage model pricing in DynamoDB."""

    def __init__(self, dynamodb_client: DynamoDBClient):
        self.client = dynamodb_client.client
        self.resource = dynamodb_client.resource
        self.table_name = settings.dynamodb_pricing_table
        self.table = self.resource.Table(self.table_name)

    def get_pricing(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get pricing for a specific model."""
        try:
            response = self.table.get_item(Key={"model_id": model_id})
            item = response.get("Item")
            if not item:
                return None
            return self._serialize_item(item)
        except Exception as e:
            print(f"[ModelPricingManager] Error getting pricing: {e}")
            return None

    def create_pricing(
        self,
        model_id: str,
        provider: str,
        display_name: Optional[str] = None,
        input_price: float = 0,
        output_price: float = 0,
        cache_read_price: Optional[float] = None,
        cache_write_price: Optional[float] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        """Create a new model pricing entry."""
        now = int(time.time())
        item = {
            "model_id": model_id,
            "provider": provider,
            "input_price": Decimal(str(input_price)),
            "output_price": Decimal(str(output_price)),
            "status": status,
            "created_at": now,
            "updated_at": now,
        }
        if display_name:
            item["display_name"] = display_name
        if cache_read_price is not None:
            item["cache_read_price"] = Decimal(str(cache_read_price))
        if cache_write_price is not None:
            item["cache_write_price"] = Decimal(str(cache_write_price))

        self.table.put_item(Item=item)
        return self._serialize_item(item)

    def update_pricing(self, model_id: str, **kwargs) -> bool:
        """Update pricing fields."""
        try:
            update_parts = []
            expr_names = {}
            expr_values = {}

            for key, value in kwargs.items():
                attr_name = f"#{key}"
                attr_value = f":{key}"
                update_parts.append(f"{attr_name} = {attr_value}")
                expr_names[attr_name] = key
                if isinstance(value, float):
                    expr_values[attr_value] = Decimal(str(value))
                else:
                    expr_values[attr_value] = value

            update_parts.append("#updated_at = :updated_at")
            expr_names["#updated_at"] = "updated_at"
            expr_values[":updated_at"] = int(time.time())

            self.table.update_item(
                Key={"model_id": model_id},
                UpdateExpression="SET " + ", ".join(update_parts),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
            return True
        except Exception as e:
            print(f"[ModelPricingManager] Error updating pricing: {e}")
            return False

    def delete_pricing(self, model_id: str) -> bool:
        """Delete a model pricing entry."""
        try:
            self.table.delete_item(Key={"model_id": model_id})
            return True
        except Exception as e:
            print(f"[ModelPricingManager] Error deleting pricing: {e}")
            return False

    def list_all_pricing(
        self,
        limit: int = 100,
        provider_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        last_key: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """List all model pricing entries."""
        try:
            scan_kwargs = {"Limit": limit}
            if last_key:
                scan_kwargs["ExclusiveStartKey"] = last_key

            response = self.table.scan(**scan_kwargs)
            items = [self._serialize_item(item) for item in response.get("Items", [])]

            if provider_filter:
                items = [i for i in items if i.get("provider", "").lower() == provider_filter.lower()]
            if status_filter:
                items = [i for i in items if i.get("status", "") == status_filter]

            result = {"items": items}
            if "LastEvaluatedKey" in response:
                result["last_key"] = response["LastEvaluatedKey"]
            return result
        except Exception as e:
            print(f"[ModelPricingManager] Error listing pricing: {e}")
            return {"items": []}

    def get_price_for_model(self, model_id: str) -> Optional[Dict[str, float]]:
        """Get input/output prices for cost calculation."""
        pricing = self.get_pricing(model_id)
        if not pricing:
            return None
        return {
            "input_price": float(pricing.get("input_price", 0)),
            "output_price": float(pricing.get("output_price", 0)),
            "cache_read_price": float(pricing.get("cache_read_price", 0) or 0),
            "cache_write_price": float(pricing.get("cache_write_price", 0) or 0),
        }

    def _serialize_item(self, item: Dict) -> Dict[str, Any]:
        """Convert DynamoDB item to plain dict."""
        result = {}
        for key, value in item.items():
            if isinstance(value, Decimal):
                if value == int(value):
                    result[key] = int(value)
                else:
                    result[key] = float(value)
            else:
                result[key] = value
        return result


class UsageStatsManager:
    """Manage aggregated usage statistics in DynamoDB."""

    def __init__(self, dynamodb_client: DynamoDBClient):
        self.client = dynamodb_client.client
        self.resource = dynamodb_client.resource
        self.table_name = settings.dynamodb_usage_stats_table
        self.table = self.resource.Table(self.table_name)

    def get_stats(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Get aggregated usage stats for an API key."""
        try:
            response = self.table.get_item(Key={"api_key": api_key})
            item = response.get("Item")
            if not item:
                return None
            return self._serialize_item(item)
        except Exception as e:
            print(f"[UsageStatsManager] Error getting stats: {e}")
            return None

    def update_stats(
        self,
        api_key: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        cache_write_tokens: int = 0,
        requests: int = 0,
        cost: float = 0,
    ) -> bool:
        """Update (increment) aggregated stats for an API key."""
        try:
            self.table.update_item(
                Key={"api_key": api_key},
                UpdateExpression=(
                    "ADD #input :input, #output :output, #cached :cached, "
                    "#cache_write :cache_write, #requests :requests, #cost :cost "
                    "SET #updated = :updated"
                ),
                ExpressionAttributeNames={
                    "#input": "total_input_tokens",
                    "#output": "total_output_tokens",
                    "#cached": "total_cached_tokens",
                    "#cache_write": "total_cache_write_tokens",
                    "#requests": "total_requests",
                    "#cost": "total_cost",
                    "#updated": "updated_at",
                },
                ExpressionAttributeValues={
                    ":input": input_tokens,
                    ":output": output_tokens,
                    ":cached": cached_tokens,
                    ":cache_write": cache_write_tokens,
                    ":requests": requests,
                    ":cost": Decimal(str(cost)),
                    ":updated": int(time.time()),
                },
            )
            return True
        except Exception as e:
            print(f"[UsageStatsManager] Error updating stats: {e}")
            return False

    def aggregate_all_usage(
        self,
        api_keys: List[str],
        pricing_manager: Optional["ModelPricingManager"] = None,
        api_key_manager: Optional["APIKeyManager"] = None,
    ) -> int:
        """
        Aggregate usage from the usage table into usage_stats for all given API keys.
        Also updates budget_used on the API key if pricing is available.

        Returns the number of keys processed.
        """
        usage_table_name = settings.dynamodb_usage_table
        usage_table = self.resource.Table(usage_table_name)
        count = 0

        for api_key in api_keys:
            try:
                # Get current stats to find last aggregation timestamp
                current_stats = self.get_stats(api_key)
                last_aggregated = int(current_stats.get("last_aggregated_timestamp", 0)) if current_stats else 0

                # Query usage records after last aggregation
                query_kwargs = {
                    "KeyConditionExpression": Key("api_key").eq(api_key),
                }
                if last_aggregated > 0:
                    query_kwargs["KeyConditionExpression"] = (
                        Key("api_key").eq(api_key) & Key("timestamp").gt(last_aggregated)
                    )

                response = usage_table.query(**query_kwargs)
                items = response.get("Items", [])

                # Handle pagination
                while "LastEvaluatedKey" in response:
                    query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                    response = usage_table.query(**query_kwargs)
                    items.extend(response.get("Items", []))

                if not items:
                    count += 1
                    continue

                # Aggregate tokens
                total_input = sum(int(i.get("prompt_tokens", 0)) for i in items)
                total_output = sum(int(i.get("completion_tokens", 0)) for i in items)
                total_cached = sum(int(i.get("cached_tokens", 0)) for i in items)
                total_cache_write = sum(int(i.get("cache_write_tokens", 0)) for i in items)
                total_requests = len(items)

                # Calculate cost if pricing manager is available
                total_cost = Decimal("0")
                if pricing_manager:
                    for item in items:
                        model = item.get("model", "")
                        prices = pricing_manager.get_price_for_model(model)
                        if prices:
                            input_cost = Decimal(str(int(item.get("prompt_tokens", 0)))) * Decimal(str(prices["input_price"])) / Decimal("1000000")
                            output_cost = Decimal(str(int(item.get("completion_tokens", 0)))) * Decimal(str(prices["output_price"])) / Decimal("1000000")
                            cache_read_cost = Decimal(str(int(item.get("cached_tokens", 0)))) * Decimal(str(prices["cache_read_price"])) / Decimal("1000000")
                            cache_write_cost = Decimal(str(int(item.get("cache_write_tokens", 0)))) * Decimal(str(prices["cache_write_price"])) / Decimal("1000000")
                            total_cost += input_cost + output_cost + cache_read_cost + cache_write_cost

                # Find max timestamp for last_aggregated_timestamp
                max_timestamp = max(int(i.get("timestamp", 0)) for i in items)

                # Update aggregated stats
                self.table.update_item(
                    Key={"api_key": api_key},
                    UpdateExpression=(
                        "ADD #input :input, #output :output, #cached :cached, "
                        "#cache_write :cache_write, #requests :requests, #cost :cost "
                        "SET #updated = :updated, #last_ts = :last_ts"
                    ),
                    ExpressionAttributeNames={
                        "#input": "total_input_tokens",
                        "#output": "total_output_tokens",
                        "#cached": "total_cached_tokens",
                        "#cache_write": "total_cache_write_tokens",
                        "#requests": "total_requests",
                        "#cost": "total_cost",
                        "#updated": "updated_at",
                        "#last_ts": "last_aggregated_timestamp",
                    },
                    ExpressionAttributeValues={
                        ":input": total_input,
                        ":output": total_output,
                        ":cached": total_cached,
                        ":cache_write": total_cache_write,
                        ":requests": total_requests,
                        ":cost": total_cost,
                        ":updated": int(time.time()),
                        ":last_ts": max_timestamp,
                    },
                )

                # Update budget_used on the API key
                if api_key_manager and total_cost > 0:
                    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                    key_info = api_key_manager.get_api_key(api_key)
                    if key_info:
                        old_budget_used = Decimal(str(key_info.get("budget_used", 0) or 0))
                        new_budget_used = old_budget_used + total_cost

                        # Handle MTD budget
                        old_mtd_month = key_info.get("budget_mtd_month", "")
                        if old_mtd_month == current_month:
                            old_mtd = Decimal(str(key_info.get("budget_used_mtd", 0) or 0))
                            new_mtd = old_mtd + total_cost
                        else:
                            new_mtd = total_cost

                        api_key_manager.table.update_item(
                            Key={"api_key": api_key},
                            UpdateExpression="SET #bu = :bu, #mtd = :mtd, #mm = :mm",
                            ExpressionAttributeNames={
                                "#bu": "budget_used",
                                "#mtd": "budget_used_mtd",
                                "#mm": "budget_mtd_month",
                            },
                            ExpressionAttributeValues={
                                ":bu": new_budget_used,
                                ":mtd": new_mtd,
                                ":mm": current_month,
                            },
                        )

                        # Check if budget exceeded
                        monthly_budget = Decimal(str(key_info.get("monthly_budget", 0) or 0))
                        if monthly_budget > 0 and new_mtd >= monthly_budget and key_info.get("is_active", False):
                            api_key_manager.deactivate_for_budget_exceeded(api_key)

                count += 1
            except Exception as e:
                print(f"[UsageStatsManager] Error aggregating for {api_key}: {e}")

        return count

    def _serialize_item(self, item: Dict) -> Dict[str, Any]:
        """Convert DynamoDB item to plain dict."""
        result = {}
        for key, value in item.items():
            if isinstance(value, Decimal):
                if value == int(value):
                    result[key] = int(value)
                else:
                    result[key] = float(value)
            else:
                result[key] = value
        return result
