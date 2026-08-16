# MomBoard Wiki

A Mom Test–based customer conversation repository: ingest interview transcripts, tag signals (⚡ pains, ➡️ workarounds, 💰 money, 🤝 commitments), review them human-in-the-loop, and interrogate your whole interview history — self-hosted, with local-LLM support.

**Website:** https://callcompass.xyz · **Repo:** https://github.com/tmdavid/Momboard

## Where to start

| You want to… | Read |
|---|---|
| Run it locally in 10 minutes | [[Getting Started]] |
| Understand how it's built | [[Architecture]] |
| Learn the tagging system | [[Mom Test Taxonomy]] |
| See what's done and what's next | [[Task Plan]] |
| Run it with zero API costs | [[Local LLM Setup]] |
| Test with realistic data | [[Fixtures and Evals]] |

## Status (August 2026)

Core application **T01–T23 implemented**: ingestion (paste / `Name: text` / WebVTT), normalize → tag → analyze pipeline, keyboard-first highlight review, notes, Explore + synthesis, Insights, auth, SQLite/Postgres schema, Docker/Fly deploy. Not yet: Google Meet auto-ingest (T24), MCP server (T25), and the M10 extensions (hypotheses, contact memory, digest, prototype-idea generator).

## Credits

Inspired by the note-taking system in *The Mom Test* by Rob Fitzpatrick. Not affiliated — buy the book.
