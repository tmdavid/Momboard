# MomBoard — Positioning One-Pager

*The single source of truth for the website. Every section below maps 1:1 to a landing-page section, in order. Copy is final-draft quality — edit voice, keep structure.*

---

## 1. Hero

**Headline:** Your customers already told you what to build. It's buried in your call notes.

**Subhead:** MomBoard turns raw interview transcripts into tagged, searchable evidence — pains, workarounds, budgets, commitments — using the signal system from *The Mom Test*. And it grades *you* on how well you interviewed.

**CTA (primary):** Get started — self-hosted & free
**CTA (secondary):** See a tagged conversation →  *(links to a live read-only demo conversation)*

**Hero visual:** the Conversation view — a real transcript with ⚡➡💰🤝 chips inline and the critique score card visible. Not an illustration; the actual product.

---

## 2. Problem (the "this is you" section)

**Header:** The customer interview graveyard

Three columns, each a recognizable sin:

- **The spreadsheet.** One row per call, a link to a doc nobody reopens. Six months of interviews you can't search, compare, or trust.
- **The highlight reel in your head.** You remember the quotes that flattered your idea and forget the ones that didn't. Your product decisions inherit that bias.
- **The compliment trap.** "I'd totally use this!" feels like validation. It's noise. The signal — what people already *do*, pay for, and commit to — gets zero structure in your notes.

**Closing line:** You read The Mom Test. Your note-taking didn't.

---

## 3. How it works (three steps, product screenshots)

1. **Drop in a transcript.** Paste, upload a .txt/.vtt, or (soon) pull straight from Google Meet. Metadata takes ten seconds.
2. **Signals get tagged, you stay in charge.** An LLM annotates verbatim quotes with the Mom Test taxonomy — every tag lands as a *suggestion* you accept or reject with one key. Nothing enters your evidence base unreviewed.
3. **Ask your entire interview history anything.** Filter every quote by tag, company, or date. Synthesize themes across conversations. Watch hypotheses accumulate evidence — or die.

*(Screenshots: Library → Conversation review mode → Explore quote wall)*

---

## 4. The taxonomy strip

A horizontal band showing the emoji system with one-line meanings — it's the brand:

⚡ pain · 🧱 obstacle · ➡️ workaround · 💰 money · 🤝 commitment · 👤 intro · ☆ follow-up · 🎈 compliment *(tagged so you stop counting it as validation)*

---

## 5. Differentiators (the three things nobody else does)

- **It grades the interviewer.** Every conversation gets a Mom Test critique: did you ask about the past or pitch the future? Did you fish for compliments? Score 3/10 on your first call, 8/10 by your tenth — the tool makes you better at the craft, not just the filing.
- **Compliments are counted as anti-signal.** Other tools summarize "positive feedback." MomBoard tracks your compliment ratio and celebrates when it *drops*.
- **Hypotheses, not folders.** State a falsifiable belief. Every new conversation's evidence attaches for or against it. Product decisions point at a meter, not a vibe.

---

## 6. Privacy / self-hosted (the trust section)

**Header:** Your customers' words never leave your machine

- Self-hosted, open source (GitHub link, license badge, star count)
- Runs on SQLite — one file, no infrastructure; Postgres when you grow
- **Works fully offline with local models** — point it at Ollama and a Qwen MoE model; a 32GB RAM machine runs the whole pipeline with zero API calls and zero per-token costs
- Or bring an OpenAI key for maximum tagging quality. Mix both, per pipeline stage.

---

## 7. For teams (secondary audience, brief)

Contact timelines ("everything Acme ever told us"), drift alerts when a customer contradicts last quarter, a Friday digest of new commitments and overdue follow-ups in Slack. Built for the founder; grows into the research team's memory.

---

## 8. Social proof (placeholder until real)

At launch, replace testimonials with honesty — it's on-brand:

> "We track commitments, not compliments. Current scoreboard: ★ N stars · N real deployments · N compliments (worthless, but flattering)."

Later: two real quotes from users, each tagged with its own emoji (a 🤝 quote beats a 🎈 quote — live the brand).

---

## 9. FAQ (the five real questions)

- **Is my data used to train anything?** No. Self-hosted, your database, your models if you want.
- **Do I need a GPU?** No. CPU + 32GB RAM runs a local MoE model fine; tagging is a background job, speed doesn't matter.
- **What if the AI tags wrong?** Everything is a suggestion until you accept it. Review is keyboard-first and takes about a minute per call.
- **Is this affiliated with The Mom Test / Rob Fitzpatrick?** No — inspired by the book's note-taking system, with attribution. (Buy the book. Seriously.)
- **What does it cost?** The software is free and open source. You pay your own LLM costs (or nothing, locally). A hosted version may come later — tell us if you'd commit to that. 🤝

---

## 10. Footer CTA

**Header:** Stop archiving interviews. Start interrogating them.
**CTA:** `git clone` + quickstart link · GitHub · X/Twitter

---

## Voice & style notes for whoever builds this

- Tone: founder-to-founder, dry, self-aware; never corporate. The 🎈 joke does more positioning work than any feature list.
- Every claim ties to a shipped feature — no "AI-powered insights" vapor. If it's roadmap, label it "soon."
- Visual language: reuse the product's design tokens (the light `#f9f9f7` page, `#2a78d6` accent, emoji chips) so the site *is* a screenshot of the product before the first screenshot appears.
- One page, no nav dropdowns, no cookie-banner drama (self-hosted product, static site, no trackers — say so in the footer, it's a feature).
