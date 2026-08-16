# Local LLM Hosting with Ollama

MomBoard supports optional local LLM inference via [Ollama](https://ollama.com/), using a pinned Docker Compose profile. Coding agents must also follow [`agent-deployment.md`](agent-deployment.md), especially its data-preservation and verification gates.

The initial `qwen3:8b` pull is several gigabytes and consumes network, disk, memory, and compute. A coding agent must obtain approval before starting that download or launching a resource-intensive local model.

## Quick Start

```bash
# Configure .env first, then start app + Ollama after approval
if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE='docker-compose'
else
  COMPOSE='docker compose'
fi
$COMPOSE --profile local-llm config -q
$COMPOSE --profile local-llm up -d

# Wait for the one-shot model bootstrap to exit successfully
$COMPOSE logs -f ollama-bootstrap
$COMPOSE ps -a
curl -fsS http://127.0.0.1:11434/api/tags
```

Configure `.env` as shown below before starting the stack. If the Docker plugin reports `unknown flag: --profile`, install/use the standalone `docker-compose` command as shown above. A successfully exited `ollama-bootstrap` container is expected; it pulls the model once and then stops.

## Configuration

For MomBoard running in Docker Compose, add to `.env`:

```env
LLM_BACKEND=local
LLM_BASE_URL=http://ollama:11434
LLM_LOCAL_MODEL=qwen3:8b
LLM_LOCAL_TIMEOUT=300
LLM_MAX_CONTEXT=8192
```

For MomBoard running from source on the host while Ollama listens on the host, use:

```env
LLM_BACKEND=local
LLM_BASE_URL=http://127.0.0.1:11434
LLM_LOCAL_MODEL=qwen3:8b
LLM_LOCAL_TIMEOUT=300
LLM_MAX_CONTEXT=8192
```

Container DNS name `ollama` is not resolvable from a host process. Conversely, `127.0.0.1` inside the app container points to the app container, not Ollama. All LLM stages use `LLM_LOCAL_MODEL` when the local backend is selected.

### Settings Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BACKEND` | `openai` | LLM provider: `openai` or `local` |
| `LLM_BASE_URL` | _(empty)_ | Required when `LLM_BACKEND=local`. Ollama API URL. |
| `LLM_LOCAL_MODEL` | `qwen3:8b` | Default model for **all** agents when `LLM_BACKEND=local`. |
| `LLM_LOCAL_FLAVOR` | `ollama` | Local backend type (currently only `ollama`). |
| `LLM_LOCAL_TIMEOUT` | `300` | Per-request timeout in seconds. Increase for slow CPU-only inference. |
| `LLM_MAX_CONTEXT` | `32768` | Context window budget in tokens. Drives chunk sizing. |

### OpenAI-only Settings (ignored when `LLM_BACKEND=local`)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL_TAGGER` | `gpt-5-mini` | Model for tagging agent (OpenAI only). |
| `LLM_MODEL_ANALYST` | `gpt-5-mini` | Model for analyst agent (OpenAI only). |
| `LLM_MODEL_NORMALIZER` | `gpt-5-mini` | Model for normalizer fallback (OpenAI only). |
| `LLM_MODEL_SYNTHESIZER` | `gpt-5-mini` | Model for synthesis agent (OpenAI only). |

### Overriding the Local Model

To use a different model locally:

```bash
# Pull a different model after approval
$COMPOSE exec ollama ollama pull llama3.1:8b

# Set the single local-model variable in .env
LLM_LOCAL_MODEL=llama3.1:8b
```

All agents will route to that model. The `LLM_MODEL_*` per-agent settings
are **only** used with the OpenAI backend and do not affect local hosting.

## Architecture

```
┌─────────────────────────────────────────────────┐
│ MomBoard App                                     │
│  ┌─────────────┐   ┌──────────────────────────┐ │
│  │ LLM Factory │──►│ OpenAIResponsesClient    │ │ (LLM_BACKEND=openai)
│  │             │──►│ OllamaClient             │ │ (LLM_BACKEND=local)
│  └─────────────┘   └──────────────────────────┘ │
└───────────────────────────┬─────────────────────┘
                            │ HTTP (no auth header)
                    ┌───────▼───────┐
                    │  Ollama:11434 │
                    │  qwen3:8b     │
                    └───────────────┘
```

## Default Model: qwen3:8b

The default model is `qwen3:8b` — selected because:

- **CPU-capable**: Runs on machines without a GPU (6–8GB RAM sufficient)
- **JSON-schema support**: Ollama's native `format` field constrains output to the expected schema
- **Quality**: Strong structured output compliance for its size class

## How Structured Output Works

Unlike OpenAI's strict JSON schema mode, Ollama uses a native `format` field:

```json
{
  "model": "qwen3:8b",
  "messages": [...],
  "format": {
    "type": "object",
    "properties": { ... },
    "required": [...]
  },
  "stream": false
}
```

The `OllamaClient` automatically:
1. Extracts the JSON schema from the Pydantic model
2. Sends it in the `format` field
3. Validates the response against the schema
4. On validation failure, sends a **repair retry** with the error message
5. If the repair also fails, raises `LLMSchemaError`

## Resource Requirements

| Config | RAM | Speed (8B model) |
|--------|-----|-------------------|
| CPU only | 8 GB | ~2–5 tok/s |
| GPU (RTX 3060) | 6 GB VRAM | ~30 tok/s |
| Apple M1/M2 | 8 GB unified | ~15 tok/s |

## Verification

```bash
# Host-exposed Ollama API and exact configured model
curl -fsS http://127.0.0.1:11434/api/tags | grep -q 'qwen3:8b'

# Container state and bootstrap exit status
$COMPOSE ps -a

# MomBoard surfaces
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/me)" = 401
```

For an end-to-end inference check, sign in, ingest a short non-sensitive transcript, and wait for processing. Review app and Ollama logs for schema repair failures; do not use real customer data for an unapproved smoke test.

## Troubleshooting

```bash
$COMPOSE ps -a
$COMPOSE logs --tail=200 ollama ollama-bootstrap app
curl -fsS http://127.0.0.1:11434/api/tags
```

- `model ... not found`: `LLM_LOCAL_MODEL` must exactly match a tag returned by `/api/tags`. The Compose bootstrap always pulls `qwen3:8b`; changing `.env` alone does not pull another model.
- Connection refused from a source process: use `http://127.0.0.1:11434` and confirm port 11434 is published.
- Connection refused from the app container: use `http://ollama:11434`, not localhost, and start the `local-llm` profile.
- Bootstrap exited: inspect its exit code/log. Exit code 0 is normal after a successful pull.
- Out of memory or very slow inference: stop the model and choose a smaller approved tag or add resources; do not bypass Compose resource limits silently.

## Stopping

```bash
# Stop only Ollama (keeps app running)
$COMPOSE --profile local-llm stop ollama

# Or stop everything; named model data remains unless volumes are explicitly removed
$COMPOSE --profile local-llm down
```

## Switching Between Backends

You can switch between OpenAI and local without code changes:

```bash
# Use OpenAI
LLM_BACKEND=openai
OPENAI_API_KEY=sk-...

# Use local Ollama
LLM_BACKEND=local
LLM_BASE_URL=http://ollama:11434
LLM_MAX_CONTEXT=8192
```

The worker and all LLM agents will automatically use the correct client.
