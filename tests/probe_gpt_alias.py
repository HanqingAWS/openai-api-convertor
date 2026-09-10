#!/usr/bin/env python3
"""End-to-end check of the alias path: claude-astra -> global.openai.gpt-6-astra.

Earlier probes passed the Bedrock ID straight through. Production uses the Admin Portal
alias, so this creates that mapping in DynamoDB and drives the alias, verifying both the
request path and what /v1/models reports for it.

Run inside the api container:
    docker exec openai-api-convertor-api-1 python /tmp/probe_gpt_alias.py
"""
import httpx

from app.db.dynamodb import DynamoDBClient, ModelMappingManager

ALIAS = "claude-astra"
BEDROCK_ID = "global.openai.gpt-6-astra"
BASE = "http://localhost:8000"

manager = ModelMappingManager(DynamoDBClient())
manager.set_mapping(ALIAS, BEDROCK_ID)
print("mapping created: {} -> {}".format(ALIAS, manager.get_mapping(ALIAS)))

models = httpx.get("{}/v1/models".format(BASE), timeout=30).json().get("data", [])
entry = next((m for m in models if m["id"] == ALIAS), None)
if entry:
    print("/v1/models: owned_by={} extended_thinking={}".format(
        entry.get("owned_by"), entry.get("capabilities", {}).get("extended_thinking")))
else:
    print("/v1/models: {} MISSING (ids: {})".format(ALIAS, [m["id"] for m in models]))


def call(label, **extra):
    payload = {
        "model": ALIAS,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 300,
    }
    payload.update(extra)
    resp = httpx.post(
        "{}/v1/chat/completions".format(BASE), timeout=120,
        headers={"Authorization": "Bearer probe-key"}, json=payload,
    )
    if resp.status_code != 200:
        print("  [{}] {} -> {}".format(resp.status_code, label, str(resp.json())[:200]))
        return
    data = resp.json()
    usage = data.get("usage", {})
    print("  [200] {} -> {!r} | cache_read={}".format(
        label,
        (data["choices"][0]["message"].get("content") or "")[:40],
        usage.get("cache_read_input_tokens"),
    ))


long_system = (
    "You are a meticulous assistant. "
    + "Always cite your reasoning and never invent facts you cannot support. " * 80
)

print("driving the alias:")
call("plain")
call("temperature=0.7", temperature=0.7)
call("reasoning_effort=high", reasoning_effort="high")
call("long prompt (cachePoint path)",
     messages=[{"role": "system", "content": long_system},
               {"role": "user", "content": "Reply with the single word: ok"}])
