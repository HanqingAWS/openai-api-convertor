#!/usr/bin/env python3
"""Regression test: don't send temperature/topP to models that reject them.

Reproduces the Bedrock error:
    ValidationException ... ConverseStream ... This model doesn't support the
    temperature field. Remove temperature and try again.

Two causes, both fixed:
  1. ChatCompletionRequest.temperature/top_p defaulted to 1.0, so
     _build_inference_config always emitted temperature even when the client never
     sent one (and the default also shadowed top_p entirely).
  2. GPT models are reasoning-only and take no sampling params. They now serve over
     Bedrock Converse too (global.openai.gpt-6-astra), not just the Mantle endpoint,
     so the Converse converter has to strip temperature/topP for them.

Note the routing subtlety: "global.openai.gpt-6-astra" does NOT match
is_openai_model()'s startswith("openai.") check, so it goes to Converse, not Mantle.

No network — pure converted-request assertions.

Usage:
    python3 tests/test_temperature_unsupported.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.converters.openai_to_bedrock import OpenAIToBedrockConverter
from app.schemas.openai import ChatCompletionRequest, Message

# A model that still ACCEPTS temperature/topP, for the "params are forwarded"
# cases. Current models (sonnet-5, opus-4-7/4-8, fable-5) deprecated both, so a
# previous-generation id is needed to exercise the forwarding path.
SONNET = "claude-sonnet-4-6"
# A current model, which rejects sampling params and needs adaptive thinking.
CURRENT_CLAUDE = "claude-sonnet-5"
# The real Bedrock ID behind the user's "claude-astra" mapping — a GPT-6 model.
GPT_ASTRA_BEDROCK_ID = "global.openai.gpt-6-astra"
# Alias as configured in the Admin Portal: a GPT model named "claude-*".
GPT_ASTRA_ALIAS = "claude-astra"

failures = []


def check(label, cond, detail=""):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


def convert(mapping=None, cache_ttl=None, **overrides):
    """Convert a request.

    `mapping` adds custom alias -> Bedrock ID entries; `cache_ttl` mirrors what
    chat.py's resolve_cache_ttl() would pass ("5m"/"1h", or None to disable).
    """
    payload = dict(
        model=SONNET,
        messages=[Message(role="user", content="hi")],
    )
    payload.update(overrides)
    request = ChatCompletionRequest(**payload)
    converter = OpenAIToBedrockConverter()
    # The previous-generation ids used here are no longer in the built-in default
    # mapping, so register them explicitly rather than relying on pass-through.
    converter.model_mapping = {
        **converter.model_mapping,
        "claude-sonnet-4-6": "global.anthropic.claude-sonnet-4-6",
        "claude-sonnet-4-5": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        **(mapping or {}),
    }
    return converter.convert_request(request, cache_ttl=cache_ttl), request


def main():
    print("1. client omits temperature -> proxy must not invent one")
    req, _ = convert()
    cfg = req["inferenceConfig"]
    check("no temperature when unset", "temperature" not in cfg, f"got {cfg}")
    check("no topP when unset", "topP" not in cfg, f"got {cfg}")

    print("2. client sends temperature explicitly -> forwarded for normal models")
    req, _ = convert(temperature=0.5)
    check("temperature forwarded", req["inferenceConfig"].get("temperature") == 0.5,
          f"got {req['inferenceConfig']}")

    print("   OpenAI allows up to 2.0, Bedrock caps at 1.0")
    req, _ = convert(temperature=1.8)
    check("temperature clamped to 1.0", req["inferenceConfig"].get("temperature") == 1.0,
          f"got {req['inferenceConfig']}")

    print("3. client sends only top_p -> forwarded")
    req, _ = convert(top_p=0.9)
    check("topP forwarded", req["inferenceConfig"].get("topP") == 0.9,
          f"got {req['inferenceConfig']}")

    print("4. GPT model over Converse -> sampling params stripped even when explicit")
    print("   4a. Bedrock ID passed through directly")
    req, _ = convert(model=GPT_ASTRA_BEDROCK_ID, temperature=0.7)
    cfg = req["inferenceConfig"]
    check("temperature stripped for gpt", "temperature" not in cfg, f"got {cfg}")
    check("topP stripped for gpt", "topP" not in cfg, f"got {cfg}")

    req, _ = convert(model=GPT_ASTRA_BEDROCK_ID, top_p=0.9)
    check("explicit topP stripped for gpt", "topP" not in req["inferenceConfig"],
          f"got {req['inferenceConfig']}")

    print("   4b. via the 'claude-astra' alias (resolved ID is what counts)")
    astra_map = {GPT_ASTRA_ALIAS: GPT_ASTRA_BEDROCK_ID}
    req, _ = convert(mapping=astra_map, model=GPT_ASTRA_ALIAS, temperature=0.7)
    cfg = req["inferenceConfig"]
    check("alias resolves to gpt id", req["modelId"] == GPT_ASTRA_BEDROCK_ID,
          f"got {req['modelId']}")
    check("temperature stripped via alias", "temperature" not in cfg, f"got {cfg}")

    print("   4c. a Claude model behind a 'gpt'-ish alias must NOT be stripped")
    # Uses a previous-generation model: current ones deprecated sampling params,
    # which would strip temperature for a reason unrelated to the alias name.
    req, _ = convert(mapping={"my-gpt-proxy": "global.anthropic.claude-sonnet-4-6"},
                     model="my-gpt-proxy", temperature=0.4)
    check("alias name doesn't trigger stripping",
          req["inferenceConfig"].get("temperature") == 0.4, f"got {req['inferenceConfig']}")

    print("5. reasoning on a GPT model -> no Anthropic thinking block, no temperature")
    req, _ = convert(mapping=astra_map, model=GPT_ASTRA_ALIAS, reasoning_effort="low")
    cfg = req["inferenceConfig"]
    additional = req.get("additionalModelRequestFields", {})
    check("no Anthropic thinking block for gpt", "thinking" not in additional,
          f"got {additional}")
    check("no forced temperature=1 for gpt", "temperature" not in cfg, f"got {cfg}")

    print("   explicit thinking via extra_body is dropped too")
    req, _ = convert(mapping=astra_map, model=GPT_ASTRA_ALIAS,
                     thinking={"type": "enabled", "budget_tokens": 4096})
    additional = req.get("additionalModelRequestFields", {})
    check("explicit thinking dropped for gpt", "thinking" not in additional,
          f"got {additional}")
    check("no temperature from thinking path", "temperature" not in req["inferenceConfig"],
          f"got {req['inferenceConfig']}")

    print("6. long prompt on a GPT model -> no cachePoint block (it rejects them)")
    long_system = (
        "You are a meticulous assistant. "
        # Long enough to clear the highest threshold in MODEL_CACHE_MIN_TOKENS
        # (4096 for opus), so this stays valid whichever model SONNET points at.
        + "Always cite your reasoning and never invent facts you cannot support. " * 260
    )
    long_msgs = [
        Message(role="system", content=long_system),
        Message(role="user", content="hi"),
    ]

    def has_cache_point(req):
        blocks = list(req.get("system") or [])
        for m in req.get("messages", []):
            if isinstance(m.get("content"), list):
                blocks += m["content"]
        blocks += (req.get("toolConfig") or {}).get("tools", [])
        return any(isinstance(b, dict) and "cachePoint" in b for b in blocks)

    req, _ = convert(mapping=astra_map, model=GPT_ASTRA_ALIAS, messages=long_msgs,
                     cache_ttl="5m")
    check("no cachePoint for gpt", not has_cache_point(req),
          "cachePoint was injected")

    print("   the same prompt on Claude must still get one")
    req, _ = convert(model=SONNET, messages=long_msgs, cache_ttl="5m")
    check("cachePoint still injected for claude", has_cache_point(req),
          "cachePoint missing — check the estimated token threshold")

    print("7. reasoning_effort on Claude -> adaptive thinking + output_config.effort")
    # Current models reject thinking.type=enabled:
    #   'Use "thinking.type.adaptive" and "output_config.effort" ...'
    for effort in ("low", "medium", "high", "xhigh", "max"):
        req, _ = convert(model=CURRENT_CLAUDE, reasoning_effort=effort)
        add = req.get("additionalModelRequestFields", {})
        ok = (add.get("thinking", {}).get("type") == "adaptive"
              and add.get("output_config", {}).get("effort") == effort)
        check(f"effort={effort} -> adaptive", ok, f"got {add}")

    req, _ = convert(model=CURRENT_CLAUDE, reasoning_effort="low")
    cfg = req["inferenceConfig"]
    check("no budget_tokens in adaptive shape",
          "budget_tokens" not in req["additionalModelRequestFields"]["thinking"],
          f"got {req['additionalModelRequestFields']}")
    check("no temperature on a sampling-deprecated model", "temperature" not in cfg, f"got {cfg}")
    check("topP dropped", "topP" not in cfg, f"got {cfg}")

    print("   an effort the schema allows but Bedrock wouldn't know falls back to medium")
    # The schema constrains reasoning_effort, so bypass it to exercise the
    # converter's own guard (which protects against a future schema widening).
    req, request = convert(model=CURRENT_CLAUDE, reasoning_effort="low")
    object.__setattr__(request, "reasoning_effort", "turbo")
    converter = OpenAIToBedrockConverter()
    req = converter.convert_request(request)
    check("unknown effort -> medium",
          req["additionalModelRequestFields"]["output_config"]["effort"] == "medium",
          f"got {req.get('additionalModelRequestFields')}")

    print("8. explicit thinking block is passed through verbatim (legacy shape)")
    req, _ = convert(model=SONNET, thinking={"type": "enabled", "budget_tokens": 10000})
    cfg = req["inferenceConfig"]
    thinking = req.get("additionalModelRequestFields", {}).get("thinking")
    check("legacy thinking preserved", thinking == {"type": "enabled", "budget_tokens": 10000},
          f"got {thinking}")
    check("no output_config added", "output_config" not in req.get("additionalModelRequestFields", {}),
          f"got {req.get('additionalModelRequestFields')}")
    check("temperature forced to 1.0 (legacy, model accepts it)",
          cfg.get("temperature") == 1.0, f"got {cfg}")
    check("maxTokens raised above budget", cfg.get("maxTokens", 0) > 10000, f"got {cfg}")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
