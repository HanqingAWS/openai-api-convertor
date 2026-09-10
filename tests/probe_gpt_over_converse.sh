#!/usr/bin/env bash
# Probe which Converse features global.openai.gpt-6-astra actually accepts.
#
# GPT models now serve over Bedrock Converse, not only the Mantle endpoint. The proxy's
# Converse converter was built for Claude, so several Anthropic-shaped fields may be
# rejected. This exercises them one at a time against real Bedrock and prints what came
# back, so support is verified rather than assumed.
#
# Usage (from the EC2 host, with the api container up):
#   bash tests/probe_gpt_over_converse.sh
#   MODEL=global.openai.gpt-6-astra bash tests/probe_gpt_over_converse.sh

BASE="${API_BASE_URL:-http://localhost:8000}"
MODEL="${MODEL:-global.openai.gpt-6-astra}"
KEY="${API_KEY:-probe-key}"

# ~6000 chars of filler -> ~1500 estimated tokens, above the 1024 fallback threshold,
# so the converter injects a Bedrock cachePoint block.
LONG_PROMPT="You are a meticulous assistant. Follow the operating rules below exactly. "
for _ in $(seq 1 60); do
  LONG_PROMPT+="Always cite your reasoning, prefer precise wording over vague summaries, and never invent facts you cannot support. "
done

probe() {
  local label="$1" payload="$2"
  local body status
  body=$(curl -s -m 120 -w '\n__STATUS__%{http_code}' "$BASE/v1/chat/completions" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" \
    -d "$payload")
  status=$(sed -n 's/.*__STATUS__//p' <<<"$body")
  body=$(sed 's/__STATUS__.*//' <<<"$body")

  if [ "$status" = "200" ]; then
    # Streaming replies are SSE, not JSON — just confirm chunks arrived.
    if grep -q '^data:' <<<"$body"; then
      echo "  [200] $label -> SSE OK ($(grep -c '^data:' <<<"$body") chunks)"
    else
      echo "  [200] $label -> $(python3 -c '
import json,sys
d=json.load(sys.stdin)
u=d.get("usage") or {}
print(repr((d["choices"][0]["message"].get("content") or "")[:60]),
      "| usage:", {k:v for k,v in u.items() if "token" in k and v})
' <<<"$body" 2>/dev/null || head -c 200 <<<"$body")"
    fi
  else
    echo "  [$status] $label -> $(python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print(sys.stdin.read()[:300]); raise SystemExit
e=d.get("error") or d.get("detail",{}).get("error") or d
print(str(e.get("message", e))[:300])
' <<<"$body" 2>/dev/null || head -c 300 <<<"$body")"
  fi
}

echo "model: $MODEL"
echo "base:  $BASE"
echo

echo "1. baseline, no sampling params"
probe "plain" "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":300}"

echo "2. client sends temperature explicitly (must be stripped by the proxy)"
probe "temperature=0.7" "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":300,\"temperature\":0.7}"

echo "3. client sends top_p explicitly (must be stripped)"
probe "top_p=0.9" "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":300,\"top_p\":0.9}"

echo "4. streaming — the operation the original error came from (ConverseStream)"
probe "stream" "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":300,\"stream\":true}"

echo "5. reasoning_effort (Anthropic thinking block must be dropped)"
probe "reasoning_effort=low" "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":300,\"reasoning_effort\":\"low\"}"

echo "6. long prompt -> converter injects a cachePoint block. Does the model accept it?"
probe "cachePoint (caching on)" "$(python3 - "$MODEL" "$LONG_PROMPT" <<'PY'
import json, sys
print(json.dumps({"model": sys.argv[1],
                  "messages": [{"role": "system", "content": sys.argv[2]},
                               {"role": "user", "content": "Reply with the single word: ok"}],
                  "max_tokens": 300}))
PY
)"

echo "   same long prompt with caching explicitly off (isolates cachePoint as the cause)"
probe "caching=false" "$(python3 - "$MODEL" "$LONG_PROMPT" <<'PY'
import json, sys
print(json.dumps({"model": sys.argv[1],
                  "messages": [{"role": "system", "content": sys.argv[2]},
                               {"role": "user", "content": "Reply with the single word: ok"}],
                  "max_tokens": 300, "caching": False}))
PY
)"

echo
echo "7. control: a Claude model must still accept everything"
probe "claude + temperature + reasoning" "{\"model\":\"claude-sonnet-4-5\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}],\"max_tokens\":300,\"temperature\":0.7}"
