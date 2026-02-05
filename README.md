# OpenAI API Convertor

OpenAI-compatible API proxy for AWS Bedrock Claude models. Use your existing OpenAI SDK code with AWS Bedrock.

## Quick Start

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://your-proxy.com/v1",
    api_key="your-api-key"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5-20250929",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

## Features

- ✅ OpenAI Chat Completions API compatible
- ✅ Streaming support
- ✅ Vision (image input)
- ✅ Tool/Function calling
- ✅ Extended thinking
- ✅ API key authentication
- ✅ Rate limiting
- ✅ Usage tracking

## Supported Models

| Model ID | Bedrock Model |
|----------|---------------|
| claude-opus-4-5-20251101 | global.anthropic.claude-opus-4-5-20251101-v1:0 |
| claude-sonnet-4-5-20250929 | global.anthropic.claude-sonnet-4-5-20250929-v1:0 |
| claude-haiku-4-5-20251001 | global.anthropic.claude-haiku-4-5-20251001-v1:0 |
| claude-3-5-haiku-20241022 | us.anthropic.claude-3-5-haiku-20241022-v1:0 |

## Local Development

### Option 1: Direct Run

```bash
# Install
pip install -e .

# Configure
cp env.example .env
# Edit .env with your AWS credentials

# Run
uvicorn app.main:app --reload --port 8000
```

### Option 2: Docker Compose

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop
docker-compose down
```

Services:
- API: http://localhost:8000
- DynamoDB Admin: http://localhost:8002

### Test

```bash
# Health check
curl http://localhost:8000/health

# Chat completion
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Deploy to AWS

```bash
cd cdk
npm install

# Dev environment
./scripts/deploy.sh -e dev -p arm64

# Prod environment
./scripts/deploy.sh -e prod -p arm64
```

## API Reference

### POST /v1/chat/completions

OpenAI-compatible chat completion endpoint.

### GET /v1/models

List available models.

### GET /health

Health check endpoint.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| AWS_REGION | us-west-2 | AWS region |
| REQUIRE_API_KEY | true | Require API key authentication |
| MASTER_API_KEY | - | Master API key for admin access |
| RATE_LIMIT_ENABLED | true | Enable rate limiting |
| RATE_LIMIT_REQUESTS | 100 | Requests per window |
| RATE_LIMIT_WINDOW | 60 | Window in seconds |

## License

MIT
