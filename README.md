# OpenAI API Convertor

OpenAI-compatible API proxy for AWS Bedrock Claude models.

## Features

- OpenAI v1 compatible API (`/v1/chat/completions`, `/v1/models`)
- Support Claude models on Bedrock (Opus 4.5, Sonnet 4.5, Haiku 4.5, Claude 3.5 Haiku)
- Streaming support
- Vision (image input)
- Tool/Function calling
- Extended thinking
- API key authentication & rate limiting
- Usage tracking with DynamoDB
- Admin Portal for management

## Quick Start (Local Docker)

```bash
# Start services
docker-compose up -d

# Check logs
docker-compose logs -f api

# Test API
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
```

## API Usage

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="test-key"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

## Model Mapping

| OpenAI Model ID | Bedrock Model ID |
|-----------------|------------------|
| claude-opus-4-5 | anthropic.claude-opus-4-5-20251101-v1:0 |
| claude-sonnet-4-5 | anthropic.claude-sonnet-4-5-20250929-v1:0 |
| claude-haiku-4-5 | anthropic.claude-haiku-4-5-20251001-v1:0 |
| claude-3-5-haiku | anthropic.claude-3-5-haiku-20241022-v1:0 |

## Deployment

See `cdk/` for AWS ECS deployment with CDK.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| AWS_REGION | AWS region | us-west-2 |
| REQUIRE_API_KEY | Enable API key auth | false |
| MASTER_API_KEY | Master API key | - |
| RATE_LIMIT_ENABLED | Enable rate limiting | false |

## License

MIT
