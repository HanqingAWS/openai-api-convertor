#!/usr/bin/env python3
"""Unit tests for OpenAI-model auto prompt caching (Bedrock Mantle).

Verifies that OpenAIService injects prompt_cache_key + prompt_cache_retention into
the Responses API kwargs, picks retention by model version, and honors the caching
opt-outs. No network — pure kwargs/helper assertions.

Usage:
    python3 tests/test_openai_auto_cache.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.schemas.openai import ChatCompletionRequest, Message
from app.services.openai_service import OpenAIService


def _req(**overrides):
    base = dict(
        model="openai-gpt-5-5",
        messages=[
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello"),
        ],
    )
    base.update(overrides)
    return ChatCompletionRequest(**base)


def run():
    svc = OpenAIService(dynamodb_client=None)
    failures = []

    def check(name, cond):
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures.append(name)

    print("── auto cache key + retention injected ──")
    kw = svc._build_responses_kwargs(_req(), "openai.gpt-5.5", api_key="sk-abc")
    check("prompt_cache_key present", "prompt_cache_key" in kw)
    check("prompt_cache_key is 32-char hex", len(kw.get("prompt_cache_key", "")) == 32)
    check("gpt-5.5 → 24h retention", kw.get("prompt_cache_retention") == "24h")

    print("── retention by model version ──")
    kw54 = svc._build_responses_kwargs(_req(), "openai.gpt-5.4", api_key="sk-abc")
    check("gpt-5.4 → in_memory retention", kw54.get("prompt_cache_retention") == "in_memory")
    check("gpt-6.0 → 24h retention", svc._prompt_cache_retention("openai.gpt-6.0") == "24h")
    check("unknown model → in_memory", svc._prompt_cache_retention("openai.foo") == "in_memory")

    print("── cache key stability / sensitivity ──")
    k1 = svc._prompt_cache_key("sk-abc", "system A")
    k2 = svc._prompt_cache_key("sk-abc", "system A")
    k3 = svc._prompt_cache_key("sk-abc", "system B")
    k4 = svc._prompt_cache_key("sk-xyz", "system A")
    check("same (key, instructions) → stable", k1 == k2)
    check("different instructions → different key", k1 != k3)
    check("different api_key → different key", k1 != k4)

    print("── per-request opt-out ──")
    kw_off = svc._build_responses_kwargs(_req(caching=False), "openai.gpt-5.5", api_key="sk-abc")
    check("caching=False suppresses prompt_cache_key", "prompt_cache_key" not in kw_off)
    check("caching=False suppresses prompt_cache_retention", "prompt_cache_retention" not in kw_off)

    print("── global disable ──")
    orig = settings.enable_prompt_caching
    try:
        settings.enable_prompt_caching = False
        kw_g = svc._build_responses_kwargs(_req(), "openai.gpt-5.5", api_key="sk-abc")
        check("global disable suppresses cache params", "prompt_cache_key" not in kw_g)
    finally:
        settings.enable_prompt_caching = orig

    print()
    if failures:
        print(f"❌ {len(failures)} check(s) failed: {failures}")
        sys.exit(1)
    print("✅ all checks passed")


if __name__ == "__main__":
    run()
