# MomBoard — TDD Task Plan

Companion to `../DESIGN.md`. One file per milestone; each task inside is one agent-sized unit of work written **red/green**:

- **RED** — write exactly these tests first. Run them. They MUST fail (compilation/import errors count as red). Do not write implementation code yet.
- **GREEN** — write the *minimum* implementation to make them pass. Run the whole suite, not just the new tests.
- **REFACTOR** — only after green, and only within the files this task touched.

## Conventions (give these to every coding agent — also mirror into repo-root `CLAUDE.md` / `AGENTS.md`)

- Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, pydantic v2, pytest + pytest-asyncio + httpx `AsyncClient`.
- Frontend: React 18 + Vite + TypeScript, TanStack Query, Tailwind. Tests: Vitest + Testing Library + MSW (mock the REST API, never the components).
- **LLM calls are never real in tests.** `app/llm/client.py` defines `LLMClient` (protocol) with the real `OpenAIResponsesClient` and a `FakeLLMClient` that replays canned JSON from `tests/fixtures/llm/`. Tests inject the fake via dependency override.
- Every Responses API structured-output schema has a Pydantic twin in `app/llm/schemas.py`; fixtures are validated against them in tests (golden-file style).
- DB tests run against SQLite locally; CI runs the same suite against SQLite **and** Postgres (testcontainers). No test may depend on autoincrement values across tables.
- Migrations: Alembic from T03 onward, never `create_all` outside tests, never edit a merged migration.
- Commits: one task per commit minimum, message `T07: worker loop with retries`.
- No new dependency without a one-line justification in the commit body.

## Fixtures to create in T06 (used everywhere after)

| file | what |
|---|---|
| `tests/fixtures/transcripts/good_interview.vtt` | Great interview: clear speakers, pains, workarounds, a commitment |
| `tests/fixtures/transcripts/compliment_disaster.txt` | "Name: text" format, interviewer pitches, customer flatters (🎈-heavy) |
| `tests/fixtures/transcripts/messy_paste.txt` | No speaker labels, wall of text |
| `tests/fixtures/llm/*.json` | Canned structured outputs for tagger/analyst/synthesizer per fixture |

## Dependency graph

```
T01 ─ T02 ─ T03 ─┬─ T04 (auth)
                 └─ T05 ─ T06 ─ T07 ─ T08 ──────────────┐
                                 │                       │
                     T09 ─ T10 ─ T11 ─ T12 ─ T13         │
                                 │                       │
        (frontend, needs API contracts only)             │
                     T14 ─┬─ T15 ─ T16                   │
                          ├─ T17 ─ T18                   │
                          └─ T20, T22 (after T19, T21)   │
                     T19 ─ T21 ─────────────────────────┤
                     T23 (deploy)  T24 (Meet)  T25 (MCP)─┘

Extensions (M10, after core is green): T27─T28 (hypotheses) · T29─T30 (contact memory)
                                       T31 (digest, needs T19) · T26 (prototype ideas, needs T21)
```

T14–T18 can start as soon as T05/T08's OpenAPI contract is merged (develop against MSW mocks); they do not block on T09–T13.

## Visual prototypes

Static, self-contained HTML mockups in `../prototypes/`. They are the **spec for look, layout, and interaction** of the frontend tasks — sample data included, no build step, just open in a browser:

| prototype | implemented by |
|---|---|
| `prototypes/library.html` | T15, T16 |
| `prototypes/conversation.html` | T17, T18 |
| `prototypes/explore.html` | T20 |
| `prototypes/insights.html` | T22 |
| `prototypes/hypotheses.html` | T28 |
| `prototypes/contact.html` | T30 |

Fidelity contract: match layout, component structure, empty/loading states, and keyboard interactions. Colors/spacing may be tokenized in Tailwind config rather than copied literally.
