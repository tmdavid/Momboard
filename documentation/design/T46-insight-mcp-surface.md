# T46 — Insight MCP surface (read-only, grounding-aware)

*Design doc, not a task spec. Grounds every choice in the existing MCP server
(`app/mcp_server.py`, T25) and data model (`app/models.py`). The scope was narrowed in
design: MomBoard does **not** draft epics or prototypes — it exposes insights,
hypotheses, and decisions over MCP so an **external** agent (e.g. Claude artifacts) does
the drafting. MomBoard stays the evidence/insight layer.*

## One-line

Add **read-only, grounding-aware, citation-first** tools to the existing T25 MCP server
that expose syntheses, hypotheses (with strength), and decisions — so an external agent
can build docs/prototypes on verifiable customer evidence, never on vibes.

## What T25 already gives us (verified in code)

The MCP server (stdio + authenticated `POST /mcp`, signed-session-token auth, shared
service layer) exposes 7 tools: `search_conversations`, `get_conversation`,
`get_highlights`, `get_commitments`, `run_synthesis`, `create_conversation`,
`ask_corpus`. Transport, auth, and dispatch are built. So T46 is **new tools on the
existing server**, not a new server.

## What's missing (the actual T46 work)

1. **No hypothesis tools at all.** Nothing exposes beliefs or their grounding — the
   centerpiece of the "agent builds from grounded insight" vision. This is the gap.
2. **No decision tools.** Decisions (with evidence + integrity) aren't exposed.
3. **Existing tools under-expose provenance.** `get_highlights` returns
   `id/tag/quote/conversation_id` — no grounding context, no source-call link.

## Scope: four read-only tools (+ provenance on existing ones)

| Tool | Returns | Notes |
|---|---|---|
| `list_hypotheses(grounding?, segment?)` | id, statement, segment, status, **grounding band + strength counts** | filterable by grounding so an agent can ask for `grounded` only |
| `get_hypothesis(id)` | the above + its confirmed links, both stances, each with quote + conversation ref | the full evidence picture for one belief |
| `list_decisions(status?, integrity?)` | id, title, status, integrity, hypothesis_id, evidence count | expose `undermined` so agents don't build on shaky decisions |
| `get_decision(id)` | the above + rationale + cited quotes + integrity_reasons | full provenance |

All **read-only**. `create_conversation` stays as-is (conversation creation is done in
the web app for now); no new write tools. The insight surface is strictly read.

## Hypothesis strength — computed, no schema change (answers the open question)

"How strong is a hypothesis / confirmed by X quotes" is **derived by counting the
`HypothesisLink` rows that already exist** — no new column. Per hypothesis:

- `supporting = count(links where stance=supports, status=confirmed)`
- `contradicting = count(links where stance=contradicts, status=confirmed)`
- `suggested = count(links where status=suggested)` (unconfirmed candidates)

From those, the **2D grounding band** (shared with T48):

| | no confirmed contradiction | has confirmed contradiction |
|---|---|---|
| **has confirmed support** | `grounded` | `contested` |
| **no confirmed support** | `hunch` (none) / `candidate` (only suggested) | `refuted` |

So a hypothesis tool returns, e.g.:
`{statement, grounding: "contested", supporting: 3, contradicting: 2, suggested: 1}`
— honest strength, both directions, no invented score.

**Dependency on T48:** the *named grounding band* is T48's derived read-model. The raw
counts work today; the band computation ships with T48. So **T46's hypothesis tools
depend on T48's grounding function** — build T48's computation first (or together), then
T46 reuses it. (Build-order note: T48 effectively precedes T46's hypothesis tool.)

## Statuses are exposed honestly (the C concern)

The whole point: an external agent treats MCP output as ground truth, so status must
travel faithfully. Every exposed entity carries its real state, never flattened:

- highlights: `suggested` vs `accepted`
- hypothesis links: `suggested` | `confirmed` | `rejected` × `supports` | `contradicts`
- hypotheses: the grounding band + counts above (so `hunch` and `grounded` are
  distinguishable by the consumer — a `hunch` must never look `grounded`)
- decisions: `proposed` | `decided` | `superseded`, and `ok` | `undermined` with reasons

A consuming agent can then correctly weight "proven across 4 calls" vs. "one person's
hunch" vs. "customers actively disagree" — which is the difference between a doc grounded
in evidence and one that launders a guess.

## Provenance / citations (first-class)

Every returned claim/quote carries enough to trace it: `highlight_id`, `quote`,
`conversation_id`, and — when the conversation came from Clari — the source-call link
(`meta.source_ref`, the small improvement noted in T48). So an external drafter can cite
"Customer X said '…' (call on 2026-08-20)" with a working link back to the recording.

## Read-only stance (the D decision)

Insight/summary/hypothesis/decision tools are **read-only**, by explicit decision.
Conversation creation stays in the web app; no external agent writes beliefs or
conversations in through this surface (which would bypass the T48 evidence gate). The
pre-existing `create_conversation` / `run_synthesis` write tools are a separate,
earlier concern and out of scope for this read-only insight surface.

## Honest risks / open questions

1. **Trust-boundary faithfulness is the whole feature.** If a tool ever returns a
   grounding band that overstates evidence, a downstream agent drafts a confident doc on
   a hunch. The counts must be computed from confirmed links only; suggested links are
   reported separately, never folded into "supporting".
2. **Token/size of payloads.** `get_hypothesis` with all links + quotes + conversation
   context can be large. Cap and paginate; return quote text but reference (not inline)
   full conversations.
3. **Auth scope.** HTTP transport uses a signed session token = a full user. There's no
   finer-grained "read-only insight" scope. Fine for now (trusted internal agents); note
   it if external/partner agents ever consume this.
4. **Depends on T48.** The grounding band is T48's model. Sequence accordingly.

## Why this is a good v0.3 citizen

It's genuinely thin: four read tools on an existing, authed, tested MCP server, computing
strength from links that already exist — **no schema change** (the only new model is
T48's shared grounding function). It realizes the "corpus feeds other tools" half of the
v0.3 theme without MomBoard ever leaving its lane: it exposes evidence; the drafting
lives elsewhere.
