#!/usr/bin/env python3
"""Smoke-test every model in settings.default_model_mapping against real Bedrock.

Drives each alias with no sampling params (the common client shape) and reports
status plus cache usage. Reads the mapping from config, so it stays correct as
the default mapping changes.

Run inside the api container:
    docker exec -w /app openai-api-convertor-api-1 python tests/probe_default_mapping.py
"""
import os
import sys

# Python puts the SCRIPT's directory first on sys.path, so running this from
# /app/tests resolves `import app` to the stale `pip install .` copy in
# site-packages instead of the bind-mounted /app/app. `docker exec -w /app` is
# not enough to fix that — the repo root has to be prepended explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from app.core.config import settings

BASE = os.environ.get("PROXY_BASE", "http://localhost:8000")
HEADERS = {"Authorization": "Bearer probe-key", "Content-Type": "application/json"}


def err_text(resp):
    try:
        data = resp.json()
    except Exception:
        return resp.text[:110]
    err = data.get("error") or data.get("detail", {}).get("error") or data
    return str(err.get("message", err))[:110]


def probe(alias, bedrock_id):
    payload = {
        "model": alias,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 300,
    }
    try:
        resp = httpx.post(f"{BASE}/v1/chat/completions", timeout=180,
                          headers=HEADERS, json=payload)
    except Exception as exc:
        return "ERR", str(exc)[:110]
    if resp.status_code != 200:
        return str(resp.status_code), err_text(resp)
    content = resp.json()["choices"][0]["message"].get("content") or ""
    return "200", repr(content[:24])


mapping = settings.default_model_mapping
print(f"default_model_mapping: {len(mapping)} entries\n")

bad = []
for alias, bedrock_id in mapping.items():
    endpoint = "Mantle" if bedrock_id.startswith("openai.") else "Converse"
    status, detail = probe(alias, bedrock_id)
    print(f"  [{status}] {alias:22s} {endpoint:8s} {detail}")
    if status != "200":
        bad.append(alias)

print()
if bad:
    print(f"FAILED: {len(bad)}/{len(mapping)} -> {', '.join(bad)}")
else:
    print(f"All {len(mapping)} models OK.")
