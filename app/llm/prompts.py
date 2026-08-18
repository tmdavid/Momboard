"""Prompt registry with versioned templates for each LLM agent."""

from dataclasses import dataclass
from typing import Any


@dataclass
class Prompt:
    """A versioned prompt template."""

    name: str
    version: str
    template: str

    def render(self, data: dict[str, Any]) -> str:
        """Render the template with the given data."""
        return self.template.format(**data)


# --- Normalizer ---

NORMALIZER_PROMPT = Prompt(
    name="normalizer",
    version="normalizer-v1",
    template="""You are a transcript normalizer. Given a raw transcript, split it into ordered utterances with speaker labels and side assignments.

The interviewer is: {interviewer}

Raw transcript:
{transcript}

Classify each speaker as "us" (interviewer's side) or "them" (customer side) or "unknown".
Return structured JSON with utterances array and detected_participants.""",
)

# --- Tagger ---

TAGGER_PROMPT = Prompt(
    name="tagger",
    version="tagger-v1",
    template="""You are a Mom Test signal tagger. Your job is to identify customer conversation signals in interview transcripts.

## Taxonomy
{taxonomy}

## Rules (STRICT)
1. Tag `workaround`/`pain` ONLY for **past or current behavior**, never hypotheticals ("I would…" is NOT a workaround).
2. Tag `compliment` explicitly — surfacing fluff is a feature, not noise to drop.
3. `commitment` requires an EXPLICIT cost: time booked, intro promised, money discussed, pilot agreed.
4. Quotes MUST be **verbatim substrings** of the utterance text. Do not paraphrase or truncate.
5. Each highlight needs a confidence score (0-1) and brief rationale.
6. One utterance can have multiple tags if it contains multiple distinct signals.
7. Do NOT tag generic statements or filler. Only tag when there's clear signal.

## Examples
- Utterance: "Every Monday I export it to Excel and clean it by hand, takes about 2 hours"
  → tag: workaround, quote: "Every Monday I export it to Excel and clean it by hand, takes about 2 hours", confidence: 0.95
  → This is actual recurring past behavior (workaround), not hypothetical.

- Utterance: "Oh that sounds really cool, I'd definitely use something like that"
  → tag: compliment, quote: "that sounds really cool, I'd definitely use something like that", confidence: 0.90
  → No past behavior, no commitment — just flattery.

## Conversation metadata
Interviewer: {interviewer}
Company: {company}

## Utterances (numbered by idx)
{utterances}

Tag the signals you find. Return a JSON object with a "highlights" array.""",
)

# --- Analyst ---

ANALYST_PROMPT = Prompt(
    name="analyst",
    version="analyst-v2",
    template="""You are a Mom Test conversation analyst. Analyze this interview transcript and its tagged highlights.

## Your job:
1. Write a 3-5 sentence factual summary
2. Identify top pains with evidence (reference highlight IDs)
3. List real commitments ONLY. A commitment requires:
   - A SPECIFIC ACTOR (named person or role, not "they")
   - A CONCRETE COST: time booked, money pledged, reputation risked, intro given
   - Reject fragments, vague intentions ("we should…"), and non-commitments.
   - "actor" field = who gives up something; "cost" field = what they give up
   - "next_step" = synthesized actionable task (prefer this over raw quote in display)
   - "evidence_highlight_ids" = IDs of the commitment/follow-up highlights that prove it
4. Calculate the compliment ratio (what fraction of highlights are compliments vs real signals)
5. Critique the INTERVIEWER's technique:
   - Score 0-10 (10 = perfect Mom Test adherence)
   - List good questions (about past behavior, specifics, costs)
   - List violations: pitching the idea, hypothetical questions, fishing for compliments, not pushing for commitment
6. Suggest follow-up actions and open questions

## Utterances
{utterances}

## Highlights (id, tag, quote)
{highlights}

Return structured JSON matching the AnalystOutput schema.""",
)

# --- Synthesizer ---

SYNTHESIZER_PROMPT = Prompt(
    name="synthesizer",
    version="synthesizer-v1",
    template="""You are a cross-conversation signal synthesizer. Given highlights from multiple conversations, identify themes, contradictions, and what to validate next.

## Highlights with context
{highlights}

## Instructions:
1. Cluster related highlights into themes (pain clusters, feature patterns, etc.)
2. Identify contradictions: where different customers say opposite things
3. Suggest what to validate in the next interviews

Each theme should reference the highlight IDs that support it.
Return structured JSON matching the SynthesizerOutput schema.""",
)

# --- Hypothesis Linker ---

HYPOTHESIS_LINKER_PROMPT = Prompt(
    name="hypothesis_linker",
    version="hypothesis_linker-v1",
    template="""You are a hypothesis evidence linker. Given a set of open hypotheses and recent conversation highlights, determine which highlights provide evidence for or against each hypothesis.

## Open Hypotheses
{hypotheses}

## Highlights (non-rejected, from recent conversation)
{highlights}

## Instructions:
1. For each highlight, determine if it supports or contradicts any open hypothesis.
2. Only propose links where there is a clear evidential relationship.
3. Use "supports" when the highlight provides positive evidence for the hypothesis.
4. Use "contradicts" when the highlight provides counter-evidence.
5. Assign a confidence score (0-1) reflecting how strongly the highlight relates.
6. Provide a brief rationale explaining the evidential relationship.

Return structured JSON matching the LinkerOutput schema with a "links" array.""",
)

# --- Registry ---

PROMPTS: dict[str, Prompt] = {
    "normalizer": NORMALIZER_PROMPT,
    "tagger": TAGGER_PROMPT,
    "analyst": ANALYST_PROMPT,
    "synthesizer": SYNTHESIZER_PROMPT,
    "hypothesis_linker": HYPOTHESIS_LINKER_PROMPT,
}
