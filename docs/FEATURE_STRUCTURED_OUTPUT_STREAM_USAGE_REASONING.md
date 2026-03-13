# 需求文档：Structured Output / Stream Usage / Reasoning Effort

## 概述

补齐 OpenAI `/v1/chat/completions` 兼容接口的三项关键功能，使 Proxy 更接近 OpenAI 标准，满足 Agent 框架（LangChain、CrewAI、OpenAI Agents SDK 等）的兼容性要求。

---

## 功能 1：Structured Output (`response_format`)

### 需求

支持 OpenAI `response_format` 参数，让模型输出符合指定 JSON Schema 的结构化数据。

### OpenAI 标准用法

```python
# JSON Object 模式
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    response_format={"type": "json_object"},
    messages=[{"role": "user", "content": "List 3 colors as JSON"}]
)

# JSON Schema 模式
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "math_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "number"},
                    "explanation": {"type": "string"}
                },
                "required": ["answer", "explanation"]
            }
        }
    },
    messages=[{"role": "user", "content": "What is 25 * 4?"}]
)
```

### 实现方案

Bedrock Converse API 不原生支持 `response_format`，采用 **System Prompt 注入** 方案：

1. `type: "json_object"` → 在 system prompt 末尾追加 JSON 输出指令
2. `type: "json_schema"` → 在 system prompt 末尾追加 schema 定义及严格遵循指令
3. `type: "text"` → 无操作（默认行为）

### 修改文件

- `app/schemas/openai.py` — 新增 `response_format` 字段
- `app/converters/openai_to_bedrock.py` — 处理 response_format，注入 system prompt

---

## 功能 2：Streaming Usage Statistics (`stream_options`)

### 需求

流式响应时返回 token 用量统计（prompt_tokens、completion_tokens），供客户端统计成本。

### OpenAI 标准用法

```python
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
    stream_options={"include_usage": True}
)

for chunk in response:
    # 最后一个 chunk 包含 usage 字段
    if chunk.usage:
        print(f"Input: {chunk.usage.prompt_tokens}")
        print(f"Output: {chunk.usage.completion_tokens}")
```

### 数据源

Bedrock ConverseStream 的 `metadata` 事件包含完整 usage：

```json
{
  "metadata": {
    "usage": {
      "inputTokens": 25,
      "outputTokens": 150,
      "totalTokens": 175
    },
    "metrics": {
      "latencyMs": 1234
    }
  }
}
```

### 实现方案

1. 解析 ConverseStream 的 `metadata` 事件，提取 token 用量
2. 当 `stream_options.include_usage = true` 时，在流末尾追加一个包含 `usage` 的 chunk
3. 同时将提取到的 usage 回传给 `chat.py`，用于 UsageTracker 记录

### 修改文件

- `app/schemas/openai.py` — 新增 `StreamOptions`、`ChatCompletionChunk.usage`
- `app/converters/bedrock_to_openai.py` — 处理 metadata 事件，提取 usage
- `app/services/bedrock_service.py` — 传递 stream_options，yield usage 信息
- `app/api/chat.py` — 从流中获取 usage，更新 UsageTracker

---

## 功能 3：Reasoning Effort (`reasoning_effort`)

### 需求

支持 OpenAI 标准的 `reasoning_effort` 参数，简化 Extended Thinking 配置。

### OpenAI 标准用法

```python
response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    reasoning_effort="medium",  # "low", "medium", "high"
    messages=[{"role": "user", "content": "Complex problem..."}]
)
```

### 实现方案

将 `reasoning_effort` 映射为 Bedrock 的 `thinking.budget_tokens`：

| reasoning_effort | budget_tokens |
|-----------------|---------------|
| low             | 1024          |
| medium          | 10000         |
| high            | 32000         |

优先级规则：
- 如果同时传了 `thinking`（via extra_body）和 `reasoning_effort`，以 `thinking` 为准
- `reasoning_effort` 仅在未显式传入 `thinking` 时生效

### 修改文件

- `app/schemas/openai.py` — 新增 `reasoning_effort` 字段
- `app/converters/openai_to_bedrock.py` — 映射 reasoning_effort → thinking config

---

## 测试计划

1. **Structured Output**
   - `response_format: {"type": "json_object"}` → 验证返回合法 JSON
   - `response_format: {"type": "json_schema", ...}` → 验证返回符合 schema
   - 不传 response_format → 行为不变

2. **Stream Usage**
   - `stream: true, stream_options: {"include_usage": true}` → 最后 chunk 含 usage
   - `stream: true` 不传 stream_options → 行为不变
   - 验证 usage 中 prompt_tokens / completion_tokens > 0

3. **Reasoning Effort**
   - `reasoning_effort: "low"` → 返回含 thinking 的响应
   - `reasoning_effort: "high"` → 返回含更长 thinking 的响应
   - 同时传 thinking + reasoning_effort → thinking 优先
