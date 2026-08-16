# Architecture

Full detail lives in [`DESIGN.md`](https://github.com/tmdavid/Momboard/blob/main/DESIGN.md); this page is the orientation map.

## Shape

One process: FastAPI serves the REST API + built React SPA, and runs an asyncio **job worker** polling a `jobs` table (no Redis/Celery). All LLM calls are isolated in `app/llm/` behind an `LLMClient` protocol — OpenAI Responses API or any OpenAI-compatible local server (see [[Local LLM Setup]]).

```
React SPA → FastAPI → services → SQLAlchemy → SQLite (→ Postgres via DATABASE_URL)
                    ↘ jobs table → worker: normalize → tag → analyze (→ synthesize on demand)
```

## The pipeline agents

| Agent | Job | Output |
|---|---|---|
| Normalizer | split transcript into speaker-attributed utterances (deterministic parsers first; LLM only for messy pastes) | `utterances` rows |
| Tagger | annotate verbatim quotes with the taxonomy; quotes validated as real substrings, fabrications dropped | `highlights` (status `suggested`) |
| Analyst | per-conversation summary, pains, commitments, **Mom Test critique of the interviewer** | `analyses` row |
| Synthesizer | cross-conversation themes + contradictions over a filtered highlight set | `analyses` (kind `synthesis`) |

## Principles worth knowing before contributing

- **AI suggests, humans decide.** AI highlights land as `suggested`; only accept/reject moves them. Re-runs never touch human decisions.
- **Structured outputs everywhere.** Every agent call uses a JSON schema with a Pydantic twin; no free-text parsing.
- **Dialect-portable by rule.** Integer PKs, portable types, Alembic-only migrations, CI runs SQLite *and* Postgres. The Postgres swap is a config change.
- **Tests never call real LLMs.** A `FakeLLMClient` replays fixtures; golden files pin prompt behavior.
