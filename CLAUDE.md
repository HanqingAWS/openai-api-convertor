# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An OpenAI-compatible API proxy in front of AWS Bedrock. Clients use the stock OpenAI SDK; the proxy
translates to **two different upstream APIs** depending on the resolved model:

- Claude models → Bedrock **Converse API** (boto3 `bedrock-runtime`)
- OpenAI models (`openai.*`) → **Bedrock Mantle Responses API** (`openai` SDK / httpx against
  `https://bedrock-mantle.us-east-2.api.aws/openai/v1`)

Two independent FastAPI apps: the API proxy (`app/`, port 8000) and the Admin Portal
(`admin_portal/`, port 8005 — FastAPI backend + React/Vite frontend served from `/admin/`).

## Commands

### Local development (docker-compose, DynamoDB Local)

```bash
docker-compose up -d --build          # api:8000, admin-portal:8005, dynamodb-local:8001, dynamodb-admin:8002
docker-compose run --rm setup-tables  # create all DynamoDB tables (idempotent)
docker-compose restart api            # picks up app/ changes (./app is bind-mounted read-only)
docker-compose logs -f api
```

`admin-portal` does **not** bind-mount `app/` — to test an `app/` change there, `docker cp` the file
in and `docker restart admin-portal`, or rebuild the image.

### Tests

Test files in `tests/` are **standalone scripts**, not pytest cases (`pyproject.toml` has pytest
config but no `test_*` functions exist, so `pytest` collects nothing).

```bash
export API_BASE_URL=http://localhost:8000 API_KEY=test-key TEST_MODEL=claude-sonnet-4-5

python3 tests/test_runner.py                      # 20+ integration cases → HTML report
python3 tests/test_runner.py --category streaming  # one category (Basic/Chat/Streaming/Structured
                                                   # Output/Reasoning/Tool Use/Parameters/
                                                   # Error Handling/Caching)
python3 tests/test_runner.py --output my.html

bash tests/test_api.sh                 # shell equivalent
bash tests/test_api.sh test_tool_calling   # single case

python3 tests/test_openai_auto_cache.py    # unit, no network (kwargs assertions)
python3 tests/test_openai_multimodal.py    # unit, no network
python3 tests/test_openai_cache_e2e.py     # e2e, run inside the api container
python3 tests/test_prompt_caching.py       # talks to Bedrock directly via boto3
```

### Lint

```bash
ruff check .                                   # line-length 100, rules E/F/I/W, E501 ignored
cd admin_portal/frontend && npm run lint       # eslint, --max-warnings 0
cd admin_portal/frontend && npm run build      # tsc && vite build
```

### CDK deploy

`CDK_PLATFORM` is **required** — `getConfig()` throws without it, and it sets both the Docker build
platform and the Fargate task `cpuArchitecture` (these must match the build host's architecture).

```bash
cd cdk && npm install
export AWS_REGION=us-west-2
CDK_PLATFORM=arm64 npx cdk deploy --all -c environment=prod --require-approval never

# code-only change → ECS stack alone
CDK_PLATFORM=arm64 npx cdk deploy OpenAIProxy-ECS-prod -c environment=prod --exclusively --require-approval never
```

Stacks: `OpenAIProxy-Network-{env}`, `-DynamoDB-{env}`, `-Cognito-{env}`, `-ECS-{env}`. Deploy
Cognito **before** ECS on a fresh account, and DynamoDB before ECS whenever a table is added —
otherwise ECS fails with `UPDATE_ROLLBACK_COMPLETE` on the unresolved table reference. To decide
whether a deploy needs the DynamoDB stack: `git diff --stat <last-deployed-commit> origin/main` and
look for `cdk/lib/dynamodb-stack.ts`.

## Deployment & git workflow (important)

Development happens locally, but **builds, commits, and deploys happen on the EC2 box** (it has
Docker; `cdk deploy` builds images).

1. Edit locally → `scp` to EC2 → test with docker-compose there → iterate.
2. Once green, `git add/commit/push` **on EC2**, then `cdk deploy`, then verify against prod ECS.

- The local clone's git history has **diverged** from GitHub: local `HEAD` (`fe76a99`) is a shadow
  commit not in the remote, and the local remote-tracking ref is stale. **Never `git push` from the
  local machine.** GitHub `main` == the EC2 baseline is authoritative.
- Don't commit intermediate states; test via scp + docker-compose first.
- On EC2, `git fetch` and confirm `HEAD == origin/main` before committing.
- `AWS_REGION` must be exported explicitly in an SSH session; it is not inherited.
- The local working tree can hold code that was reverted upstream (e.g. `app/api/responses.py` /
  `/v1/responses`, reverted on GitHub + prod in commit `8888086`). Check GitHub state before
  assuming the local tree matches production.

Regions: `us-west-2` is the intentional default in README/docs and for the customer deployment —
**do not "correct" it**. The maintainer's own prod environment is `ap-northeast-1`. Both are real.

When fixing a bug: build a failing test/request that reproduces it first, then fix, then re-run the
same test to confirm. Applies in both docker-compose and ECS.

## Architecture

### Request flow (`app/api/chat.py` is the hub)

`POST /v1/chat/completions` →
`get_api_key_info` (auth) → `check_rate_limit` → `resolve_provider` (multi-tenant creds) →
`bedrock_service.resolve_model_id(model)` → `validate_provider_for_model` → branch on
`is_openai_model(resolved_model_id)` (`startswith("openai.")`) → Claude path (`BedrockService`) or
OpenAI path (`OpenAIService`) → usage recorded to DynamoDB in both stream and non-stream paths.

Streaming on both paths uses the same pattern: a worker (thread for boto3, task for httpx) pushes
SSE strings onto an `asyncio.Queue`; the consumer emits `: ping\n\n` every 30s on queue timeout to
survive the ALB idle timeout (set to 300s in `cdk/lib/ecs-stack.ts`). Token usage travels back to
the endpoint through an internal `__usage__:{json}` sentinel line that is stripped before reaching
the client.

### Model resolution is data-driven

`resolve_model_id` checks the DynamoDB `model-mapping` table first, then
`settings.default_model_mapping`, then passes the string through unchanged. So a new model can be
added at runtime via the Admin Portal with no deploy — and the Converse-vs-Mantle routing decision
falls out of whatever Bedrock ID the mapping produces.

### DynamoDB is runtime configuration, not just storage

Seven tables (`openai-proxy-{api-keys,usage,model-mapping,pricing,usage-stats,config,providers}-{env}`),
all managed through `app/db/dynamodb.py` (one manager class per table). Every request reads key info,
provider credentials, and model mappings live — configuration changes take effect on the next
request, no restart. Pricing is auto-seeded by the API service's lifespan handler;
`admin_portal/backend/services/usage_aggregator.py` rolls per-request usage into `usage-stats` every
300s.

### Multi-tenant providers are fail-closed (hard rule)

An API key may carry `provider_id`, binding it to a tenant's own AWS credentials.

- Empty `provider_id` = unbound → host ECS task role, by design.
- Non-empty `provider_id` → **must** authenticate as that provider. Missing, inactive, or incomplete
  credentials raise `ProviderConfigError` (502) / `InvalidRequestError` (400). **Never fall back to
  host credentials** — that was a real bug where tenant traffic silently ran on the host account.

Both auth types serve both model families: `ak_sk` → SigV4 for Converse, and a derived short-lived
bearer token for Mantle; `bearer_token` → an **UNSIGNED** boto3 client with `Authorization: Bearer`
injected per-client via a `before-send` event hook (never a process-global `AWS_BEARER_TOKEN_BEDROCK`
env var — concurrent tenants would clobber each other) for Converse, and passed straight through for
Mantle. Enforcement lives in `chat.py` (`resolve_provider`, `validate_provider_for_model`) and again
defensively in `bedrock_service._get_client_for_provider` / `openai_service.resolve_endpoint`.
Endpoints re-raise `OpenAIProxyError` before the generic `except Exception` so these statuses aren't
masked as 500. Model mappings stay global — there is no per-provider mapping.

Bearer tokens have no refresh path by design: expiry surfaces as a 401 rather than falling back to
IAM. `ak_sk`-derived tokens do refresh (`_invalidate_provider_token` + one retry on 401).

### Two prompt-caching mechanisms, one per path

**Claude** (`app/converters/openai_to_bedrock.py`): `_inject_cache_points()` inserts Bedrock
`cachePoint` blocks automatically. Placement is driven by a **cumulative** token estimate
(system + tools + messages, via `_estimate_tokens()`: ~4 chars/token Latin, ~1.5 CJK) against
per-model thresholds in `MODEL_CACHE_MIN_TOKENS` (sonnet-4-5 1024, sonnet-4-6 2048, opus-4-5/4-6
4096, haiku-4-5 2048; `PROMPT_CACHE_MIN_TOKENS` is the fallback for unknown models). An explicit
client `cache_control` disables auto-injection. `claude-3-5-haiku` doesn't support caching and is
skipped silently. TTL priority: per-request `extra_body` (`cache_ttl` / `caching: false`) >
per-API-key `cache_ttl` > `DEFAULT_CACHE_TTL` (`resolve_cache_ttl` in `chat.py`).

**OpenAI** (`app/services/openai_service.py`): injects `prompt_cache_key` (=
`sha256(api_key + "\0" + instructions)[:32]`) and `prompt_cache_retention` (`24h` for gpt ≥ 5.5,
else `in_memory`). Caching depends on the Responses API `store` default of `true` — **never send
`store=false`**, it kills cache hits entirely. Cache-hit jitter on cold Mantle replicas is expected.

`prompt_tokens = inputTokens + cacheReadInputTokens + cacheWriteInputTokens`;
`prompt_tokens_details` / `cache_creation` are emitted only when there is cache activity.

### Mantle auth (`app/services/openai_token.py`)

`dynamic` mode (default) derives a bearer token from the host IAM role via
`aws-bedrock-token-generator` — cached ~5h with background refresh and a 401 retry. `static` mode
reads a token from the `config` table. Correct API for v1.1.0 (common examples are wrong):
`BedrockTokenGenerator()` takes no constructor args, then `.get_token(frozen_credentials, region)`.

### Admin Portal routes

Note the singular/plural traps: `/api/keys` (not `/api/api-keys`), `/api/model-mapping` (not
`-mappings`), plus `/api/pricing`, `/api/dashboard/stats`, `/api/openai-config`, `/api/providers`,
`/api/auth/config`. Auth is Cognito JWT; with no `COGNITO_USER_POOL_ID` the middleware falls into a
dev mode that auto-injects a dev user and skips auth. The frontend fetches `/api/auth/config` at
boot to configure Amplify.

## Conventions & gotchas

- Model IDs are written without a version suffix (`claude-sonnet-4-6`, not
  `claude-sonnet-4-6-20250929`). Ask for exact Bedrock model IDs rather than guessing them.
- Extended thinking forces `temperature=1`, drops `top_p`, and raises `max_tokens` above
  `budget_tokens` (`convert_request`). `reasoning_effort` low/medium/high → 1024/10000/32000 budget
  for Claude, or native `reasoning.effort` for OpenAI models.
- **GPT models can now be served over Converse, not only Mantle** (e.g.
  `global.openai.gpt-6-astra`). Two consequences:
  - **Routing is decided by prefix, implicitly.** `is_openai_model()` tests
    `startswith("openai.")`, so `openai.gpt-6-astra` → Mantle but `global.openai.gpt-6-astra` →
    Converse. Whoever adds a mapping picks the endpoint via that prefix, probably without knowing.
  - **Three Anthropic-shaped things must be withheld from them**, all keyed off
    `_is_openai_family(resolved_bedrock_id)` / `OPENAI_FAMILY_MODEL_MARKERS`. Verified against
    `global.openai.gpt-6-astra` (see `tests/probe_gpt_over_converse.sh`):
    1. `inferenceConfig.temperature` / `topP` — `ValidationException: This model doesn't support
       the temperature field`.
    2. `additionalModelRequestFields.thinking` — Anthropic-only, so `reasoning_effort` / `thinking`
       is dropped rather than translated. The equivalent Converse field for GPT reasoning effort,
       if one exists, is still unknown; if you find it, `_model_supports_anthropic_thinking` is
       where it goes.
    3. An explicit `cachePoint` block — `AccessDeniedException: You invoked an unsupported model or
       your request did not allow prompt caching`. **Nothing is lost by skipping it:** these models
       cache automatically once the prompt passes ~1024 *actual* tokens, and the proxy still
       reports `cache_read_input_tokens` / `cache_creation_input_tokens` correctly. (Measured: 1704
       tokens → write 1702 on the first call, read 1702 on the second, with no cachePoint sent.)
  - The marker set is matched against the **resolved Bedrock ID only**, never the client-facing
    alias — an alias can be named anything (this model is mapped as `claude-astra`; conversely a
    Claude model could sit behind an alias containing "gpt").
- `temperature`/`top_p` must stay `Optional[...] = None` in the schema: a non-None default makes
  "client omitted it" indistinguishable from "client asked for it", so the proxy invents a value and
  forwards it upstream. The old `1.0` default also shadowed `top_p` entirely (the `elif` branch).
- **TODO (deferred 2026-09-10, "works for now"): a client sending an explicit non-1 sampling value
  still fails on the newest models.** Verified in prod:

  | Model | Path | Error on `temperature=0.7` / `top_p=0.9` |
  |---|---|---|
  | `claude-sonnet-5`, `claude-opus-4-7`, `claude-opus-4-8`, `claude-fable-5` | Converse | 400 `` `temperature` is deprecated for this model `` |
  | `openai.gpt-5.6-*` | Mantle | 400 `unsupported_parameter` (converted to a 500) |

  These accept `temperature=1.0` fine — they reject only *other* values, so the old `1.0` default
  masked this and it is **not** a regression. It matters because many OpenAI clients send
  `temperature=0.7` by default. Two ways to close it: extend the marker set (simple, but that list
  has already proven too narrow twice, and models are added at runtime via the Admin Portal), or
  catch the `deprecated` / `unsupported_parameter` ValidationException, retry once without sampling
  params, and cache that per model (self-healing for future models; the stream path can retry too
  since the error is raised by `converse_stream()` before any chunk is yielded). The Mantle path has
  the same gap in `openai_service._build_responses_kwargs`, which forwards `temperature != 1.0`.
- `gpt-5.x` on Mantle rejects `temperature` unless it is 1 — the OpenAI path only forwards
  `temperature` when it differs from 1, and passthrough surfaces the upstream 400 rather than
  stripping the parameter. Small `max_output_tokens` (< 64) often gets consumed by reasoning tokens
  and returns `status=incomplete`.
- **A script run inside the `api` container from outside `/app` silently imports stale code.** The
  image bakes in a `pip install .` copy at `/usr/local/lib/python3.11/site-packages/app`, while
  `./app` is bind-mounted over `/app/app`. uvicorn runs with cwd `/app` so the server uses the
  mounted (fresh) code, but `docker exec ... python /tmp/some_test.py` puts `/tmp` on `sys.path` and
  resolves `import app` to the stale site-packages copy — tests then "fail" against code you already
  fixed, or pass against code you didn't. Always
  `docker cp <test> <container>:/app/tests/ && docker exec -w /app <container> python tests/<test>`.
- `dynamodb-local` runs **in-memory** (`-inMemory`): a container restart wipes every table. Symptom
  is `validate_api_key` returning `None` so every key degrades to `anonymous` (silently testing the
  host path instead of the provider path), plus `Could not connect to the endpoint URL` in logs. Fix:
  `docker-compose up -d dynamodb-local && docker-compose run --rm setup-tables`, restart `api`, then
  recreate test providers/keys.
- `settings.streaming_timeout` (`STREAMING_TIMEOUT`) is dead code — nothing reads it. Real stream
  bounds are the ALB idle timeout plus the boto3 `read_timeout` (`BEDROCK_TIMEOUT`, 300s).
- Fixed Bedrock `ValidationException` sources worth remembering: a tool with `required: null`
  (defaults to `[]`), and consecutive same-role messages (merged in `_convert_messages`).
- Streaming tool calls need `index` on each `tool_calls` entry and per-`contentBlockIndex` metadata
  tracking, otherwise multi-tool streams lose function names and some clients reject the chunks.
- Never commit private data (public IPs, SSH keys, real API keys); test scripts read
  `$API_BASE_URL` / `$API_KEY` from the environment.
- AWS CLI `cognito-idp` commands hang on the EC2 box (CLI 2.33.15 IPv6/DNS issue) — create admin
  users from a local machine with `scripts/create-admin-user.sh`.
