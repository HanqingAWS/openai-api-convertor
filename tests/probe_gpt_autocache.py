#!/usr/bin/env python3
"""Does global.openai.gpt-6-astra cache automatically, with no cachePoint block?

The model rejects an explicit Bedrock cachePoint (AccessDeniedException) yet reports
cacheWriteInputTokens when none is sent — suggesting it caches on its own, like the
OpenAI API does. If a repeated identical prefix shows cache_read > 0, then skipping
cachePoint injection for GPT models costs nothing.

Run inside the api container:
    docker exec openai-api-convertor-api-1 python /tmp/probe_gpt_autocache.py
"""
import os

import httpx

BASE = os.environ.get("PROXY_BASE", "http://localhost:8000")
MODEL = os.environ.get("MODEL", "global.openai.gpt-6-astra")

LONG = (
    "You are a meticulous assistant. Follow the operating rules below exactly. "
    + "Always cite your reasoning, prefer precise wording over vague summaries, "
    "and never invent facts you cannot support. " * 60
)


def call(n, caching):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": LONG},
            {"role": "user", "content": "Reply with the single word: ok"},
        ],
        "max_tokens": 300,
    }
    if caching is not None:
        payload["caching"] = caching
    resp = httpx.post(
        f"{BASE}/v1/chat/completions",
        timeout=120,
        headers={"Authorization": "Bearer probe-key"},
        json=payload,
    )
    if resp.status_code != 200:
        msg = str(resp.json())[:160]
        print("  call {}: status={} {}".format(n, resp.status_code, msg))
        return
    usage = resp.json().get("usage", {})
    print(
        "  call {}: prompt={} cache_read={} cache_write={}".format(
            n,
            usage.get("prompt_tokens"),
            usage.get("cache_read_input_tokens"),
            usage.get("cache_creation_input_tokens"),
        )
    )


print("identical long prompt, no cachePoint injected (caching=false):")
for i in (1, 2, 3):
    call(i, caching=False)
