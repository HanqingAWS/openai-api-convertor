"""Setup DynamoDB tables for local development."""
import os
import boto3


def create_tables():
    endpoint_url = os.environ.get("DYNAMODB_ENDPOINT_URL", "http://localhost:8001")
    region = os.environ.get("AWS_REGION", "us-west-2")

    client = boto3.client(
        "dynamodb",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "local"),
    )

    tables = [
        {
            "TableName": "openai-proxy-api-keys",
            "KeySchema": [{"AttributeName": "api_key", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "api_key", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "user_id-index",
                    "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": "openai-proxy-usage",
            "KeySchema": [
                {"AttributeName": "api_key", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "api_key", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "N"},
                {"AttributeName": "request_id", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "request_id-index",
                    "KeySchema": [{"AttributeName": "request_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": "openai-proxy-model-mapping",
            "KeySchema": [{"AttributeName": "openai_model_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "openai_model_id", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": "openai-proxy-pricing",
            "KeySchema": [{"AttributeName": "model_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "model_id", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": "openai-proxy-usage-stats",
            "KeySchema": [{"AttributeName": "api_key", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "api_key", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
    ]

    for table_def in tables:
        table_name = table_def["TableName"]
        try:
            # Check if table exists
            client.describe_table(TableName=table_name)
            print(f"Table {table_name} already exists")
        except client.exceptions.ResourceNotFoundException:
            # Create table
            client.create_table(**table_def)
            print(f"Created table {table_name}")

    print("All tables ready!")


if __name__ == "__main__":
    create_tables()
