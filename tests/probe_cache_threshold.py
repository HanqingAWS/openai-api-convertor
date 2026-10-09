#!/usr/bin/env python3
"""Find each Claude model's real minimum cacheable prompt size.

MODEL_CACHE_MIN_TOKENS drives where cachePoint is injected; a value below the
model's real threshold means Bedrock silently ignores the cache point (no error,
just no caching). Bedrock doesn't document these per model, so probe: send a
prompt sized just above a candidate threshold twice and see whether the second
call reports a cache read.

Run inside the api container:
    docker exec -w /app openai-api-convertor-api-1 python tests/probe_cache_threshold.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = os.environ.get("PROXY_BASE", "http://localhost:8000")
HEADERS = {"Authorization": "Bearer probe-key", "Content-Type": "application/json"}
MODELS = os.environ.get(
    "MODELS", "claude-sonnet-5,claude-opus-4-7,claude-opus-4-8,claude-fable-5"
).split(",")

# Candidate thresholds to bracket. Each probe uses a distinct filler so earlier
# probes can't serve its cache.
CANDIDATES = [1024, 2048, 4096]
SENTENCE = "Always cite your reasoning and never invent facts you cannot support. "


def call(model, system):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": "Reply with the single word: ok"},
        ],
        "max_tokens": 300,
    }
    resp = httpx.post(f"{BASE}/v1/chat/completions", timeout=180,
                      headers=HEADERS, json=payload)
    if resp.status_code != 200:
        return None
    return resp.json().get("usage", {})


for model in MODELS:
    model = model.strip()
    print(f"\n{model}:")
    for target in CANDIDATES:
        # ~4 chars/token for Latin text, plus a unique marker per (model, target)
        reps = int(target * 4 / len(SENTENCE)) + 20
        system = f"Probe {model} {target}. " + SENTENCE * reps

        first = call(model, system)
        if first is None:
            print(f"  ~{target:>5} tokens: request failed")
            continue
        second = call(model, system)
        if second is None:
            print(f"  ~{target:>5} tokens: second request failed")
            continue

        prompt = first.get("prompt_tokens", 0)
        write = first.get("cache_creation_input_tokens", 0) or 0
        read = second.get("cache_read_input_tokens", 0) or 0
        verdict = "CACHED" if read > 0 else "not cached"
        print(f"  ~{target:>5} target / {prompt:>5} actual tokens: "
              f"write={write:>5} read={read:>5}  -> {verdict}")
