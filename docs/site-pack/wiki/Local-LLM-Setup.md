# Local LLM Setup

Run the whole pipeline with zero API calls and zero per-token cost. Transcripts never leave your machine. (Backend design: task T32 in `tasks/M10-extensions.md`.)

## Why this works on modest hardware

Tagging runs as a **background job** — tokens/second barely matters. Constraints are RAM and quality, not speed. A small GPU (≤2 GB) contributes nothing; run pure CPU.

## Recommended models (Ollama, all tags are pre-quantized Q4_K_M)

| Free RAM for the model | Pull | Notes |
|---|---|---|
| ~6–10 GB | `qwen3:8b` (5.2 GB) | fast lane / cheap stages |
| ~10–16 GB | `qwen3:14b` (9.3 GB) — or `qwen3:14b-q8_0` (16 GB) | solid dense tagger |
| ~18 GB+ (e.g. 32 GB box) | **`qwen3:30b-a3b`** (19 GB) | MoE: ~3B active params → small-model speed, big-model quality. The CPU sweet spot. |

## Setup

```bash
ollama pull qwen3:30b-a3b
export OLLAMA_KEEP_ALIVE=1h        # don't reload 19GB between jobs
```

`.env`:

```
LLM_BACKEND=local
LLM_BASE_URL=http://localhost:11434/v1
LLM_MAX_CONTEXT=16384              # drives chunk sizing + KV cache
LLM_MODEL_TAGGER=qwen3:30b-a3b
LLM_MODEL_ANALYST=qwen3:30b-a3b
LLM_MODEL_SYNTHESIZER=qwen3:30b-a3b
```

**Hybrid mode** (smaller machines): local tagger, API for the reasoning-heavy agents —

```
LLM_BACKEND_TAGGER=local
LLM_BACKEND_ANALYST=openai
LLM_BACKEND_SYNTHESIZER=openai
```

## Alternatives to Ollama

Same GGUF weights, same speed: **llama.cpp `llama-server`** gives more control (grammar-constrained JSON — the strictest schema enforcement anywhere) at the cost of managing model files yourself. LM Studio for GUI exploration. vLLM/SGLang only matter once this runs on a GPU server. Everything talks to `LLM_BASE_URL`, so switching is a one-line change.

## Don't guess — measure

The eval harness (T33) compares models on the hand-labeled fixtures: per-tag precision/recall, quote validity, schema failures, latency. Run it before trusting any model choice:

```bash
python -m app.eval --models qwen3:30b-a3b,gpt-5-mini --live
```
