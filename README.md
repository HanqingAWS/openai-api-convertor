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

支持通过 Admin Portal 或 DynamoDB 自定义映射，优先级：DynamoDB 自定义 > 默认配置 > 直接透传。

---

## 快速开始（本地 Docker Compose）

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
- **最小 Token 阈值**：Prompt 内容低于 `PROMPT_CACHE_MIN_TOKENS`（默认 1024）时不会插入缓存点，避免对短 prompt 产生不必要的缓存写入开销。可通过环境变量调整此阈值

> Note: `claude-3-5-haiku` 不支持 Prompt Caching，对不支持的模型自动跳过缓存。

---

## EC2 部署测试

适用于在 EC2 上快速拉取代码测试（Amazon Linux 2023）：

```bash
# 运行安装脚本
bash scripts/ec2_setup.sh

# 或手动操作
sudo yum install -y docker git
sudo systemctl start docker
sudo usermod -aG docker $USER

# 安装 Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 克隆代码
git clone https://github.com/HanqingAWS/openai-api-convertor.git
cd openai-api-convertor

# 配置（EC2 使用 IAM Role，不需要 AK/SK）
cp env.example .env
# 编辑 .env 设置 AWS_REGION

# 启动
sudo docker-compose up -d --build

# 查看日志
sudo docker-compose logs -f api
sudo docker-compose logs -f admin-portal
```

EC2 IAM Role 需要以下权限：
- `bedrock:InvokeModel`
- `bedrock:InvokeModelWithResponseStream`
- `bedrock:Converse`
- `bedrock:ConverseStream`

安全组需开放端口：8000（API）、8005（Admin Portal）。

---

## CDK 部署（生产环境）

使用 AWS CDK 部署到 ECS Fargate，包含 VPC、ALB、DynamoDB、ECS 服务。

### 架构

```
ALB (80/443)
  ├── /v1/*          → API Proxy Service (Fargate)
  ├── /admin/*       → Admin Portal Service (Fargate)
  └── /api/*         → Admin Portal Service (Fargate)

DynamoDB Tables:
  ├── openai-proxy-api-keys-{env}
  ├── openai-proxy-usage-{env}
  ├── openai-proxy-model-mapping-{env}
  ├── openai-proxy-pricing-{env}
  └── openai-proxy-usage-stats-{env}
```

### 部署步骤

```bash
cd cdk
npm install

# Bootstrap（首次部署需要）
CDK_PLATFORM=arm64 npx cdk bootstrap -c environment=dev

# 部署开发环境
CDK_PLATFORM=arm64 npx cdk deploy --all -c environment=dev --require-approval never

# 部署生产环境
CDK_PLATFORM=arm64 npx cdk deploy --all -c environment=prod

# 查看输出（ALB 地址等）
CDK_PLATFORM=arm64 npx cdk deploy --all -c environment=dev --outputs-file outputs.json
```

`CDK_PLATFORM` 支持 `arm64`（Graviton，推荐）和 `amd64`。

### 部署后测试

```bash
# 从 CDK 输出获取 ALB 地址
ALB_DNS=<your-alb-dns-name>

# 获取 Master API Key（存储在 Secrets Manager）
aws secretsmanager get-secret-value \
  --secret-id openai-proxy-dev-master-api-key \
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

### 销毁

```bash
CDK_PLATFORM=arm64 npx cdk destroy --all -c environment=dev
```

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
| `PROMPT_CACHE_MIN_TOKENS` | 最小缓存 token 数（低于此值不缓存） | 1024 |
| `DEFAULT_CACHE_TTL` | 默认缓存 TTL（`5m` 或 `1h`） | 5m |
| `SKIP_AUTH` | Admin Portal 跳过认证 | true |
| `COGNITO_USER_POOL_ID` | Cognito User Pool ID | - |
| `COGNITO_CLIENT_ID` | Cognito Client ID | - |

---

## 项目结构

```
openai-api-convertor/
├── app/                          # API Proxy 主服务
│   ├── api/                      # API 路由（chat, models, health）
│   ├── converters/               # OpenAI ↔ Bedrock 格式转换
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
│   │   └── services/             # 用量聚合服务
│   └── frontend/                 # React + TypeScript + Tailwind
├── cdk/                          # AWS CDK 基础设施
│   ├── lib/                      # Stack 定义（Network, DynamoDB, ECS）
│   └── config/                   # 环境配置（dev, prod）
├── scripts/                      # 工具脚本
│   ├── create_api_key.py         # 创建 API Key
│   ├── setup_tables.py           # 创建 DynamoDB 表
│   ├── seed_pricing.py           # 初始化模型定价
│   └── ec2_setup.sh              # EC2 环境安装
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

项目提供两种测试方式：

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

测试覆盖 20 个用例：健康检查、模型列表、基础对话、系统消息、多轮对话、流式响应、流式用量、结构化输出（json_object / json_schema）、推理力度（low / high）、扩展思考、工具调用、工具结果回传、Temperature、Stop Sequences、Max Tokens、错误处理。

---

## 初始化定价数据

```bash
# 本地开发（DynamoDB Local）
python scripts/seed_pricing.py

# 覆盖已有定价
python scripts/seed_pricing.py --force

# 生产环境
python scripts/seed_pricing.py --no-endpoint
```

---

## License

MIT
