"""Seed default model pricing into DynamoDB.

Usage:
    # Local DynamoDB
    python scripts/seed_pricing.py

    # Custom endpoint
    DYNAMODB_ENDPOINT_URL=http://localhost:8001 python scripts/seed_pricing.py

    # Production (uses IAM role)
    AWS_REGION=us-west-2 python scripts/seed_pricing.py --no-endpoint
"""
import argparse
import os
import time
from decimal import Decimal

import boto3

# Default pricing per 1M tokens (USD) - Bedrock Anthropic Claude models
# Source: https://aws.amazon.com/bedrock/pricing/
#
# cache_write_5m_price: 5 分钟 TTL 的 Cache Write 价格
# cache_write_1h_price: 1 小时 TTL 的 Cache Write 价格
# cache_read_price:     Cache Read（命中 & 续期）价格
DEFAULT_PRICING = [
    {
        "model_id": "claude-opus-4-6",
        "provider": "Anthropic",
        "display_name": "Claude Opus 4.6",
        "input_price": 5.0,
        "output_price": 25.0,
        "cache_read_price": 0.50,
        "cache_write_5m_price": 6.25,
        "cache_write_1h_price": 10.0,
    },
    {
        "model_id": "claude-opus-4-5",
        "provider": "Anthropic",
        "display_name": "Claude Opus 4.5",
        "input_price": 5.0,
        "output_price": 25.0,
        "cache_read_price": 0.50,
        "cache_write_5m_price": 6.25,
        "cache_write_1h_price": 10.0,
    },
    {
        "model_id": "claude-sonnet-4-6",
        "provider": "Anthropic",
        "display_name": "Claude Sonnet 4.6",
        "input_price": 3.0,
        "output_price": 15.0,
        "cache_read_price": 0.30,
        "cache_write_5m_price": 3.75,
        "cache_write_1h_price": 6.0,
    },
    {
        "model_id": "claude-sonnet-4-5",
        "provider": "Anthropic",
        "display_name": "Claude Sonnet 4.5",
        "input_price": 3.0,
        "output_price": 15.0,
        "cache_read_price": 0.30,
        "cache_write_5m_price": 3.75,
        "cache_write_1h_price": 6.0,
    },
    {
        "model_id": "claude-haiku-4-5",
        "provider": "Anthropic",
        "display_name": "Claude Haiku 4.5",
        "input_price": 0.80,
        "output_price": 4.0,
        "cache_read_price": 0.08,
        "cache_write_5m_price": 1.0,
        "cache_write_1h_price": None,  # 待确认
    },
    {
        "model_id": "claude-3-5-haiku",
        "provider": "Anthropic",
        "display_name": "Claude 3.5 Haiku",
        "input_price": 0.80,
        "output_price": 4.0,
        "cache_read_price": None,       # 不支持 prompt caching
        "cache_write_5m_price": None,
        "cache_write_1h_price": None,
    },
]


def seed_pricing(endpoint_url=None, table_name="openai-proxy-pricing", force=False):
    region = os.environ.get("AWS_REGION", "us-west-2")

    client_kwargs = {
        "service_name": "dynamodb",
        "region_name": region,
    }
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url
        client_kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "local")
        client_kwargs["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "local")

    resource = boto3.resource(**client_kwargs)
    table = resource.Table(table_name)

    now = int(time.time())
    created = 0
    skipped = 0

    for model in DEFAULT_PRICING:
        model_id = model["model_id"]
        try:
            existing = table.get_item(Key={"model_id": model_id}).get("Item")
            if existing and not force:
                print(f"  SKIP  {model_id} (already exists)")
                skipped += 1
                continue
        except Exception:
            pass

        item = {
            "model_id": model_id,
            "provider": model["provider"],
            "display_name": model["display_name"],
            "input_price": Decimal(str(model["input_price"])),
            "output_price": Decimal(str(model["output_price"])),
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }

        # Cache pricing fields
        for field in ("cache_read_price", "cache_write_5m_price", "cache_write_1h_price"):
            if model.get(field) is not None:
                item[field] = Decimal(str(model[field]))

        table.put_item(Item=item)
        cache_info = ""
        if model.get("cache_write_5m_price"):
            cache_info = f"  cache: read=${model['cache_read_price']} write_5m=${model['cache_write_5m_price']}"
            if model.get("cache_write_1h_price"):
                cache_info += f" write_1h=${model['cache_write_1h_price']}"
        print(f"  ADD   {model_id}  in=${model['input_price']} out=${model['output_price']}{cache_info}")
        created += 1

    print(f"\nDone: {created} created, {skipped} skipped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed default model pricing")
    parser.add_argument("--force", action="store_true", help="Overwrite existing pricing")
    parser.add_argument("--no-endpoint", action="store_true", help="Don't use local endpoint")
    parser.add_argument("--table", default="openai-proxy-pricing", help="DynamoDB table name")
    args = parser.parse_args()

    endpoint = None if args.no_endpoint else os.environ.get("DYNAMODB_ENDPOINT_URL", "http://localhost:8001")

    print(f"Seeding pricing to table: {args.table}")
    if endpoint:
        print(f"Endpoint: {endpoint}")
    seed_pricing(endpoint_url=endpoint, table_name=args.table, force=args.force)
