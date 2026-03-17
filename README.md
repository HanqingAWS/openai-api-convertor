# OpenAI API Convertor

OpenAI 兼容的 API 代理，将请求转发到 AWS Bedrock Claude 模型。使用 OpenAI SDK 即可调用 Bedrock 上的 Claude，无需修改业务代码。

## 功能特性

- OpenAI v1 兼容 API（`/v1/chat/completions`、`/v1/models`）
- 支持 Claude 模型：Opus 4.5/4.6、Sonnet 4.5/4.6、Haiku 4.5、Claude 3.5 Haiku
- 流式响应（Streaming SSE）
- 图片输入（Vision）
- 工具调用（Function Calling）
- 扩展思考（Extended Thinking）
- Prompt Caching（自动缓存 system prompt / 历史对话 / tools，支持 5m / 1h TTL）
- 结构化输出（Structured Output：`json_object` / `json_schema`）
- 流式用量统计（`stream_options.include_usage`）
- 推理力度控制（`reasoning_effort`：low / medium / high）
- API Key 认证 & 速率限制
- DynamoDB 使用量追踪 & 成本计算
- Admin Portal 管理后台（API Key 管理、模型定价、用量统计）

## 模型映射

| 模型 ID | Bedrock 模型 ID |
|---------|----------------|
| claude-opus-4-5 | global.anthropic.claude-opus-4-5-20251101-v1:0 |
| claude-opus-4-6 | global.anthropic.claude-opus-4-6-v1 |
| claude-sonnet-4-5 | global.anthropic.claude-sonnet-4-5-20250929-v1:0 |
| claude-sonnet-4-6 | global.anthropic.claude-sonnet-4-6 |
| claude-haiku-4-5 | global.anthropic.claude-haiku-4-5-20251001-v1:0 |
| claude-3-5-haiku | us.anthropic.claude-3-5-haiku-20241022-v1:0 |

### 添加新模型

通过 Admin Portal 添加自定义模型映射：

1. 打开 Admin Portal → **Model Mappings** 页面
2. 点击 **Add Mapping**
3. 填写 Anthropic Model ID（OpenAI SDK 使用的名称，如 `claude-sonnet-4-5`）和 Bedrock Model ID（如 `global.anthropic.claude-sonnet-4-5-20250929-v1:0`）
4. 保存后立即生效，无需重启服务
5. 如需计费，在 **Model Pricing** 页面配置对应模型的输入/输出/缓存价格

---

## CDK 部署（生产环境）

使用 AWS CDK 部署到 ECS Fargate，包含完整的 VPC、ALB、DynamoDB、ECS 服务。

### 架构

```
Internet → ALB (80/443)
              ├── /v1/*          → API Proxy Service (Fargate)
              ├── /health        → API Proxy Service (Fargate)
              ├── /admin/*       → Admin Portal Service (Fargate)
              └── /api/*         → Admin Portal API (Fargate)

DynamoDB Tables:
  ├── openai-proxy-api-keys-{env}       # API Key 管理
  ├── openai-proxy-usage-{env}          # 请求级用量记录
  ├── openai-proxy-model-mapping-{env}  # 自定义模型映射
  ├── openai-proxy-pricing-{env}        # 模型定价配置
  └── openai-proxy-usage-stats-{env}    # 聚合用量统计

CDK Stacks:
  ├── OpenAIProxy-Network-{env}     # VPC, Subnets, NAT Gateway, ALB, Security Groups
  ├── OpenAIProxy-DynamoDB-{env}    # DynamoDB Tables
  └── OpenAIProxy-ECS-{env}        # ECS Cluster, Fargate Services, Task Definitions
```

### 前置条件

- AWS CLI 已配置，具有 CloudFormation / ECS / ECR / DynamoDB / Secrets Manager 权限
- Node.js 18+ 和 npm
- Docker（用于构建容器镜像）
- CDK Bootstrap 已在目标 Region 执行

### 部署步骤

```bash
cd cdk
npm install

# 设置目标 Region（重要：必须与 Bedrock 可用区域一致）
export AWS_REGION=us-west-2

# Bootstrap（首次部署需要，每个 Region 只需执行一次）
CDK_PLATFORM=arm64 npx cdk bootstrap -c environment=prod

# 部署所有 Stacks
CDK_PLATFORM=arm64 npx cdk deploy --all -c environment=prod --require-approval never

# 仅更新 ECS 服务（代码变更后快速部署）
git fetch origin && git reset --hard origin/main
cd cdk
CDK_PLATFORM=arm64 npx cdk deploy OpenAIProxy-ECS-prod -c environment=prod --exclusively --require-approval never
```

`CDK_PLATFORM` 支持 `arm64`（Graviton，推荐，成本更低）和 `amd64`。

环境配置在 `cdk/config/config.ts` 中定义，包含 `dev` 和 `prod` 两套：

| 配置项 | dev | prod |
|--------|-----|------|
| ECS Tasks | 1 | 2 |
| CPU / Memory | 512 / 1024 | 1024 / 2048 |
| Auto Scaling | 1-2 | 2-10 |
| NAT Gateway | 1 | 1 |
| Log Retention | 7 天 | 30 天 |

### 部署后配置

```bash
# 获取 ALB 地址（从 CDK 输出）
ALB_DNS=<your-alb-dns-name>

# 获取 Master API Key（存储在 Secrets Manager）
aws secretsmanager get-secret-value \
  --secret-id openai-proxy-prod-master-api-key \
  --query 'SecretString' --output text | jq -r '.password'

# 测试 API
curl http://$ALB_DNS/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <master-api-key>" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 200
  }'

# 访问管理后台
open http://$ALB_DNS/admin/
```

API 服务启动时会自动初始化模型定价数据，无需手动 seed。

### ECS Task IAM 权限

CDK 自动为 ECS Task Role 授予以下权限：

| 权限 | 用途 |
|------|------|
| `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream` | 调用 Bedrock 模型 |
| `bedrock:Converse` / `bedrock:ConverseStream` | Converse API |
| DynamoDB CRUD（5 张表） | API Key 验证、用量记录、模型映射、定价查询 |
| Secrets Manager Read | 读取 Master API Key |

### 销毁

```bash
CDK_PLATFORM=arm64 npx cdk destroy --all -c environment=prod
```

---

## 快速开始（本地 Docker Compose）

适用于本地开发和测试，使用 DynamoDB Local，无需 AWS 账号。

### 1. 克隆 & 配置

```bash
git clone https://github.com/HanqingAWS/openai-api-convertor.git
cd openai-api-convertor
cp env.example .env
```

编辑 `.env`，设置 AWS 凭证（用于调用 Bedrock）：
```bash
AWS_REGION=us-west-2
# 如果在 EC2 上使用 IAM Role，不需要设置以下两项
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
```

### 2. 启动服务

```bash
docker-compose up -d --build
```

服务端口：
| 服务 | 端口 | 说明 |
|------|------|------|
| API Proxy | 8000 | OpenAI 兼容 API |
| Admin Portal | 8005 | 管理后台（`/admin/`）|
| DynamoDB Local | 8001 | 本地 DynamoDB |
| DynamoDB Admin | 8002 | DynamoDB 可视化 |

### 3. 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 查看可用模型
curl http://localhost:8000/v1/models

# 打开管理后台
open http://localhost:8005/admin/
```

> **注意**：docker-compose 使用本地 DynamoDB，数据与 ECS 生产环境完全隔离。

---

## API 使用

### Python（OpenAI SDK）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="test-key"  # 本地默认 MASTER_API_KEY
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=200
)
print(response.choices[0].message.content)
```

### curl

```bash
# 非流式
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 200
  }'

# 流式
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 200,
    "stream": true
  }'
```

### Vision（图片输入）

```python
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "这张图片里有什么？"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]
    }]
)
```

### Function Calling

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"]
        }
    }
}]

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "东京天气怎么样？"}],
    tools=tools,
    tool_choice="auto"
)
```

### Extended Thinking

```python
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "解决这个复杂问题..."}],
    extra_body={
        "thinking": {
            "type": "enabled",
            "budget_tokens": 10000
        }
    }
)
```

### 响应格式

#### 非流式响应

```json
{
  "id": "chatcmpl-xxxx",
  "object": "chat.completion",
  "created": 1773646794,
  "model": "claude-sonnet-4-6",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello!",
        "tool_calls": null,
        "thinking": null
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 4222,
    "completion_tokens": 5,
    "total_tokens": 4227,
    "prompt_tokens_details": {
      "cached_tokens": 4210
    },
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 4210,
    "cache_creation": {
      "ephemeral_5m_input_tokens": 0,
      "ephemeral_1h_input_tokens": 0
    }
  }
}
```

#### 流式响应

请求需设置 `"stream": true`。每个 chunk 通过 SSE（Server-Sent Events）返回：

```
data: {"id":"chatcmpl-xxxx","object":"chat.completion.chunk","created":...,"model":"claude-sonnet-4-6","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}],"usage":null}

data: {"id":"chatcmpl-xxxx","object":"chat.completion.chunk","created":...,"model":"claude-sonnet-4-6","choices":[{"index":0,"delta":{"content":"Hello!"},"finish_reason":null}],"usage":null}

data: {"id":"chatcmpl-xxxx","object":"chat.completion.chunk","created":...,"model":"claude-sonnet-4-6","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":null}

data: [DONE]
```

如需在流式响应中获取用量统计，请在请求中加入 `"stream_options": {"include_usage": true}`，最后一个 chunk 会包含完整的 `usage` 字段（格式与非流式一致）。

#### Usage 字段说明

| 字段 | 说明 |
|------|------|
| `prompt_tokens` | 总输入 token 数（= inputTokens + cacheRead + cacheWrite） |
| `completion_tokens` | 输出 token 数 |
| `total_tokens` | prompt_tokens + completion_tokens |
| `prompt_tokens_details.cached_tokens` | 从缓存读取的 token 数 |
| `cache_creation_input_tokens` | 写入缓存的 token 数（对应 Bedrock `cacheWriteInputTokens`） |
| `cache_read_input_tokens` | 从缓存读取的 token 数（对应 Bedrock `cacheReadInputTokens`） |
| `cache_creation.ephemeral_5m_input_tokens` | 以 5 分钟 TTL 写入缓存的 token 数 |
| `cache_creation.ephemeral_1h_input_tokens` | 以 1 小时 TTL 写入缓存的 token 数 |

> `prompt_tokens_details` 和 `cache_creation` 仅在有缓存活动时返回，无缓存时为 `null`。

### Prompt Caching

Prompt caching is **enabled by default**. The proxy automatically inserts cache points for system prompts, conversation history, and tool definitions. No client-side changes needed.

```python
# Automatic caching (default) - no extra config needed
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[
        {"role": "system", "content": "Very long system prompt..."},
        {"role": "user", "content": "Hello!"},
    ],
)
# response.usage.prompt_tokens_details.cached_tokens shows cache hit tokens

# Specify 1 hour TTL for long-running agent tasks
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[...],
    extra_body={"cache_ttl": "1h"}
)

# Disable caching for a single request
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[...],
    extra_body={"caching": False}
)
```

#### 缓存 TTL 优先级

缓存 TTL 按以下优先级从高到低决定，匹配到即停止：

| 优先级 | 来源 | 设置方式 | 示例 |
|--------|------|----------|------|
| 1（最高） | 请求级别 | `extra_body={"cache_ttl": "1h"}` 或 `extra_body={"caching": False}` | 单次请求指定 TTL 或禁用缓存 |
| 2 | API Key 级别 | Admin Portal → API Keys → Cache TTL 下拉框 | 为特定 Key 设置 `5m` / `1h` / `disabled` |
| 3（最低） | 全局配置 | 环境变量 `DEFAULT_CACHE_TTL`（默认 `5m`） | 所有未指定的请求使用此值 |

- API Key Cache TTL 设为 **Proxy Default**（空值）时，回退到全局配置
- 全局开关 `ENABLE_PROMPT_CACHING=false` 将完全禁用缓存，忽略以上所有设置
- 缓存点自动注入位置：system prompt 末尾、tools 定义末尾、对话历史中的 assistant 消息末尾、或累计 token 首次超过阈值的消息末尾

> Note: `claude-3-5-haiku` 不支持 Prompt Caching，对不支持的模型自动跳过缓存。

#### 最小缓存 Token 阈值

Bedrock 对不同模型有不同的最小缓存 token 要求，低于阈值的请求即使插入了缓存点也不会实际缓存。代理会根据模型自动使用对应阈值，只有累计 token 数（system + tools + messages）达到阈值时才会插入缓存点：

| 模型 | 最小缓存 Token 数 |
|------|-------------------|
| claude-sonnet-4-5 | 1,024 |
| claude-sonnet-4-6 | 2,048 |
| claude-opus-4-5 | 4,096 |
| claude-opus-4-6 | 4,096 |
| claude-haiku-4-5 | 2,048 |

环境变量 `PROMPT_CACHE_MIN_TOKENS`（默认 1024）作为未在上表中的模型的回退值。

#### Token 估算逻辑

缓存点注入依赖 token 数估算来判断是否达到阈值。估算规则：
- **英文/拉丁字符**：约 4 字符 ≈ 1 token
- **中日韩（CJK）字符**：约 1.5 字符 ≈ 1 token

如需调整估算精度，修改 `app/converters/openai_to_bedrock.py` 中的 `_estimate_tokens()` 方法。如需修改模型阈值，修改同文件中的 `MODEL_CACHE_MIN_TOKENS` 字典。

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `AWS_REGION` | AWS 区域 | us-west-2 |
| `DYNAMODB_ENDPOINT_URL` | DynamoDB 端点（本地开发用） | - |
| `DYNAMODB_API_KEYS_TABLE` | API Keys 表名 | openai-proxy-api-keys |
| `DYNAMODB_USAGE_TABLE` | Usage 表名 | openai-proxy-usage |
| `DYNAMODB_MODEL_MAPPING_TABLE` | Model Mapping 表名 | openai-proxy-model-mapping |
| `DYNAMODB_PRICING_TABLE` | Pricing 表名 | openai-proxy-pricing |
| `DYNAMODB_USAGE_STATS_TABLE` | Usage Stats 表名 | openai-proxy-usage-stats |
| `REQUIRE_API_KEY` | 是否要求 API Key | false |
| `MASTER_API_KEY` | 管理员 API Key | - |
| `RATE_LIMIT_ENABLED` | 是否启用限流 | false |
| `RATE_LIMIT_REQUESTS` | 每窗口最大请求数 | 100 |
| `RATE_LIMIT_WINDOW` | 限流窗口（秒） | 60 |
| `ENABLE_VISION` | 启用图片输入 | true |
| `ENABLE_TOOL_USE` | 启用工具调用 | true |
| `ENABLE_EXTENDED_THINKING` | 启用扩展思考 | true |
| `ENABLE_PROMPT_CACHING` | 启用 Prompt Caching | true |
| `PROMPT_CACHE_MIN_TOKENS` | 最小缓存 token 数回退值（已知模型使用内置阈值，见上表） | 1024 |
| `DEFAULT_CACHE_TTL` | 默认缓存 TTL（`5m` 或 `1h`） | 5m |
| `SKIP_AUTH` | Admin Portal 跳过认证 | true |
| `COGNITO_USER_POOL_ID` | Cognito User Pool ID | - |
| `COGNITO_CLIENT_ID` | Cognito Client ID | - |

---

## EC2 部署测试

适用于在 EC2 上快速拉取代码测试（Amazon Linux 2023）：

```bash
# 运行安装脚本
bash scripts/ec2_setup.sh

# 配置（EC2 使用 IAM Role，不需要 AK/SK）
cp env.example .env
# 编辑 .env 设置 AWS_REGION

# 启动
sudo docker-compose up -d --build
```

EC2 IAM Role 需要以下权限：
- `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream`
- `bedrock:Converse` / `bedrock:ConverseStream`

安全组需开放端口：8000（API）、8005（Admin Portal）。

---

## 项目结构

```
openai-api-convertor/
├── app/                          # API Proxy 主服务
│   ├── api/                      # API 路由（chat, models, health）
│   ├── converters/               # OpenAI <-> Bedrock 格式转换
│   ├── core/                     # 配置、异常
│   ├── db/                       # DynamoDB 操作
│   ├── middleware/                # 认证、限流中间件
│   ├── schemas/                  # Pydantic 模型
│   └── services/                 # Bedrock 调用服务
├── admin_portal/                 # 管理后台
│   ├── backend/                  # FastAPI 后端
│   │   ├── api/                  # API 路由（keys, pricing, dashboard, mapping）
│   │   ├── middleware/           # Cognito 认证
│   │   ├── schemas/              # 数据模型
│   │   └── services/             # 用量聚合服务（每 5 分钟聚合一次）
│   └── frontend/                 # React + TypeScript + Tailwind
├── cdk/                          # AWS CDK 基础设施
│   ├── lib/                      # Stack 定义（Network, DynamoDB, ECS）
│   └── config/                   # 环境配置（dev, prod）
├── scripts/                      # 工具脚本
│   ├── create_api_key.py         # 创建 API Key
│   ├── setup_tables.py           # 创建 DynamoDB 表
│   ├── seed_pricing.py           # 初始化模型定价
│   └── ec2_setup.sh              # EC2 环境安装
├── tests/                        # 集成测试
│   ├── test_api.sh               # Shell 测试脚本
│   └── test_runner.py            # Python 测试 + HTML 报告
├── Dockerfile                    # API 服务镜像
├── docker-compose.yml            # 本地开发编排
└── pyproject.toml                # Python 依赖
```

## OpenAI 兼容功能对比

| 功能 | OpenAI API | LiteLLM | 本项目 |
|------|:---:|:---:|:---:|
| `/v1/chat/completions` | ✅ | ✅ | ✅ |
| `/v1/models` | ✅ | ✅ | ✅ |
| `/v1/embeddings` | ✅ | ✅ | ❌ |
| `/v1/images` | ✅ | ✅ | ❌ |
| 流式响应 (`stream`) | ✅ | ✅ | ✅ |
| 流式用量 (`stream_options.include_usage`) | ✅ | ✅ | ✅ |
| 系统消息 (`system`) | ✅ | ✅ | ✅ |
| 多轮对话 | ✅ | ✅ | ✅ |
| 图片输入 (`image_url`) | ✅ | ✅ | ✅ |
| 工具调用 (`tools` / `tool_choice`) | ✅ | ✅ | ✅ |
| 工具结果回传 (`tool` role) | ✅ | ✅ | ✅ |
| 结构化输出 (`response_format: json_object`) | ✅ | ✅ | ✅ |
| 结构化输出 (`response_format: json_schema`) | ✅ | ✅ | ✅ |
| Prompt Caching (自动缓存 + TTL 控制) | ❌ | ✅ | ✅ |
| 扩展思考 (`thinking` via `extra_body`) | ❌* | ✅ | ✅ |
| 推理力度 (`reasoning_effort`) | ✅ | ✅ | ✅ |
| Temperature / Top-P | ✅ | ✅ | ✅ |
| Stop Sequences (`stop`) | ✅ | ✅ | ✅ |
| Max Tokens (`max_tokens`) | ✅ | ✅ | ✅ |
| API Key 认证 | ✅ | ✅ | ✅ |
| 速率限制 | ✅ | ✅ | ✅ |
| 用量追踪 & 成本计算 | ✅ | ✅ | ✅ |
| 模型定价管理 | ❌ | ❌ | ✅ |
| Admin Portal 管理后台 | ❌ | ✅ | ✅ |
| 多 Provider 支持 | ✅ | ✅ | ❌** |

> \* OpenAI 原生模型不支持 Claude 风格的扩展思考，此处为 Claude-specific 功能。
>
> \** 本项目专注于 AWS Bedrock Claude 模型，提供最深度的 Claude 功能集成。

---

## 集成测试

### Shell 测试脚本

```bash
export API_BASE_URL=http://localhost:8000
export API_KEY=test-key
export TEST_MODEL=claude-sonnet-4-5

bash tests/test_api.sh

# 运行单个测试
bash tests/test_api.sh test_tool_calling
```

### Python 测试 + HTML 报告

```bash
export API_BASE_URL=http://localhost:8000
export API_KEY=test-key
export TEST_MODEL=claude-sonnet-4-5

python3 tests/test_runner.py

# 指定分类
python3 tests/test_runner.py --category streaming

# 自定义报告路径
python3 tests/test_runner.py --output my_report.html
```

测试覆盖 20+ 用例：健康检查、模型列表、基础对话、系统消息、多轮对话、流式响应、流式用量、结构化输出（json_object / json_schema）、推理力度（low / high）、扩展思考、工具调用、工具结果回传、Temperature、Stop Sequences、Max Tokens、错误处理。

---

## License

MIT
