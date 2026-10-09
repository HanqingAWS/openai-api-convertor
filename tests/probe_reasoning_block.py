#!/usr/bin/env python3
"""Does adaptive thinking actually return a reasoningContent block?

The proxy maps Bedrock's reasoningContent -> reasoning_content / thinking. With
thinking.type=adaptive the block appears only sometimes, which decides whether
the integration suite's "Has thinking field" assertion can hold.

Run inside the api container:
    docker exec -w /app openai-api-convertor-api-1 python tests/probe_reasoning_block.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "us-west-2")
MODEL = os.environ.get("MODEL", "global.anthropic.claude-sonnet-5")
RUNS = int(os.environ.get("RUNS", "3"))

client = boto3.client("bedrock-runtime", region_name=REGION,
                      config=Config(read_timeout=180, connect_timeout=30))

PROMPT = [{"role": "user", "content": [{"text": "What is 17*23? Think it through."}]}]

CASES = {
    "adaptive+effort=low": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}},
    "adaptive+effort=high": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
    "adaptive+effort=max": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "max"}},
    "adaptive (no effort)": {"thinking": {"type": "adaptive"}},
    "no thinking fields": None,
}

print(f"model: {MODEL}  region: {REGION}  runs per case: {RUNS}\n")

for label, amrf in CASES.items():
    kwargs = {"additionalModelRequestFields": amrf} if amrf else {}
    marks, tokens = [], []
    for _ in range(RUNS):
        resp = client.converse(modelId=MODEL, messages=PROMPT,
                               inferenceConfig={"maxTokens": 4096}, **kwargs)
        blocks = [k for b in resp["output"]["message"]["content"] for k in b]
        marks.append("R" if "reasoningContent" in blocks else "-")
        tokens.append(resp["usage"]["outputTokens"])
    hits = marks.count("R")
    print(f"  {label:22s} reasoning={''.join(marks)} ({hits}/{RUNS})  "
          f"outputTokens={tokens}")

print("\nR = reasoningContent block present, - = absent")
