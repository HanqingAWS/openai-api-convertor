#!/bin/bash
# =============================================================================
# OpenAI API Convertor - Integration Test Suite (curl)
#
# Usage:
#   export API_BASE_URL=http://localhost:8000
#   export API_KEY=test-key
#   bash tests/test_api.sh
#
# Or run a specific test:
#   bash tests/test_api.sh test_structured_output_json_object
# =============================================================================

set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-test-key}"
MODEL="${TEST_MODEL:-claude-sonnet-4-5}"

PASS=0
FAIL=0
SKIP=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Helper: make a request and capture response
request() {
  curl -s -w "\n__HTTP_CODE__%{http_code}" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    "$@"
}

# Helper: extract HTTP code and body
parse_response() {
  local response="$1"
  HTTP_CODE=$(echo "$response" | grep -o '__HTTP_CODE__[0-9]*' | grep -o '[0-9]*')
  BODY=$(echo "$response" | sed 's/__HTTP_CODE__[0-9]*//')
}

# Helper: assert condition
assert() {
  local test_name="$1"
  local condition="$2"
  if eval "$condition"; then
    echo -e "  ${GREEN}PASS${NC}: $test_name"
    ((PASS++))
  else
    echo -e "  ${RED}FAIL${NC}: $test_name"
    ((FAIL++))
  fi
}

# ============================================================================
# Test: Health Check
# ============================================================================
test_health() {
  echo -e "\n== Health Check =="
  local resp
  resp=$(request "${API_BASE_URL}/health")
  parse_response "$resp"
  assert "GET /health returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Status is healthy" 'echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d[\"status\"]==\"healthy\"" 2>/dev/null'
}

# ============================================================================
# Test: List Models
# ============================================================================
test_list_models() {
  echo -e "\n== List Models =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/models")
  parse_response "$resp"
  assert "GET /v1/models returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Response has data array" 'echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert len(d[\"data\"])>0" 2>/dev/null'
  assert "Models include capabilities" 'echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d[\"data\"][0].get(\"capabilities\") is not None" 2>/dev/null'
}

# ============================================================================
# Test: Basic Chat Completion (Non-Streaming)
# ============================================================================
test_basic_chat() {
  echo -e "\n== Basic Chat (Non-Streaming) =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Say hello in exactly 3 words\"}],
      \"max_tokens\": 50
    }")
  parse_response "$resp"
  assert "POST returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Has choices array" 'echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert len(d[\"choices\"])>0" 2>/dev/null'
  assert "Has content" 'echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d[\"choices\"][0][\"message\"][\"content\"] is not None" 2>/dev/null'
  assert "Has usage stats" 'echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d[\"usage\"][\"prompt_tokens\"]>0" 2>/dev/null'
  assert "finish_reason is stop" 'echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d[\"choices\"][0][\"finish_reason\"]==\"stop\"" 2>/dev/null'
}

# ============================================================================
# Test: System Message
# ============================================================================
test_system_message() {
  echo -e "\n== System Message =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [
        {\"role\": \"system\", \"content\": \"You are a pirate. Always respond in pirate speak.\"},
        {\"role\": \"user\", \"content\": \"Say hello\"}
      ],
      \"max_tokens\": 100
    }")
  parse_response "$resp"
  assert "System message returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Has content" 'echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert len(d[\"choices\"][0][\"message\"][\"content\"])>0" 2>/dev/null'
}

# ============================================================================
# Test: Streaming
# ============================================================================
test_streaming() {
  echo -e "\n== Streaming =="
  local stream_output
  stream_output=$(curl -s \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Count from 1 to 3\"}],
      \"max_tokens\": 50,
      \"stream\": true
    }")
  assert "Stream has data lines" 'echo "$stream_output" | grep -q "^data: "'
  assert "Stream has [DONE]" 'echo "$stream_output" | grep -q "\[DONE\]"'
  assert "Stream has role delta" 'echo "$stream_output" | grep -q "\"role\":\"assistant\""'
  assert "Stream has content delta" 'echo "$stream_output" | grep -q "\"content\":"'
  assert "Stream has finish_reason" 'echo "$stream_output" | grep -q "\"finish_reason\":\"stop\""'
}

# ============================================================================
# Test: Structured Output - json_object
# ============================================================================
test_structured_output_json_object() {
  echo -e "\n== Structured Output: json_object =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"List 3 colors with hex codes\"}],
      \"max_tokens\": 200,
      \"response_format\": {\"type\": \"json_object\"}
    }")
  parse_response "$resp"
  assert "Returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Content is valid JSON" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
content = d[\"choices\"][0][\"message\"][\"content\"]
json.loads(content)  # Should parse as JSON
" 2>/dev/null'
}

# ============================================================================
# Test: Structured Output - json_schema
# ============================================================================
test_structured_output_json_schema() {
  echo -e "\n== Structured Output: json_schema =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"What is 25 * 4?\"}],
      \"max_tokens\": 200,
      \"response_format\": {
        \"type\": \"json_schema\",
        \"json_schema\": {
          \"name\": \"math_response\",
          \"strict\": true,
          \"schema\": {
            \"type\": \"object\",
            \"properties\": {
              \"answer\": {\"type\": \"number\"},
              \"explanation\": {\"type\": \"string\"}
            },
            \"required\": [\"answer\", \"explanation\"]
          }
        }
      }
    }")
  parse_response "$resp"
  assert "Returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Content matches schema" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
content = json.loads(d[\"choices\"][0][\"message\"][\"content\"])
assert \"answer\" in content, \"Missing answer field\"
assert \"explanation\" in content, \"Missing explanation field\"
assert isinstance(content[\"answer\"], (int, float)), \"answer is not a number\"
assert content[\"answer\"] == 100, f\"Expected 100, got {content[\"answer\"]}\"
" 2>/dev/null'
}

# ============================================================================
# Test: Stream with Usage (stream_options)
# ============================================================================
test_stream_usage() {
  echo -e "\n== Stream with Usage (stream_options) =="
  local stream_output
  stream_output=$(curl -s \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Say hi\"}],
      \"max_tokens\": 30,
      \"stream\": true,
      \"stream_options\": {\"include_usage\": true}
    }")
  assert "Stream has usage chunk" 'echo "$stream_output" | grep -q "\"prompt_tokens\":"'
  assert "Usage has prompt_tokens > 0" 'echo "$stream_output" | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if line.startswith(\"data: \") and \"prompt_tokens\" in line:
        d = json.loads(line[6:])
        assert d[\"usage\"][\"prompt_tokens\"] > 0
        assert d[\"usage\"][\"completion_tokens\"] > 0
        break
" 2>/dev/null'
}

# ============================================================================
# Test: Stream without Usage (backward compat)
# ============================================================================
test_stream_no_usage() {
  echo -e "\n== Stream without Usage (backward compat) =="
  local stream_output
  stream_output=$(curl -s \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Say hi\"}],
      \"max_tokens\": 30,
      \"stream\": true
    }")
  local usage_count
  usage_count=$(echo "$stream_output" | grep -c '"prompt_tokens"' || true)
  assert "No usage chunk when stream_options not set" '[ "$usage_count" = "0" ]'
}

# ============================================================================
# Test: Reasoning Effort (low)
# ============================================================================
test_reasoning_effort_low() {
  echo -e "\n== Reasoning Effort: low =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"What is the square root of 144?\"}],
      \"max_tokens\": 500,
      \"reasoning_effort\": \"low\"
    }")
  parse_response "$resp"
  assert "Returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Has thinking field" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d[\"choices\"][0][\"message\"].get(\"thinking\")
assert t is not None and len(t) > 0, \"No thinking content\"
" 2>/dev/null'
  assert "Has correct answer" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert \"12\" in d[\"choices\"][0][\"message\"][\"content\"]
" 2>/dev/null'
}

# ============================================================================
# Test: Reasoning Effort (high)
# ============================================================================
test_reasoning_effort_high() {
  echo -e "\n== Reasoning Effort: high =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"What is 17 * 23? Show your work.\"}],
      \"max_tokens\": 1000,
      \"reasoning_effort\": \"high\"
    }")
  parse_response "$resp"
  assert "Returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Has thinking field" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d[\"choices\"][0][\"message\"].get(\"thinking\")
assert t is not None and len(t) > 0, \"No thinking content\"
" 2>/dev/null'
  assert "Has answer 391" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert \"391\" in d[\"choices\"][0][\"message\"][\"content\"]
" 2>/dev/null'
}

# ============================================================================
# Test: Tool/Function Calling
# ============================================================================
test_tool_calling() {
  echo -e "\n== Tool / Function Calling =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"What is the weather in Tokyo?\"}],
      \"max_tokens\": 200,
      \"tools\": [{
        \"type\": \"function\",
        \"function\": {
          \"name\": \"get_weather\",
          \"description\": \"Get current weather for a location\",
          \"parameters\": {
            \"type\": \"object\",
            \"properties\": {
              \"location\": {\"type\": \"string\", \"description\": \"City name\"}
            },
            \"required\": [\"location\"]
          }
        }
      }],
      \"tool_choice\": \"auto\"
    }")
  parse_response "$resp"
  assert "Returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Has tool_calls" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tc = d[\"choices\"][0][\"message\"].get(\"tool_calls\")
assert tc is not None and len(tc) > 0, \"No tool_calls\"
" 2>/dev/null'
  assert "Tool name is get_weather" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tc = d[\"choices\"][0][\"message\"][\"tool_calls\"][0]
assert tc[\"function\"][\"name\"] == \"get_weather\"
" 2>/dev/null'
  assert "finish_reason is tool_calls" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d[\"choices\"][0][\"finish_reason\"] == \"tool_calls\"
" 2>/dev/null'
  assert "Arguments contain location" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
args = json.loads(d[\"choices\"][0][\"message\"][\"tool_calls\"][0][\"function\"][\"arguments\"])
assert \"location\" in args
" 2>/dev/null'
}

# ============================================================================
# Test: Extended Thinking (explicit via extra_body)
# ============================================================================
test_extended_thinking() {
  echo -e "\n== Extended Thinking (explicit) =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"What is 15 + 27?\"}],
      \"max_tokens\": 2000,
      \"thinking\": {\"type\": \"enabled\", \"budget_tokens\": 1024}
    }")
  parse_response "$resp"
  assert "Returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Has thinking content" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d[\"choices\"][0][\"message\"].get(\"thinking\")
assert t is not None and len(t) > 0
" 2>/dev/null'
}

# ============================================================================
# Test: Temperature / Top-P
# ============================================================================
test_temperature() {
  echo -e "\n== Temperature =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Pick a random number between 1 and 100\"}],
      \"max_tokens\": 20,
      \"temperature\": 0.0
    }")
  parse_response "$resp"
  assert "Temperature 0.0 returns 200" '[ "$HTTP_CODE" = "200" ]'
}

# ============================================================================
# Test: Stop Sequences
# ============================================================================
test_stop_sequences() {
  echo -e "\n== Stop Sequences =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Count from 1 to 10, each on a new line\"}],
      \"max_tokens\": 200,
      \"stop\": [\"5\"]
    }")
  parse_response "$resp"
  assert "Stop sequence returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Content stopped before 5" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
content = d[\"choices\"][0][\"message\"][\"content\"]
# Content should not contain numbers >= 6
assert \"6\" not in content.split(), f\"Should have stopped before 6\"
" 2>/dev/null'
}

test_prompt_caching() {
  echo -e "\n== Prompt Caching =="
  local resp
  # Build a long system prompt to exceed min token threshold
  local long_prompt=""
  for i in $(seq 1 200); do
    long_prompt="${long_prompt}You are a helpful assistant. "
  done
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [
        {\"role\": \"system\", \"content\": \"${long_prompt}\"},
        {\"role\": \"user\", \"content\": \"Say hi\"}
      ],
      \"max_tokens\": 50
    }")
  parse_response "$resp"
  assert "Caching request returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Has usage with prompt_tokens" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d[\"usage\"][\"prompt_tokens\"] > 0
" 2>/dev/null'
}

test_prompt_caching_disabled() {
  echo -e "\n== Prompt Caching Disabled =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Say hi\"}],
      \"max_tokens\": 50,
      \"caching\": false
    }")
  parse_response "$resp"
  assert "Caching disabled returns 200" '[ "$HTTP_CODE" = "200" ]'
  assert "Has content" 'echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d[\"choices\"][0][\"message\"][\"content\"]
" 2>/dev/null'
}

test_prompt_caching_ttl() {
  echo -e "\n== Prompt Caching TTL 1h =="
  local resp
  resp=$(request "${API_BASE_URL}/v1/chat/completions" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Say hi\"}],
      \"max_tokens\": 50,
      \"cache_ttl\": \"1h\"
    }")
  parse_response "$resp"
  assert "Cache TTL 1h returns 200" '[ "$HTTP_CODE" = "200" ]'
}

# ============================================================================
# Run Tests
# ============================================================================
echo "============================================"
echo " OpenAI API Convertor - Integration Tests"
echo " Base URL: ${API_BASE_URL}"
echo " Model: ${MODEL}"
echo "============================================"

if [ $# -gt 0 ]; then
  # Run specific test
  "$1"
else
  # Run all tests
  test_health
  test_list_models
  test_basic_chat
  test_system_message
  test_streaming
  test_structured_output_json_object
  test_structured_output_json_schema
  test_stream_usage
  test_stream_no_usage
  test_reasoning_effort_low
  test_reasoning_effort_high
  test_tool_calling
  test_extended_thinking
  test_temperature
  test_stop_sequences
  test_prompt_caching
  test_prompt_caching_disabled
  test_prompt_caching_ttl
fi

echo -e "\n============================================"
echo -e " Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo "============================================"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
