"""Create an API key."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.dynamodb import DynamoDBClient, APIKeyManager


def main():
    parser = argparse.ArgumentParser(description="Create an API key")
    parser.add_argument("--user-id", required=True, help="User ID")
    parser.add_argument("--name", required=True, help="Key name")
    parser.add_argument("--rate-limit", type=int, default=100, help="Rate limit per minute")
    args = parser.parse_args()

    client = DynamoDBClient()
    manager = APIKeyManager(client)

    api_key = manager.create_api_key(
        user_id=args.user_id,
        name=args.name,
        rate_limit=args.rate_limit,
    )

    print(f"Created API key:")
    print(f"  API Key: {api_key}")
    print(f"  User ID: {args.user_id}")
    print(f"  Name: {args.name}")
    print(f"  Rate Limit: {args.rate_limit}/min")


if __name__ == "__main__":
    main()
