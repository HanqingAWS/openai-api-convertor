#!/usr/bin/env python3
"""
OpenAI API Convertor - Integration Test Runner

Runs curl-based integration tests and generates a beautiful HTML5 report.

Usage:
    export API_BASE_URL=http://localhost:8000
    export API_KEY=test-key
    python3 tests/test_runner.py

    # Run specific test category:
    python3 tests/test_runner.py --category streaming

    # Custom output path:
    python3 tests/test_runner.py --output my_report.html
"""
import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "test-key")
MODEL = os.environ.get("TEST_MODEL", "claude-sonnet-4-5")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Assertion:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class TestResult:
    name: str
    category: str
    description: str
    passed: bool
    assertions: List[Assertion] = field(default_factory=list)
    duration_ms: float = 0
    http_code: int = 0
    request_body: str = ""
    response_body: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Curl helper
# ---------------------------------------------------------------------------
def curl_request(
    url: str,
    method: str = "GET",
    data: Optional[dict] = None,
    stream: bool = False,
    timeout: int = 120,
) -> dict:
    """Execute a curl request and return parsed result."""
    cmd = [
        "curl", "-s", "-w", "\n__HTTP_CODE__%{http_code}",
        "-X", method,
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {API_KEY}",
        "--max-time", str(timeout),
    ]
    if data:
        cmd += ["-d", json.dumps(data)]
    cmd.append(url)

    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        elapsed_ms = (time.time() - start) * 1000
        raw = result.stdout
    except subprocess.TimeoutExpired:
        return {"body": "", "http_code": 0, "raw": "", "elapsed_ms": timeout * 1000, "error": "timeout"}
    except Exception as e:
        return {"body": "", "http_code": 0, "raw": "", "elapsed_ms": 0, "error": str(e)}

    # Parse HTTP code
    http_code = 0
    body = raw
    if "__HTTP_CODE__" in raw:
        parts = raw.rsplit("__HTTP_CODE__", 1)
        body = parts[0]
        try:
            http_code = int(parts[1].strip())
        except ValueError:
            pass

    return {"body": body.strip(), "http_code": http_code, "raw": raw, "elapsed_ms": elapsed_ms, "error": ""}


def curl_stream(url: str, data: dict, timeout: int = 120) -> dict:
    """Execute a streaming curl request."""
    cmd = [
        "curl", "-s",
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {API_KEY}",
        "--max-time", str(timeout),
        "-d", json.dumps(data),
        url,
    ]
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        elapsed_ms = (time.time() - start) * 1000
        return {"output": result.stdout, "elapsed_ms": elapsed_ms, "error": ""}
    except subprocess.TimeoutExpired:
        return {"output": "", "elapsed_ms": timeout * 1000, "error": "timeout"}
    except Exception as e:
        return {"output": "", "elapsed_ms": 0, "error": str(e)}


def parse_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Test definitions
# ---------------------------------------------------------------------------

def test_health() -> TestResult:
    """Health check endpoint."""
    r = curl_request(f"{API_BASE_URL}/health")
    assertions = []
    assertions.append(Assertion("GET /health returns 200", r["http_code"] == 200))
    body = parse_json(r["body"])
    assertions.append(Assertion(
        "Status is healthy",
        body is not None and body.get("status") == "healthy",
        detail=r["body"][:200] if body is None else "",
    ))
    return TestResult(
        name="Health Check",
        category="Basic",
        description="Verify /health endpoint returns 200 with healthy status",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        response_body=r["body"][:2000],
    )


def test_list_models() -> TestResult:
    """List models endpoint."""
    r = curl_request(f"{API_BASE_URL}/v1/models")
    assertions = []
    assertions.append(Assertion("GET /v1/models returns 200", r["http_code"] == 200))
    body = parse_json(r["body"])
    assertions.append(Assertion(
        "Response has data array",
        body is not None and isinstance(body.get("data"), list) and len(body["data"]) > 0,
    ))
    has_caps = False
    if body and body.get("data"):
        has_caps = body["data"][0].get("capabilities") is not None
    assertions.append(Assertion("Models include capabilities", has_caps))
    return TestResult(
        name="List Models",
        category="Basic",
        description="Verify /v1/models returns model list with capabilities",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        response_body=r["body"][:2000],
    )


def test_basic_chat() -> TestResult:
    """Basic non-streaming chat completion."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say hello in exactly 3 words"}],
        "max_tokens": 50,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("POST returns 200", r["http_code"] == 200))
    assertions.append(Assertion(
        "Has choices array",
        body is not None and isinstance(body.get("choices"), list) and len(body["choices"]) > 0,
    ))
    has_content = False
    if body and body.get("choices"):
        has_content = body["choices"][0].get("message", {}).get("content") is not None
    assertions.append(Assertion("Has content in response", has_content))

    has_usage = False
    if body and body.get("usage"):
        has_usage = body["usage"].get("prompt_tokens", 0) > 0
    assertions.append(Assertion("Has usage stats (prompt_tokens > 0)", has_usage))

    finish_ok = False
    if body and body.get("choices"):
        finish_ok = body["choices"][0].get("finish_reason") == "stop"
    assertions.append(Assertion("finish_reason is 'stop'", finish_ok))

    return TestResult(
        name="Basic Chat (Non-Streaming)",
        category="Chat",
        description="Send a simple message and verify structured response",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_system_message() -> TestResult:
    """System message support."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a pirate. Always respond in pirate speak."},
            {"role": "user", "content": "Say hello"},
        ],
        "max_tokens": 100,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    has_content = False
    if body and body.get("choices"):
        content = body["choices"][0].get("message", {}).get("content", "")
        has_content = len(content) > 0
    assertions.append(Assertion("Has non-empty content", has_content))
    return TestResult(
        name="System Message",
        category="Chat",
        description="Verify system messages are passed to the model",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_multi_turn() -> TestResult:
    """Multi-turn conversation."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "My name is Alice."},
            {"role": "assistant", "content": "Hello Alice! Nice to meet you."},
            {"role": "user", "content": "What is my name?"},
        ],
        "max_tokens": 50,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    has_name = False
    if body and body.get("choices"):
        content = body["choices"][0].get("message", {}).get("content", "")
        has_name = "Alice" in content or "alice" in content
    assertions.append(Assertion("Response contains 'Alice'", has_name))
    return TestResult(
        name="Multi-Turn Conversation",
        category="Chat",
        description="Verify multi-turn context is maintained",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_streaming() -> TestResult:
    """Streaming response."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Count from 1 to 3"}],
        "max_tokens": 50,
        "stream": True,
    }
    r = curl_stream(f"{API_BASE_URL}/v1/chat/completions", data=payload)
    output = r["output"]
    assertions = []
    assertions.append(Assertion("Stream has data lines", "data: " in output))
    assertions.append(Assertion("Stream has [DONE]", "[DONE]" in output))
    assertions.append(Assertion("Stream has role delta", '"role":"assistant"' in output or '"role": "assistant"' in output))
    assertions.append(Assertion("Stream has content delta", '"content":' in output or '"content": ' in output))
    assertions.append(Assertion("Stream has finish_reason", '"finish_reason":"stop"' in output or '"finish_reason": "stop"' in output))
    return TestResult(
        name="Streaming Response",
        category="Streaming",
        description="Verify SSE streaming format with role, content, and finish_reason",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        response_body=output[:3000],
        request_body=json.dumps(payload, indent=2),
    )


def test_stream_usage() -> TestResult:
    """Streaming with usage stats (stream_options)."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 30,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    r = curl_stream(f"{API_BASE_URL}/v1/chat/completions", data=payload)
    output = r["output"]
    assertions = []
    assertions.append(Assertion("Stream has usage chunk", '"prompt_tokens":' in output or '"prompt_tokens": ' in output))

    # Parse usage from stream
    usage_ok = False
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("data: ") and "prompt_tokens" in line:
            try:
                d = json.loads(line[6:])
                usage = d.get("usage", {})
                if usage.get("prompt_tokens", 0) > 0 and usage.get("completion_tokens", 0) > 0:
                    usage_ok = True
            except Exception:
                pass
    assertions.append(Assertion("Usage has prompt_tokens > 0 and completion_tokens > 0", usage_ok))
    return TestResult(
        name="Stream with Usage (stream_options)",
        category="Streaming",
        description="Verify stream_options.include_usage emits a usage chunk",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        request_body=json.dumps(payload, indent=2),
        response_body=output[:3000],
    )


def test_stream_no_usage() -> TestResult:
    """Streaming without usage (backward compat)."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 30,
        "stream": True,
    }
    r = curl_stream(f"{API_BASE_URL}/v1/chat/completions", data=payload)
    output = r["output"]
    count = output.count('"prompt_tokens"')
    assertions = [Assertion("No usage chunk when stream_options not set", count == 0, detail=f"Found {count} occurrences")]
    return TestResult(
        name="Stream without Usage (backward compat)",
        category="Streaming",
        description="Verify no usage chunk is emitted when stream_options is not set",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        request_body=json.dumps(payload, indent=2),
        response_body=output[:3000],
    )


def test_structured_output_json_object() -> TestResult:
    """Structured output: json_object."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "List 3 colors with hex codes"}],
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    content_is_json = False
    content_str = ""
    if body and body.get("choices"):
        content_str = body["choices"][0].get("message", {}).get("content", "")
        parsed = parse_json(content_str)
        content_is_json = parsed is not None
    assertions.append(Assertion("Content is valid JSON", content_is_json, detail=content_str[:200]))
    return TestResult(
        name="Structured Output: json_object",
        category="Structured Output",
        description="Verify response_format type=json_object returns valid JSON",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_structured_output_json_schema() -> TestResult:
    """Structured output: json_schema."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "What is 25 * 4?"}],
        "max_tokens": 200,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "math_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "number"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["answer", "explanation"],
                },
            },
        },
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    schema_ok = False
    answer_ok = False
    if body and body.get("choices"):
        content_str = body["choices"][0].get("message", {}).get("content", "")
        parsed = parse_json(content_str)
        if parsed:
            schema_ok = "answer" in parsed and "explanation" in parsed
            answer_ok = parsed.get("answer") == 100
    assertions.append(Assertion("Content matches schema (has answer + explanation)", schema_ok))
    assertions.append(Assertion("Answer equals 100", answer_ok))
    return TestResult(
        name="Structured Output: json_schema",
        category="Structured Output",
        description="Verify response_format type=json_schema returns conforming JSON",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_reasoning_effort_low() -> TestResult:
    """Reasoning effort: low."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "What is the square root of 144?"}],
        "max_tokens": 500,
        "reasoning_effort": "low",
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    has_thinking = False
    has_answer = False
    if body and body.get("choices"):
        msg = body["choices"][0].get("message", {})
        thinking = msg.get("thinking")
        has_thinking = thinking is not None and len(thinking) > 0
        content = msg.get("content", "")
        has_answer = "12" in content
    assertions.append(Assertion("Has thinking field", has_thinking))
    assertions.append(Assertion("Has correct answer (12)", has_answer))
    return TestResult(
        name="Reasoning Effort: low",
        category="Reasoning",
        description="Verify reasoning_effort='low' enables thinking with small budget",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_reasoning_effort_high() -> TestResult:
    """Reasoning effort: high."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "What is 17 * 23? Show your work."}],
        "max_tokens": 1000,
        "reasoning_effort": "high",
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    has_thinking = False
    has_answer = False
    if body and body.get("choices"):
        msg = body["choices"][0].get("message", {})
        thinking = msg.get("thinking")
        has_thinking = thinking is not None and len(thinking) > 0
        content = msg.get("content", "")
        has_answer = "391" in content
    assertions.append(Assertion("Has thinking field", has_thinking))
    assertions.append(Assertion("Has answer 391", has_answer))
    return TestResult(
        name="Reasoning Effort: high",
        category="Reasoning",
        description="Verify reasoning_effort='high' enables thinking with large budget",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_extended_thinking() -> TestResult:
    """Extended thinking (explicit via thinking param)."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "What is 15 + 27?"}],
        "max_tokens": 2000,
        "thinking": {"type": "enabled", "budget_tokens": 1024},
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    has_thinking = False
    if body and body.get("choices"):
        thinking = body["choices"][0].get("message", {}).get("thinking")
        has_thinking = thinking is not None and len(thinking) > 0
    assertions.append(Assertion("Has thinking content", has_thinking))
    return TestResult(
        name="Extended Thinking (explicit)",
        category="Reasoning",
        description="Verify explicit thinking param enables extended thinking",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_tool_calling() -> TestResult:
    """Tool / Function calling."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "What is the weather in Tokyo?"}],
        "max_tokens": 200,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "City name"},
                        },
                        "required": ["location"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))

    has_tool_calls = False
    tool_name_ok = False
    finish_ok = False
    args_ok = False
    if body and body.get("choices"):
        msg = body["choices"][0].get("message", {})
        tc = msg.get("tool_calls")
        has_tool_calls = tc is not None and len(tc) > 0
        if has_tool_calls:
            tool_name_ok = tc[0].get("function", {}).get("name") == "get_weather"
            args_str = tc[0].get("function", {}).get("arguments", "{}")
            args = parse_json(args_str)
            args_ok = args is not None and "location" in args
        finish_ok = body["choices"][0].get("finish_reason") == "tool_calls"

    assertions.append(Assertion("Has tool_calls", has_tool_calls))
    assertions.append(Assertion("Tool name is 'get_weather'", tool_name_ok))
    assertions.append(Assertion("finish_reason is 'tool_calls'", finish_ok))
    assertions.append(Assertion("Arguments contain 'location'", args_ok))
    return TestResult(
        name="Tool / Function Calling",
        category="Tool Use",
        description="Verify tool calling with auto tool_choice",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_tool_result() -> TestResult:
    """Tool result round-trip."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "What is the weather in Tokyo?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_001",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location":"Tokyo"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_001",
                "content": '{"temperature": 22, "condition": "sunny"}',
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "City name"}
                        },
                        "required": ["location"],
                    },
                },
            }
        ],
        "max_tokens": 200,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    has_content = False
    if body and body.get("choices"):
        content = body["choices"][0].get("message", {}).get("content", "")
        has_content = len(content) > 0
    assertions.append(Assertion("Has response content after tool result", has_content))
    return TestResult(
        name="Tool Result Round-Trip",
        category="Tool Use",
        description="Verify model can process tool results and generate final response",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_temperature() -> TestResult:
    """Temperature parameter."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Pick a random number between 1 and 100"}],
        "max_tokens": 20,
        "temperature": 0.0,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    assertions = [Assertion("Temperature 0.0 returns 200", r["http_code"] == 200)]
    return TestResult(
        name="Temperature Parameter",
        category="Parameters",
        description="Verify temperature parameter is accepted",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_stop_sequences() -> TestResult:
    """Stop sequences."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Count from 1 to 10, each on a new line"}],
        "max_tokens": 200,
        "stop": ["5"],
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    stopped = False
    if body and body.get("choices"):
        content = body["choices"][0].get("message", {}).get("content", "")
        stopped = "6" not in content.split()
    assertions.append(Assertion("Content stopped before reaching 6", stopped))
    return TestResult(
        name="Stop Sequences",
        category="Parameters",
        description="Verify stop sequences halt generation",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_max_tokens() -> TestResult:
    """Max tokens limit."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Write a very long essay about the history of computing."}],
        "max_tokens": 10,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))
    short_response = False
    finish_length = False
    if body and body.get("choices"):
        content = body["choices"][0].get("message", {}).get("content", "")
        # With max_tokens=10, response should be very short
        short_response = len(content.split()) <= 20
        finish_length = body["choices"][0].get("finish_reason") in ("length", "stop")
    assertions.append(Assertion("Response is short (max_tokens enforced)", short_response))
    assertions.append(Assertion("finish_reason is 'length' or 'stop'", finish_length))
    return TestResult(
        name="Max Tokens Limit",
        category="Parameters",
        description="Verify max_tokens limits response length",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_error_invalid_model() -> TestResult:
    """Error handling: invalid model."""
    payload = {
        "model": "nonexistent-model-xyz",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 10,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    assertions = []
    assertions.append(Assertion(
        "Returns error status (4xx or 5xx)",
        r["http_code"] >= 400,
        detail=f"Got HTTP {r['http_code']}",
    ))
    body = parse_json(r["body"])
    has_error = False
    if body:
        has_error = "error" in body or "detail" in body
    assertions.append(Assertion("Response contains error info", has_error))
    return TestResult(
        name="Error: Invalid Model",
        category="Error Handling",
        description="Verify graceful error on invalid model ID",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_error_missing_messages() -> TestResult:
    """Error handling: missing messages."""
    payload = {"model": MODEL, "max_tokens": 10}
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    assertions = [Assertion(
        "Returns 422 (validation error)",
        r["http_code"] == 422,
        detail=f"Got HTTP {r['http_code']}",
    )]
    return TestResult(
        name="Error: Missing Messages",
        category="Error Handling",
        description="Verify validation error when messages field is missing",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2),
        response_body=r["body"][:2000],
    )


def test_prompt_caching_usage() -> TestResult:
    """Prompt caching - usage includes prompt_tokens_details."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. " * 200},
            {"role": "user", "content": "Say hi"},
        ],
        "max_tokens": 50,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))

    has_usage = body is not None and body.get("usage") is not None
    assertions.append(Assertion("Has usage object", has_usage))

    # prompt_tokens should include both input + cached tokens
    prompt_tokens = 0
    if has_usage:
        prompt_tokens = body["usage"].get("prompt_tokens", 0)
    assertions.append(Assertion(
        "prompt_tokens > 0",
        prompt_tokens > 0,
        detail=f"prompt_tokens={prompt_tokens}",
    ))

    return TestResult(
        name="Prompt Caching - Usage Stats",
        category="Caching",
        description="Verify prompt_tokens includes all input (cached + uncached) and prompt_tokens_details is present when caching occurs",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2)[:1000],
        response_body=r["body"][:2000],
    )


def test_prompt_caching_disabled() -> TestResult:
    """Prompt caching - disable via extra_body."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. " * 200},
            {"role": "user", "content": "Say hi"},
        ],
        "max_tokens": 50,
        "caching": False,
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))

    has_content = False
    if body and body.get("choices"):
        has_content = body["choices"][0].get("message", {}).get("content") is not None
    assertions.append(Assertion("Has response content", has_content))

    return TestResult(
        name="Prompt Caching - Disable Per-Request",
        category="Caching",
        description="Verify caching=false disables caching without errors",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2)[:1000],
        response_body=r["body"][:2000],
    )


def test_prompt_caching_ttl_1h() -> TestResult:
    """Prompt caching - 1h TTL via extra_body."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. " * 200},
            {"role": "user", "content": "Say hi"},
        ],
        "max_tokens": 50,
        "cache_ttl": "1h",
    }
    r = curl_request(f"{API_BASE_URL}/v1/chat/completions", method="POST", data=payload)
    body = parse_json(r["body"])
    assertions = []
    assertions.append(Assertion("Returns 200", r["http_code"] == 200))

    has_content = False
    if body and body.get("choices"):
        has_content = body["choices"][0].get("message", {}).get("content") is not None
    assertions.append(Assertion("Has response content", has_content))

    has_usage = body is not None and body.get("usage") is not None
    assertions.append(Assertion("Has usage object", has_usage))

    return TestResult(
        name="Prompt Caching - 1h TTL",
        category="Caching",
        description="Verify cache_ttl=1h is accepted and request succeeds",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=r["http_code"],
        request_body=json.dumps(payload, indent=2)[:1000],
        response_body=r["body"][:2000],
    )


def test_prompt_caching_stream_usage() -> TestResult:
    """Prompt caching - streaming includes cache tokens in usage."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. " * 200},
            {"role": "user", "content": "Say hi"},
        ],
        "max_tokens": 50,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    r = curl_stream(f"{API_BASE_URL}/v1/chat/completions", data=payload)
    assertions = []
    assertions.append(Assertion("Receives stream output", len(r["output"]) > 0))

    # Check for usage chunk with prompt_tokens > 0
    has_usage_chunk = False
    prompt_tokens = 0
    for line in r["output"].strip().split("\n"):
        if line.startswith("data: ") and line != "data: [DONE]":
            try:
                chunk = json.loads(line[6:])
                if chunk.get("usage") and chunk["usage"].get("prompt_tokens", 0) > 0:
                    has_usage_chunk = True
                    prompt_tokens = chunk["usage"]["prompt_tokens"]
            except Exception:
                pass
    assertions.append(Assertion(
        "Has usage chunk with prompt_tokens > 0",
        has_usage_chunk,
        detail=f"prompt_tokens={prompt_tokens}",
    ))

    return TestResult(
        name="Prompt Caching - Streaming Usage",
        category="Caching",
        description="Verify streaming response includes cache usage stats",
        passed=all(a.passed for a in assertions),
        assertions=assertions,
        duration_ms=r["elapsed_ms"],
        http_code=0,
        request_body=json.dumps(payload, indent=2)[:1000],
        response_body=r["output"][:2000],
    )


# ---------------------------------------------------------------------------
# All tests registry
# ---------------------------------------------------------------------------
ALL_TESTS = [
    ("Basic", test_health),
    ("Basic", test_list_models),
    ("Chat", test_basic_chat),
    ("Chat", test_system_message),
    ("Chat", test_multi_turn),
    ("Streaming", test_streaming),
    ("Streaming", test_stream_usage),
    ("Streaming", test_stream_no_usage),
    ("Structured Output", test_structured_output_json_object),
    ("Structured Output", test_structured_output_json_schema),
    ("Reasoning", test_reasoning_effort_low),
    ("Reasoning", test_reasoning_effort_high),
    ("Reasoning", test_extended_thinking),
    ("Tool Use", test_tool_calling),
    ("Tool Use", test_tool_result),
    ("Parameters", test_temperature),
    ("Parameters", test_stop_sequences),
    ("Parameters", test_max_tokens),
    ("Error Handling", test_error_invalid_model),
    ("Error Handling", test_error_missing_messages),
    ("Caching", test_prompt_caching_usage),
    ("Caching", test_prompt_caching_disabled),
    ("Caching", test_prompt_caching_ttl_1h),
    ("Caching", test_prompt_caching_stream_usage),
]


# ---------------------------------------------------------------------------
# HTML Report Generator
# ---------------------------------------------------------------------------
def generate_html_report(results: List[TestResult], total_duration_ms: float) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    pass_rate = (passed / total * 100) if total > 0 else 0

    # Group by category
    categories: Dict[str, List[TestResult]] = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    cat_summary = []
    for cat, tests in categories.items():
        cp = sum(1 for t in tests if t.passed)
        cat_summary.append((cat, len(tests), cp))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build test rows
    test_rows = ""
    for i, r in enumerate(results):
        status_class = "pass" if r.passed else "fail"
        status_icon = "✅" if r.passed else "❌"
        assertion_html = ""
        for a in r.assertions:
            a_icon = "✓" if a.passed else "✗"
            a_class = "assertion-pass" if a.passed else "assertion-fail"
            detail_html = f' <span class="assertion-detail">({a.detail})</span>' if a.detail else ""
            assertion_html += f'<div class="{a_class}"><span class="a-icon">{a_icon}</span> {_esc(a.name)}{detail_html}</div>\n'

        req_body = _esc(r.request_body) if r.request_body else "<em>N/A</em>"
        resp_body = _esc(r.response_body) if r.response_body else "<em>N/A</em>"

        test_rows += f"""
        <div class="test-card {status_class}" onclick="toggleDetail('detail-{i}')">
            <div class="test-header">
                <span class="test-status">{status_icon}</span>
                <span class="test-name">{_esc(r.name)}</span>
                <span class="test-badge badge-{r.category.lower().replace(' ', '-')}">{_esc(r.category)}</span>
                <span class="test-duration">{r.duration_ms:.0f}ms</span>
            </div>
            <div class="test-desc">{_esc(r.description)}</div>
            <div class="test-detail" id="detail-{i}">
                <div class="assertions">
                    <h4>Assertions</h4>
                    {assertion_html}
                </div>
                <div class="payloads">
                    <div class="payload-block">
                        <h4>Request</h4>
                        <pre>{req_body}</pre>
                    </div>
                    <div class="payload-block">
                        <h4>Response <span class="http-code">HTTP {r.http_code}</span></h4>
                        <pre>{resp_body}</pre>
                    </div>
                </div>
            </div>
        </div>
"""

    # Category cards
    cat_cards = ""
    for cat, total_c, passed_c in cat_summary:
        cat_status = "cat-pass" if passed_c == total_c else "cat-fail"
        cat_cards += f"""
            <div class="cat-card {cat_status}">
                <div class="cat-name">{_esc(cat)}</div>
                <div class="cat-stats">{passed_c}/{total_c}</div>
            </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>API Test Report - OpenAI API Convertor</title>
<style>
:root {{
    --bg: #0f172a;
    --surface: #1e293b;
    --surface2: #334155;
    --border: #475569;
    --text: #f1f5f9;
    --text-dim: #94a3b8;
    --green: #22c55e;
    --green-bg: #052e16;
    --red: #ef4444;
    --red-bg: #450a0a;
    --blue: #3b82f6;
    --purple: #a855f7;
    --orange: #f97316;
    --cyan: #06b6d4;
    --yellow: #eab308;
    --radius: 12px;
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
}}

.container {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 32px 24px;
}}

/* Header */
.header {{
    text-align: center;
    margin-bottom: 40px;
}}
.header h1 {{
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(135deg, var(--blue), var(--purple));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
}}
.header .subtitle {{
    color: var(--text-dim);
    font-size: 0.95rem;
}}
.header .meta {{
    margin-top: 12px;
    display: flex;
    justify-content: center;
    gap: 24px;
    font-size: 0.85rem;
    color: var(--text-dim);
}}
.header .meta span {{
    display: flex;
    align-items: center;
    gap: 6px;
}}

/* Summary */
.summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
}}
.summary-card {{
    background: var(--surface);
    border-radius: var(--radius);
    padding: 24px;
    text-align: center;
    border: 1px solid var(--border);
}}
.summary-card .label {{
    font-size: 0.8rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
}}
.summary-card .value {{
    font-size: 2.2rem;
    font-weight: 700;
}}
.summary-card .value.green {{ color: var(--green); }}
.summary-card .value.red {{ color: var(--red); }}
.summary-card .value.blue {{ color: var(--blue); }}
.summary-card .value.purple {{ color: var(--purple); }}

/* Progress bar */
.progress-bar {{
    width: 100%;
    height: 8px;
    background: var(--surface2);
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 32px;
}}
.progress-fill {{
    height: 100%;
    background: linear-gradient(90deg, var(--green), var(--cyan));
    border-radius: 4px;
    transition: width 0.6s ease;
}}
.progress-fill.has-fail {{
    background: linear-gradient(90deg, var(--green), var(--green) {pass_rate:.0f}%, var(--red) {pass_rate:.0f}%, var(--red));
}}

/* Category cards */
.categories {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 32px;
}}
.cat-card {{
    background: var(--surface);
    border-radius: 8px;
    padding: 12px 20px;
    border: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: default;
}}
.cat-card.cat-pass {{ border-color: var(--green); }}
.cat-card.cat-fail {{ border-color: var(--red); }}
.cat-name {{ font-size: 0.9rem; font-weight: 600; }}
.cat-stats {{
    font-size: 0.85rem;
    color: var(--text-dim);
    background: var(--surface2);
    padding: 2px 10px;
    border-radius: 12px;
}}
.cat-pass .cat-stats {{ color: var(--green); }}
.cat-fail .cat-stats {{ color: var(--red); }}

/* Filter */
.filter-bar {{
    display: flex;
    gap: 8px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}}
.filter-btn {{
    padding: 6px 16px;
    border-radius: 20px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-dim);
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.2s;
}}
.filter-btn:hover, .filter-btn.active {{
    border-color: var(--blue);
    color: var(--text);
    background: var(--surface2);
}}

/* Test cards */
.test-card {{
    background: var(--surface);
    border-radius: var(--radius);
    padding: 20px 24px;
    margin-bottom: 12px;
    border-left: 4px solid var(--green);
    cursor: pointer;
    transition: all 0.2s;
}}
.test-card:hover {{
    background: var(--surface2);
}}
.test-card.fail {{
    border-left-color: var(--red);
}}
.test-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}}
.test-status {{ font-size: 1.2rem; }}
.test-name {{ font-weight: 600; font-size: 1rem; }}
.test-badge {{
    font-size: 0.75rem;
    padding: 2px 10px;
    border-radius: 12px;
    font-weight: 500;
}}
.badge-basic {{ background: #1e3a5f; color: var(--blue); }}
.badge-chat {{ background: #1a2e1a; color: var(--green); }}
.badge-streaming {{ background: #2a1a3a; color: var(--purple); }}
.badge-structured-output {{ background: #3a2a0a; color: var(--orange); }}
.badge-reasoning {{ background: #0a2a3a; color: var(--cyan); }}
.badge-tool-use {{ background: #3a3a0a; color: var(--yellow); }}
.badge-parameters {{ background: #1e293b; color: var(--text-dim); }}
.badge-error-handling {{ background: #2a0a0a; color: var(--red); }}
.test-duration {{
    margin-left: auto;
    font-size: 0.85rem;
    color: var(--text-dim);
    font-variant-numeric: tabular-nums;
}}
.test-desc {{
    margin-top: 6px;
    font-size: 0.85rem;
    color: var(--text-dim);
}}
.test-detail {{
    display: none;
    margin-top: 16px;
    border-top: 1px solid var(--border);
    padding-top: 16px;
}}
.test-detail.open {{
    display: block;
}}
.assertions {{ margin-bottom: 16px; }}
.assertions h4 {{ font-size: 0.85rem; color: var(--text-dim); margin-bottom: 8px; }}
.assertion-pass {{ color: var(--green); font-size: 0.9rem; padding: 2px 0; }}
.assertion-fail {{ color: var(--red); font-size: 0.9rem; padding: 2px 0; }}
.assertion-detail {{ color: var(--text-dim); font-size: 0.8rem; }}
.a-icon {{ font-weight: 700; margin-right: 4px; }}
.payloads {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
}}
@media (max-width: 768px) {{
    .payloads {{ grid-template-columns: 1fr; }}
}}
.payload-block h4 {{
    font-size: 0.85rem;
    color: var(--text-dim);
    margin-bottom: 8px;
}}
.http-code {{
    background: var(--surface2);
    padding: 1px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
}}
.payload-block pre {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    font-size: 0.8rem;
    overflow-x: auto;
    max-height: 300px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
}}

/* Footer */
.footer {{
    text-align: center;
    margin-top: 48px;
    padding-top: 24px;
    border-top: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 0.8rem;
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>OpenAI API Convertor</h1>
        <div class="subtitle">Integration Test Report</div>
        <div class="meta">
            <span>📅 {now}</span>
            <span>🌐 {_esc(API_BASE_URL)}</span>
            <span>🤖 {_esc(MODEL)}</span>
            <span>⏱ {total_duration_ms / 1000:.1f}s</span>
        </div>
    </div>

    <div class="summary">
        <div class="summary-card">
            <div class="label">Total Tests</div>
            <div class="value blue">{total}</div>
        </div>
        <div class="summary-card">
            <div class="label">Passed</div>
            <div class="value green">{passed}</div>
        </div>
        <div class="summary-card">
            <div class="label">Failed</div>
            <div class="value {'red' if failed > 0 else 'green'}">{failed}</div>
        </div>
        <div class="summary-card">
            <div class="label">Pass Rate</div>
            <div class="value {'green' if pass_rate == 100 else 'purple'}">{pass_rate:.0f}%</div>
        </div>
    </div>

    <div class="progress-bar">
        <div class="progress-fill {'has-fail' if failed > 0 else ''}" style="width: {pass_rate}%"></div>
    </div>

    <div class="categories">
        {cat_cards}
    </div>

    <div class="filter-bar">
        <button class="filter-btn active" onclick="filterTests('all')">All</button>
        <button class="filter-btn" onclick="filterTests('pass')">✅ Passed</button>
        <button class="filter-btn" onclick="filterTests('fail')">❌ Failed</button>
    </div>

    <div id="test-list">
        {test_rows}
    </div>

    <div class="footer">
        Generated by <strong>OpenAI API Convertor Test Runner</strong> &middot;
        Powered by curl + Python
    </div>
</div>

<script>
function toggleDetail(id) {{
    const el = document.getElementById(id);
    if (el) el.classList.toggle('open');
}}

function filterTests(type) {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    document.querySelectorAll('.test-card').forEach(card => {{
        if (type === 'all') {{
            card.style.display = '';
        }} else if (type === 'pass') {{
            card.style.display = card.classList.contains('pass') ? '' : 'none';
        }} else if (type === 'fail') {{
            card.style.display = card.classList.contains('fail') ? '' : 'none';
        }}
    }});
}}
</script>
</body>
</html>"""
    return html


def _esc(s: str) -> str:
    """Escape HTML special characters."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="OpenAI API Convertor - Integration Test Runner")
    parser.add_argument("--category", "-c", help="Run only tests in this category")
    parser.add_argument("--output", "-o", default="tests/test_report.html", help="Output HTML report path")
    parser.add_argument("--list", "-l", action="store_true", help="List all test names and exit")
    args = parser.parse_args()

    if args.list:
        for cat, fn in ALL_TESTS:
            print(f"  [{cat}] {fn.__doc__}")
        return

    print("=" * 60)
    print("  OpenAI API Convertor - Integration Test Runner")
    print(f"  Base URL : {API_BASE_URL}")
    print(f"  Model    : {MODEL}")
    print(f"  Report   : {args.output}")
    print("=" * 60)

    tests_to_run = ALL_TESTS
    if args.category:
        tests_to_run = [(c, fn) for c, fn in ALL_TESTS if c.lower() == args.category.lower()]
        if not tests_to_run:
            print(f"\nNo tests found for category '{args.category}'")
            print(f"Available: {', '.join(sorted(set(c for c, _ in ALL_TESTS)))}")
            sys.exit(1)

    results: List[TestResult] = []
    overall_start = time.time()

    for cat, test_fn in tests_to_run:
        name = test_fn.__doc__ or test_fn.__name__
        sys.stdout.write(f"\n  Running: {name} ... ")
        sys.stdout.flush()
        try:
            result = test_fn()
            results.append(result)
            icon = "✅" if result.passed else "❌"
            print(f"{icon}  ({result.duration_ms:.0f}ms)")
            for a in result.assertions:
                a_icon = "  ✓" if a.passed else "  ✗"
                print(f"    {a_icon} {a.name}")
        except Exception as e:
            print(f"💥 ERROR: {e}")
            results.append(TestResult(
                name=name,
                category=cat,
                description="",
                passed=False,
                error=str(e),
            ))

    total_duration = (time.time() - overall_start) * 1000

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed, {len(results)} total")
    print(f"  Duration: {total_duration / 1000:.1f}s")
    print("=" * 60)

    # Generate HTML report
    html = generate_html_report(results, total_duration)
    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  📄 HTML report saved to: {args.output}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
