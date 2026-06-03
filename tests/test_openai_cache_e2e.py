#!/usr/bin/env python3
"""End-to-end auto-cache check against a running proxy (OpenAI model via Bedrock Mantle).

Sends two back-to-back non-stream requests sharing a long system prompt, then one
streaming request, and reports cached_tokens. Expects the 2nd+ calls to show
prompt_tokens_details.cached_tokens > 0 (auto prompt_cache_key/retention working).

Run inside the api container:
    python tests/test_openai_cache_e2e.py
"""
import json
import os
import sys
import time

import httpx

# Reuse the long (~2.3k token) system prompt that reliably crosses the cache threshold.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_prompt_caching import LONG_SYSTEM_PROMPT

BASE = os.environ.get("PROXY_BASE", "http://localhost:8000")
MODEL = os.environ.get("E2E_MODEL", "openai-gpt-5-5")
HEADERS = {"Authorization": "Bearer e2e-cache-test", "Content-Type": "application/json"}


def post(question, stream=False):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": LONG_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "max_tokens": 60,
        "stream": stream,
    }
    if stream:
        body["stream_options"] = {"include_usage": True}
    with httpx.Client(timeout=120) as c:
        r = c.post(f"{BASE}/v1/chat/completions", headers=HEADERS, json=body)
        r.raise_for_status()
        if not stream:
            return r.json().get("usage", {})
        usage = {}
        for line in r.text.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    obj = json.loads(line[6:])
                    if obj.get("usage"):
                        usage = obj["usage"]
                except Exception:
                    pass
        return usage


def cached(u):
    return (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)


def main():
    print(f"Proxy: {BASE}  Model: {MODEL}\n")

    print("── Round 1 (non-stream): first request → expect cache WRITE, cached=0 ──")
    u1 = post("What is the circuit breaker pattern? One sentence.")
    print(f"  prompt={u1.get('prompt_tokens')} completion={u1.get('completion_tokens')} cached={cached(u1)}")

    time.sleep(3)

    print("── Round 2 (non-stream): same system, new question → expect cached > 0 ──")
    u2 = post("Explain the saga pattern. One sentence.")
    print(f"  prompt={u2.get('prompt_tokens')} completion={u2.get('completion_tokens')} cached={cached(u2)}")

    time.sleep(3)

    print("── Round 3 (stream): same system → expect cached > 0 in usage chunk ──")
    u3 = post("What about the bulkhead pattern? One sentence.", stream=True)
    print(f"  prompt={u3.get('prompt_tokens')} completion={u3.get('completion_tokens')} cached={cached(u3)}")

    print("\n── Verdict ──")
    ok = cached(u2) > 0 or cached(u3) > 0
    if ok:
        print("✅ Auto prompt caching working — cache READ observed on repeat requests.")
    else:
        print("❌ No cache reads observed. Check token threshold / retention / endpoint.")
        sys.exit(1)


if __name__ == "__main__":
    main()
