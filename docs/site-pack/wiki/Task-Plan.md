# Task Plan

Development is organized as TDD (red/green) tasks in [`tasks/`](https://github.com/tmdavid/Momboard/tree/main/tasks) — each task ships its failing tests first. Conventions live in `tasks/README.md`.

## Done — T01–T23

| Milestone | Tasks | What shipped |
|---|---|---|
| M0 Scaffold | T01–T02 | app factory, async DB, Alembic, dual-dialect CI |
| M1 Schema & auth | T03–T04 | full schema, taxonomy seed, session auth, user CLI |
| M2 Ingest & jobs | T05–T08 | conversations CRUD, VTT/`Name:` normalizer, worker loop, SSE progress |
| M3–M4 LLM agents | T09–T13 | client wrapper + prompt registry, tagger + quote validator, chunking, analyst, review/reprocess |
| M5 Frontend | T14–T18 | SPA, Library, Conversation review (j/k/a/x), notes panel |
| M6 Explore | T19–T22 | cross-conversation highlights, quote wall, synthesizer, Insights |
| M7 Deploy | T23 | Docker, Fly.io, rotating backups |

## Next

| Task | What | Status |
|---|---|---|
| T24 | Google Meet auto-ingest via Drive API | not started |
| T25 | MCP server (search/get/synthesize tools for any MCP client) | not started |
| T26 | Prototype-idea generator from syntheses | designed |
| T27–T28 | **Hypothesis tracking** — falsifiable beliefs accumulating evidence | designed |
| T29–T30 | Contact-level memory + drift detection | designed |
| T31 | Weekly Slack digest | designed |
| T32–T33 | Local LLM backend + model eval harness | designed |

"Designed" = full red/green task spec exists in `tasks/M10-extensions.md` (and M6–M9 file), ready to implement. Suggested order: T27→T28, T29→T30, T31, T26; T32/T33 when privacy or cost demands.
