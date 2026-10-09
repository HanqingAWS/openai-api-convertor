#!/usr/bin/env python3
"""Probe the adaptive-thinking shape newest Claude models require.

claude-sonnet-5 rejects the classic block:
    "thinking.type.enabled" is not supported for this model.
    Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.

Calls Bedrock Converse directly (bypassing the proxy) to find which field
combination is accepted and what `effort` values exist, before changing the
converter.

Run inside the api container:
    docker exec -w /app openai-api-convertor-api-1 python tests/probe_adaptive_thinking.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "us-west-2")
MODEL = os.environ.get("MODEL", "global.anthropic.claude-sonnet-5")

client = boto3.client("bedrock-runtime", region_name=REGION,
                      config=Config(read_timeout=120, connect_timeout=30))

MESSAGES = [{"role": "user", "content": [{"text": "What is 17*23? Think it through."}]}]


def attempt(label, **kwargs):
    try:
        resp = client.converse(modelId=MODEL, messages=MESSAGES,
                               inferenceConfig={"maxTokens": 2048}, **kwargs)
        blocks = resp["output"]["message"]["content"]
        kinds = [k for b in blocks for k in b]
        usage = resp.get("usage", {})
        print(f"  [OK]   {label}")
        print(f"         content blocks={kinds} outputTokens={usage.get('outputTokens')}")
    except Exception as exc:
        msg = str(exc)
        if "ValidationException" in msg:
            msg = msg.split("errors: ", 1)[-1] if "errors: " in msg else msg
        print(f"  [FAIL] {label}")
        print(f"         {msg[:200]}")


print(f"model: {MODEL}  region: {REGION}\n")

print("1. no thinking fields at all (baseline)")
attempt("plain")

print("\n2. the OLD shape the converter currently emits")
attempt("thinking.type=enabled + budget_tokens",
        additionalModelRequestFields={"thinking": {"type": "enabled", "budget_tokens": 1024}})

print("\n3. adaptive without effort")
attempt("thinking.type=adaptive",
        additionalModelRequestFields={"thinking": {"type": "adaptive"}})

print("\n4. adaptive + output_config.effort, each candidate value")
for effort in ("low", "medium", "high", "none", "minimal"):
    attempt(f"adaptive + effort={effort}",
            additionalModelRequestFields={
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": effort},
            })

print("\n5. output_config.effort alone (no thinking block)")
attempt("effort=high only",
        additionalModelRequestFields={"output_config": {"effort": "high"}})
