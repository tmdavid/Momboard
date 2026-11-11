# T48 — Evidence-gated hypothesis intake (design)

*Design doc, not a task spec yet. Grounds every choice in code that already exists
(`app/models.py` hypotheses, `app/llm/linker.py`, `app/services/corpus_chat.py`,
`app/services/briefs.py`). The goal: let a human add a belief by hand, but make the
corpus either back it with evidence, show honest weak matches, or interrogate it with
Mom Test questions — never a silent empty row.*

## One-line

A manual "add a belief" front door to the existing hypothesis board that, on entry,
matches the belief against the call corpus and reports **how much the customers
actually back it**: **grounded** (proven — act on it), **weak** (a faint signal —
worth noting, not acting), or **no-evidence** (the calls don't support this — a nudge
that it may not be worth your time to represent the customer on). The belief always
saves; the corpus decides its weight, not the advocate.

## Framing: grounding is a priority gradient, not a pass/fail

The intended user is a **sales/CSM** — someone structurally incentivized to advocate
for *their* account, i.e. biased toward over-claiming what "the customer wants." The
feature's job is not to block them but to confront that bias with evidence:

- **grounded** → confirmed supporting quotes exist. Real. Carries weight downstream.
  *(v0.4: "exist" now means the PRD thresholds — 3+ quotes from 2+ companies, at most 1
  contradicting; see CHANGELOG and `app/services/hypothesis_grounding.py`.)*
- **weak** → only low-confidence matches. A whisper worth recording, not acting on.
- **no-evidence** → nothing in the calls resembles this. *This is itself the signal* —
  if no customer said anything like it, maybe it isn't important enough to spend time
  representing. Not a failure, not a to-do: a gentle "are you sure this matters?"

Crucially, **intake does not have to be a perfect gatekeeper.** The MCP/insight layer
(T26/T46) re-checks grounding at read time and simply disregards unsupported beliefs as
"no support." So intake's job is to record the belief *with an honest grounding band*;
the downstream layer does the filtering. This division of labor is what lets intake stay
non-blocking while still enforcing evidence discipline where it counts.

## Design stance: heavy judgment, zero-effort retrieval

The central tension: confirmation must be **heavy** (the user is an advocate; a false
`confirmed` is costly) but the user is a **busy sales/CSM** who won't do heavy *labor*.
These only conflict if you treat "heavy" as one dial. Split it:

- **Judgment stays heavy.** The human must look at a real quote and actively assert it
  proves the belief — per-quote, opt-in, no bulk-confirm. This is the integrity gate.
- **Effort goes to zero.** The user never *hunts* for evidence. The system surfaces the
  right 2–3 quotes beside the belief, so the task collapses to "read this, yes/no."

Consequence that makes this **load-bearing, not cosmetic**: retrieval quality is now an
**adoption lever**, not a nice-to-have. Weak retrieval (keyword `ilike` only) surfaces
mediocre candidates → the CSM has to go hunt → they won't → everything degrades to
`hunch`, systematically losing *provable* beliefs to laziness rather than to a genuine
lack of evidence. Good semantic retrieval surfaces the actual supporting quote → the
CSM judges in seconds → grounding stays attainable. So **the keyword-vs-vector question
(below) is the thing that makes heavy confirmation survivable for this user**, and
should be treated as part of the feature's core, not a fast-follow.

We accept, deliberately, that **grounded hypotheses may be the minority** — a CSM who
won't confirm one quote probably holds a belief that shouldn't carry weight, and the
MCP layer filters it anyway. The design does *not* fight that; it only ensures retrieval
never forces a genuinely-evidenced belief into `hunch` through effort alone.

## What already exists (and what we reuse verbatim)

| Need | Already in code | Reuse |
|---|---|---|
| Store a belief | `Hypothesis` (statement, segment, status, created_by) | **as-is** |
| Attach evidence | `HypothesisLink` (stance, confidence, rationale, `origin` ai\|human, `status` suggested\|confirmed\|rejected) | **as-is** — a human-confirmed match is a row with `origin="human", status="confirmed"` |
| Find matching highlights for text | `corpus_chat._retrieve_candidates(db, text, filters, limit)` | **reuse** — this *is* the matcher |
| Generate past-behavior questions | `briefs.build_brief` LLM call + the `\bwould you\b|\bwill you\b` reject-regex | **reuse the pattern** |
| Graduate a hunch when a future call brings evidence | `linker.run_hypothesis_link` already links new highlights to every **open** hypothesis on each conversation | **reuse — zero new code** |

The headline finding: **the back half of the feature already ships.** The linker runs
on every conversation and attaches evidence to open hypotheses. So a hunch saved as a
normal open hypothesis *will* get linked evidence from future calls with no new
machinery. T48 is mostly a **front door + an honesty gate**, not a new subsystem.

## The one real gap

`Hypothesis.status` is `open | supported | refuted | parked`. There is **no way to
distinguish "a belief someone typed with zero evidence" from "a well-supported open
hypothesis."** Both are `open`. That flattening is exactly what lets ungrounded fluff
hide on the board — and it's the single thing T48 must add.

**Proposal:** add a nullable `origin` to `Hypothesis` (`ai | human | import`) and a
derived, read-time **`grounding` state** — not a stored status — computed like T41
freshness. Grounding is **two-dimensional**, because support and contradiction are
independent axes (the same belief can be both supported by some customers and
contradicted by others — e.g. the synthesis's "Enagic says the portal is unreliable,
Amway relies on it"). Collapsing that onto one line would hide the most valuable
finding. From the **confirmed** links' stances:

| | no `contradicts` links | has `contradicts` links |
|---|---|---|
| **has `supports` links** | `grounded` | **`contested`** |
| **no `supports` links** | `hunch` (none) / `candidate` (only suggested) | **`refuted`** (leaning) |

- `grounded` — confirmed support, no contradiction. Carries weight downstream.
- `contested` — confirmed support **and** contradiction. Not an error — a **fault line
  to explore** (hand off to T43 segment lenses: which segment supports vs. contradicts).
- `refuted` — confirmed contradiction, no support. The calls push back; for a CSM this
  is "careful, the evidence runs against you." (`Hypothesis.status` already has
  `refuted` as a value — natural home.)
- `candidate` / `hunch` — only weak or no matches, as before.

`grounding` is computed, never written, so the existing linker graduating a hunch →
grounded (or flipping it to `contested` when a later call contradicts) needs no
status-write and no new job. (Mirrors how T41 computes freshness at read time.) The only
migration is `hypotheses.origin` + maybe a stored `validation_questions` JSON for the
hunch's prompts.

**Contradiction is first-class, by explicit decision.** A contradicted hypothesis is
*kept*, not suppressed — as long as it is **clear** (the `contested`/`refuted` band is
loud and distinct from `grounded`) and **explorable** (one click shows both stances'
quotes grouped, each linking to its conversation, with an "open as lens" to see the
segmentation). The tool surfaces the tension; the human adjudicates it.

## The intake flow

```
human types belief ("Customer X wants bulk CSV export")  [+ optional segment]
        │
        ▼
 _retrieve_candidates(belief_text, filters=segment)   ← reused corpus search
        │
        ▼
 LLM scores each candidate: does this highlight actually support the belief?
   → {highlight_id, relation: supports|contradicts|unrelated, confidence, rationale}
   (same generate()+validate shape as corpus_chat; IDs validated against candidates)
        │
    ┌───┴─────────────────────────────┬───────────────────────────────┐
  STRONG (≥1 high-conf support)     WEAK (only low-conf / few)       NONE
    │                                 │                               │
 show matches, human confirms      show as "possibly related,       generate 2-3 grounded
 ✓/✗ each → confirmed HypothesisLinks  low confidence" — human       Mom Test questions
 (origin=human). Hypothesis born    may promote to confirmed or     (reuse briefs' gen +
 GROUNDED.                          dismiss. Nothing auto-attached.  past-behavior validator)
                                      │                               │
                                      └──────────┬────────────────────┘
                                                 ▼
                                   save Hypothesis(origin=human), store the
                                   questions; grounding = candidate | hunch.
                                   The board shows the band honestly.
                                                 ▼
                              LATER: a real call produces a linking highlight →
                              existing run_hypothesis_link attaches it →
                              grounding recomputes to GROUNDED. Hunch graduates.
```

## Where the LLM is trusted vs. where code gates (the crux)

This is the part that must be right, because a false match is worse than no match.

- **Retrieval: code, not LLM.** Candidates come from `_retrieve_candidates` (SQL +
  keyword). The LLM never picks highlights from thin air — it only *scores ones we
  handed it*, and every returned `highlight_id` is validated against the candidate set
  (same drop-invalid-IDs discipline as `corpus_chat` and the linker).
- **Scoring: LLM, but advisory only.** The LLM says "this looks like support,
  conf=0.8" — it does **not** create the link. A link is only written when a **human
  confirms** (strong/weak path) or the **existing linker** confirms later. So the
  gate is human-or-deterministic, never the matcher's own say-so.
- **Thresholds: code.** `strong` vs `weak` vs `none` is a code threshold on the
  scores, tunable — not the LLM deciding its own confidence band. (We learned from the
  tagger's fuzzy `validate_quote` that "let the similarity score speak for itself" lets
  junk through; the human confirm step is the backstop.)
- **Questions: LLM + hard post-validator.** Reuse the briefs regex reject
  (`would you|will you`) and require past-behavior phrasing; regenerate once on failure.
- **Confirmation is deliberately heavy — by design, not oversight.** The user is an
  advocate with a conflict of interest (they *want* their belief validated) and a false
  `confirmed` is expensive (it feeds MCP/drafter/decisions). So confirming a match is
  **per-quote and opt-in**: no "confirm all", no pre-checked boxes, quote shown in
  context beside the belief, human actively asserts "yes, this supports it." Friction
  here is the point — it is what stops advocacy from laundering into "proven."

## API surface (thin, mostly existing)

- `POST /api/hypotheses/intake {statement, segment?}` → runs match, returns
  `{hypothesis_candidate, matches:[{highlight_id, quote, relation, confidence}],
  grounding_preview, suggested_questions?}` — **does not save yet**; it's a preview.
- `POST /api/hypotheses` (existing or extended) → commits the hypothesis with the
  human's confirmed matches (as `HypothesisLink origin=human status=confirmed`) and the
  stored questions. `origin=human`.
- Confirm/dismiss individual matches → create/patch `HypothesisLink` (routes likely
  already exist for the board).

## Honest failure modes / open questions (need prototyping, not guessing)

1. **Retrieval quality is load-bearing (see "Design stance").** `_retrieve_candidates`
   is keyword `ilike` + fallback-to-recent; a belief phrased differently from the quotes
   under-matches → false "no evidence," which under heavy-judgment/zero-effort means the
   CSM gives up and the belief degrades to `hunch`. Since good retrieval is what makes
   heavy confirmation survivable, this is **not** a fast-follow: either prove keyword is
   good enough by measuring false-emptiness on the ~200-conversation corpus, or commit to
   semantic/pgvector retrieval as part of T48. The honest default: build the flow on
   keyword, measure, and gate the release on the false-emptiness rate being acceptable.
2. **Threshold calibration is empirical.** Where `strong`/`weak`/`none` sit can only be
   tuned against real data (we have ~200 conversations to calibrate on). Don't hardcode
   a number in the spec; make it a setting and tune.
3. **The questions becoming busywork.** If every hunch spawns 3 questions nobody
   answers, the feature is nagware. Mitigation (from T41's philosophy): questions are a
   visible *nudge*, skipping is allowed but marks the hypothesis `hunch` on the board —
   social/visual pressure, not a hard wall.
4. **Contradiction at the intake moment** (now a first-class state, see "one real gap").
   The remaining risk is *tone*: when a CSM types a belief and the best matches
   contradict it, the moment is confrontational ("you think X; listen to this"). The UX
   must read as **valuable intelligence, not a scolding** — e.g. "⚠ Worth knowing before
   you commit — some calls point the other way:" + the contradicting quotes. The belief
   still saves (as `contested`/`refuted`), with the contradicting evidence attached. The
   win: it didn't block the belief, it made the counter-evidence visible at the exact
   moment the belief was forming.
5. **Dedup against existing hypotheses.** A typed belief may restate an existing
   hypothesis. Intake should also match against open hypotheses (not just highlights)
   and offer "this looks like hypothesis #N — add evidence to it instead?"

## Why this is a good v0.3 citizen

Small surface (one migration column + a derived band + a preview endpoint + a UI flow),
reuses four shipped subsystems, and the hardest part (graduation) is already built. The
risk is concentrated in one place — match honesty — which the human-confirm gate and
code-side thresholds contain. It earns its "evidence or nothing, on the input side"
half of the v0.3 theme without a new object to maintain.

## Small adjacent improvement: link evidence back to the source Clari call

T48's whole value is traceability — a hypothesis cites highlights, highlights belong to
a conversation. For Clari-imported conversations we can close the last link in that
chain: back to the **original recorded call**. The identifier already exists — the
importer stamps `meta.source_ref = "clari:<call_id>"` (used for dedupe). This is just
surfacing it:

- When a conversation's `meta.source_ref` has the `clari:` prefix, render a "View in
  Clari" link in the conversation header (and anywhere evidence provenance is shown).
- URL is a template over the call ID (e.g. the Clari Copilot call URL pattern);
  configurable, defaults off if unknown. No schema change — read-only use of existing
  `meta`.

Scope note: this is really a **Clari-importer / conversation-provenance** improvement,
not T48 proper — but it strengthens the evidence chain T48 depends on (belief → quote →
conversation → *the actual call recording*), so it's tracked here. Cheap: one computed
link, no migration, no new data.
