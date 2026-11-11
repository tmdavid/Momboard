# Design principles and risks

Lasting guidance that came out of the v0.2 and v0.3 release plans. What each release shipped is in
[`CHANGELOG.md`](../../CHANGELOG.md); the original architecture is in [`architecture.md`](architecture.md).

## Principles

- **Evidence or nothing.** MomBoard is the *evidence layer*: a grounded source of truth that people and
  agents build on. Everything it shows or exposes rests on real customer quotes, and it refuses ungrounded
  input: a belief added by hand either cites calls or is flagged as a hunch with a plan to validate it.
- **Citation or silence.** Every insight, answer, brief and MCP payload carries the highlight IDs it rests
  on. No ungrounded claims cross the boundary.
- **Degrade honestly.** On a small or empty corpus, briefs, chat and MCP insights return empty sections or a
  "not enough evidence" answer, never padding. A downstream agent will treat what we expose as ground truth.
- **Human in the loop.** AI proposes (suggested tags, suggested links, drafts); a person accepts. Nothing an
  agent writes is promoted automatically.
- **Stay in your lane.** MomBoard feeds design, planning and ticketing tools; it does not become them.
- **No required-click regression.** The core Library and Conversation flow gains no mandatory step. New
  surfaces are opt-in, and anything that adds a required click gets cut.
- **Nothing team-specific in the public repo.** Real customer text, company names and hand-tagged test sets
  stay outside it; the repo ships synthetic examples.

## Risks to keep watching

- **Source format drift.** Google can change the Meet transcript layout. Keep parsers pinned to fixtures and
  fail into the inbox with a `parse_error` status instead of dropping data.
- **Fuzzy matching.** Matching a typed belief to highlights is approximate. Weak matches are shown as
  low-confidence candidates with a human confirm step, never auto-attached as proof (a false match is worse
  than none), and a phrasing mismatch must not wrongly report "no evidence". Validation questions are
  generated from the specific belief and pass the past-behaviour validator, or they become busywork.
- **Drafter over-reach.** Anything that drafts from the corpus must never promote its own output or invent
  evidence. The review queue and citation validation are the guardrails, not polish.
- **Taxonomy sprawl.** Overlapping custom tags dilute the tagger. Prefer a small, sharp set with clear
  "don't tag when" hints (see [`guides/tagger-evaluation.md`](../guides/tagger-evaluation.md)).
- **Scale.** The schema is PostgreSQL-compatible; moving off single-file SQLite is the step before
  high-volume, continuous ingestion. It is infrastructure work, not a user feature.
