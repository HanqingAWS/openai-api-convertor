# OpenAI API Convertor - 需求文档

## 项目概述

OpenAI API Convertor 是一个 API 代理服务，让使用 OpenAI SDK 的应用程序可以通过修改 `base_url` 和 `api_key` 直接访问 AWS Bedrock 上的 Claude 模型。

### 使用场景

```python
from openai import OpenAI

# 原本连接 OpenAI
# client = OpenAI(api_key="sk-xxx")

# 改为连接 Bedrock Proxy
client = OpenAI(
    base_url="https://your-proxy.com/v1",
    api_key="your-proxy-api-key"
)

# 代码无需任何其他修改
response = client.chat.completions.create(
    model="claude-sonnet-4-5-20250929",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

---

## 功能需求

### 1. API 兼容性

#### 1.1 Chat Completions API

**端点**: `POST /v1/chat/completions`

**必须支持的参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| model | string | 模型 ID |
| messages | array | 消息列表 |
| stream | boolean | 是否流式响应 |
| max_tokens | integer | 最大输出 token |
| temperature | float | 温度 (0-2) |
| top_p | float | Top-p 采样 |
| stop | string/array | 停止序列 |
| tools | array | 工具定义 (function calling) |
| tool_choice | string/object | 工具选择策略 |

**消息格式支持**:
- `role`: system, user, assistant, tool
- `content`: 支持 string 和 array 格式
- 图片输入 (Vision): `{"type": "image_url", "image_url": {"url": "data:image/..."}}`

**响应格式**:
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "claude-sonnet-4-5-20250929",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Hello!"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  }
}
```

**流式响应格式** (SSE):
```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"}}]}

data: [DONE]
```

#### 1.2 Models API

**端点**: `GET /v1/models`

**响应**:
```json
{
  "object": "list",
  "data": [
    {
      "id": "claude-sonnet-4-5-20250929",
      "object": "model",
      "created": 1234567890,
      "owned_by": "anthropic"
    }
  ]
}
```

#### 1.3 Health Check

**端点**: 
- `GET /health` - 健康检查
- `GET /ready` - 就绪检查

---

### 2. 模型映射

#### 2.1 默认映射

| OpenAI 模型 ID | Bedrock 模型 ID |
|----------------|-----------------|
| claude-opus-4-5-20251101 | global.anthropic.claude-opus-4-5-20251101-v1:0 |
| claude-sonnet-4-5-20250929 | global.anthropic.claude-sonnet-4-5-20250929-v1:0 |
| claude-haiku-4-5-20251001 | global.anthropic.claude-haiku-4-5-20251001-v1:0 |
| claude-3-5-haiku-20241022 | us.anthropic.claude-3-5-haiku-20241022-v1:0 |

#### 2.2 映射优先级

1. DynamoDB 自定义映射（最高优先级）
2. 默认配置映射
3. 直接透传（假设是有效的 Bedrock 模型 ID）

---

### 3. Vision 支持

支持 OpenAI Vision API 格式的图片输入：

```python
response = client.chat.completions.create(
    model="claude-sonnet-4-5-20250929",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "What's in this image?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]
    }]
)
```

**支持的图片格式**:
- image/jpeg
- image/png
- image/gif
- image/webp

**支持的输入方式**:
- Base64 data URL: `data:image/png;base64,...`
- HTTP URL: `https://example.com/image.png` (需要下载转换)

---

### 4. Tool/Function Calling 支持

支持 OpenAI 格式的 function calling：

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string"}
            },
            "required": ["location"]
        }
    }
}]

response = client.chat.completions.create(
    model="claude-sonnet-4-5-20250929",
    messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
    tools=tools,
    tool_choice="auto"
)
```

**Tool 响应格式**:
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "id": "call_xxx",
        "type": "function",
        "function": {
          "name": "get_weather",
          "arguments": "{\"location\": \"Tokyo\"}"
        }
      }]
    },
    "finish_reason": "tool_calls"
  }]
}
```

---

### 5. Extended Thinking 支持

通过自定义参数支持 Claude 的 Extended Thinking：

```python
response = client.chat.completions.create(
    model="claude-sonnet-4-5-20250929",
    messages=[{"role": "user", "content": "Solve this complex problem..."}],
    extra_body={
        "thinking": {
            "type": "enabled",
            "budget_tokens": 10000
        }
    }
)
```

**响应中包含思考过程**:
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "Final answer...",
      "thinking": "Step by step reasoning..."
    }
  }]
}
```

---

### 6. 认证与授权

#### 6.1 API Key 认证

- Header: `Authorization: Bearer <api-key>` 或 `x-api-key: <api-key>`
- API Key 存储在 DynamoDB
- 支持 Master API Key（管理员）

#### 6.2 API Key 属性

| 字段 | 类型 | 说明 |
|------|------|------|
| api_key | string | API Key (主键) |
| user_id | string | 用户 ID |
| name | string | Key 名称 |
| is_active | boolean | 是否启用 |
| rate_limit | number | 每分钟请求限制 |
| created_at | string | 创建时间 |
| metadata | object | 自定义元数据 |

---

### 7. 限流

- 基于 Token Bucket 算法
- 每 API Key 独立限流
- 返回标准限流 Header:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`
- 超限返回 429 状态码

---

### 8. 使用量追踪

记录每次请求的使用情况：

| 字段 | 说明 |
|------|------|
| api_key | API Key |
| timestamp | 请求时间 |
| request_id | 请求 ID |
| model | 使用的模型 |
| prompt_tokens | 输入 token 数 |
| completion_tokens | 输出 token 数 |
| total_tokens | 总 token 数 |
| success | 是否成功 |
| error_message | 错误信息 |
| latency_ms | 响应延迟 |

---

### 9. Admin Portal (管理后台)

#### 9.1 功能模块

**Dashboard**:
- 总请求数统计
- Token 使用量统计
- 成功/失败率
- 按模型分布
- 按时间趋势图

**API Key 管理**:
- 创建/删除 API Key
- 启用/禁用 API Key
- 设置限流配置
- 查看使用历史

**模型定价管理**:
- 设置各模型的 input/output token 单价
- 计算成本统计

**用户认证**:
- Cognito 集成
- 登录/登出

#### 9.2 技术栈

- Frontend: React + TypeScript + Tailwind CSS
- Backend: FastAPI (与主服务共用)
- 认证: AWS Cognito

---

## 技术架构

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Load Balancer                │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│   API Proxy Service     │     │   Admin Portal Service  │
│   (ECS Fargate/EC2)     │     │   (ECS Fargate)         │
│                         │     │                         │
│  /v1/chat/completions   │     │  /admin/*               │
│  /v1/models             │     │  /api/*                 │
│  /health                │     │                         │
└─────────────────────────┘     └─────────────────────────┘
              │                               │
              └───────────────┬───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        AWS Services                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Bedrock    │  │  DynamoDB   │  │  Cognito            │  │
│  │  Runtime    │  │  Tables     │  │  (Admin Auth)       │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 数据流

```
OpenAI SDK Request
       │
       ▼
┌──────────────────┐
│ Auth Middleware  │ ──→ DynamoDB (API Keys)
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ Rate Limiter     │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ OpenAI → Bedrock │
│ Converter        │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ Bedrock Service  │ ──→ AWS Bedrock
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ Bedrock → OpenAI │
│ Converter        │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ Usage Tracker    │ ──→ DynamoDB (Usage)
└──────────────────┘
       │
       ▼
OpenAI SDK Response
```

### DynamoDB 表设计

**1. API Keys Table** (`openai-proxy-api-keys`)
- PK: `api_key`
- GSI: `user_id-index`

**2. Usage Table** (`openai-proxy-usage`)
- PK: `api_key`
- SK: `timestamp`
- GSI: `request_id-index`

**3. Model Mapping Table** (`openai-proxy-model-mapping`)
- PK: `openai_model_id`

**4. Model Pricing Table** (`openai-proxy-model-pricing`)
- PK: `model_id`

**5. Usage Stats Table** (`openai-proxy-usage-stats`)
- PK: `api_key`
- SK: `date`

---

## 项目结构

```
openai-api-convertor/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 入口
│   ├── api/
│   │   ├── __init__.py
│   │   ├── chat.py                # /v1/chat/completions
│   │   ├── models.py              # /v1/models
│   │   └── health.py              # /health
│   ├── converters/
│   │   ├── __init__.py
│   │   ├── openai_to_bedrock.py   # OpenAI → Bedrock 转换
│   │   └── bedrock_to_openai.py   # Bedrock → OpenAI 转换
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # 配置管理
│   │   ├── exceptions.py          # 异常定义
│   │   └── logging.py             # 日志配置
│   ├── db/
│   │   ├── __init__.py
│   │   └── dynamodb.py            # DynamoDB 操作
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py                # 认证中间件
│   │   └── rate_limit.py          # 限流中间件
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── openai.py              # OpenAI API 模型
│   │   └── bedrock.py             # Bedrock API 模型
│   └── services/
│       ├── __init__.py
│       └── bedrock_service.py     # Bedrock 调用服务
├── admin_portal/
│   ├── backend/
│   │   ├── api/
│   │   ├── middleware/
│   │   └── main.py
│   └── frontend/
│       ├── src/
│       └── package.json
├── cdk/
│   ├── bin/
│   ├── lib/
│   │   ├── network-stack.ts
│   │   ├── dynamodb-stack.ts
│   │   ├── cognito-stack.ts
│   │   └── ecs-stack.ts
│   ├── config/
│   │   └── config.ts
│   └── package.json
├── scripts/
│   ├── create_api_key.py
│   ├── setup_tables.py
│   └── manage_model_mapping.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 部署配置

### 环境变量

```bash
# AWS
AWS_REGION=us-west-2

# DynamoDB Tables
DYNAMODB_API_KEYS_TABLE=openai-proxy-api-keys
DYNAMODB_USAGE_TABLE=openai-proxy-usage
DYNAMODB_MODEL_MAPPING_TABLE=openai-proxy-model-mapping

# Authentication
REQUIRE_API_KEY=true
MASTER_API_KEY=xxx

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# Features
ENABLE_VISION=true
ENABLE_TOOL_USE=true
ENABLE_EXTENDED_THINKING=true
```

### 本地开发与调试

#### 方式一：直接运行 (推荐开发时使用)

```bash
# 安装依赖
cd openai-api-convertor
pip install -e .

# 配置环境变量
cp env.example .env
# 编辑 .env 设置 AWS 凭证

# 启动服务
python -m uvicorn app.main:app --reload --port 8000
```

#### 方式二：Docker Compose (推荐集成测试)

```bash
cd openai-api-convertor

# 启动所有服务 (API + DynamoDB Local + Admin UI)
docker-compose up -d

# 查看日志
docker-compose logs -f api

# 停止服务
docker-compose down
```

**Docker Compose 包含**:
- API Proxy (port 8000)
- DynamoDB Local (port 8001)
- DynamoDB Admin UI (port 8002) - 可视化查看表数据

#### 方式三：单独 Docker 运行

```bash
# 构建镜像
docker build -t openai-api-convertor .

# 运行容器 (使用 AWS 凭证)
docker run -p 8000:8000 \
  -e AWS_REGION=us-west-2 \
  -e AWS_ACCESS_KEY_ID=xxx \
  -e AWS_SECRET_ACCESS_KEY=xxx \
  -e REQUIRE_API_KEY=false \
  openai-api-convertor
```

#### 本地测试

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="test-key"  # 本地可设置 REQUIRE_API_KEY=false 跳过认证
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5-20250929",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

#### 使用 curl 测试

```bash
# Non-streaming
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# Streaming
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'

# List models
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer test-key"

# Health check
curl http://localhost:8000/health
```

---

### CDK 部署 (生产环境)

```bash
# 开发环境
cd cdk
npm install
CDK_PLATFORM=arm64 CDK_LAUNCH_TYPE=fargate npx cdk deploy --all -c environment=dev

# 生产环境
CDK_PLATFORM=arm64 CDK_LAUNCH_TYPE=fargate npx cdk deploy --all -c environment=prod
```

---

## 错误处理

### OpenAI 兼容错误格式

```json
{
  "error": {
    "message": "Invalid API key",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_api_key"
  }
}
```

### 错误码映射

| HTTP Status | OpenAI Error Type | 说明 |
|-------------|-------------------|------|
| 400 | invalid_request_error | 请求格式错误 |
| 401 | authentication_error | 认证失败 |
| 403 | permission_error | 权限不足 |
| 404 | not_found_error | 资源不存在 |
| 429 | rate_limit_error | 限流 |
| 500 | server_error | 服务器错误 |
| 503 | service_unavailable | 服务不可用 |

---

## 开发里程碑

### Phase 1: 核心功能
- [ ] 项目初始化
- [ ] OpenAI Chat Completions API (non-streaming)
- [ ] OpenAI Chat Completions API (streaming)
- [ ] Models API
- [ ] 基础认证

### Phase 2: 高级功能
- [ ] Vision 支持
- [ ] Tool/Function Calling
- [ ] Extended Thinking
- [ ] 限流

### Phase 3: 运维功能
- [ ] 使用量追踪
- [ ] DynamoDB 模型映射
- [ ] CDK 部署

### Phase 4: Admin Portal
- [ ] Dashboard
- [ ] API Key 管理
- [ ] 定价管理
- [ ] Cognito 认证

---

## 参考资料

- [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
- [AWS Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)
- [Anthropic Claude on Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages.html)
