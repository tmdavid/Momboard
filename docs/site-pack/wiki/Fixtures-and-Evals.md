# Fixtures and Evals

Eight hand-written, anonymized transcripts under `fixtures/` — realistic brand-protection-industry interviews with small talk, filler, planted signals, and deliberate interviewer mistakes. They power demos, tests, prompt iteration, and the T33 model evals.

## The two personas

**Marta — enforcement specialist (4 files).** Heavy platform user drowning *after* detection: the "hydra" seller network, an inherited 1,800-row alias sheet, test-buy dossiers, agency spend. Thread evolves Aug→Oct: the queue sit-in with Jonas, a September check-in (gray-market enforcement un-stopped after a distributor escalation; sheet migrated to Airtable), and a messy phone-debrief paste with no speaker labels — the fixture that must trigger LLM normalization.

- `enforcement_heavy_user.vtt` · `enforcement_f1_queue_sitin.vtt` · `enforcement_f2_september_checkin.txt` · `enforcement_f3_phone_debrief_paste.txt`

**Priya — head of brand protection, reporting-driven (4 files).** Quarterly twenty minutes in front of the CFO decide her budget; Diego rebuilds everything from CSVs (`join_hell_v7.xlsx`). Thread evolves Aug→Nov: the one-pager sit-in, the renewal memo (her handmade time-to-takedown metric becomes a standing KPI), and the renewal outcome call.

- `reporting_options.txt` · `reporting_f1_onepager_sitin.txt` · `reporting_f2_memo_debrief.txt` · `reporting_f3_renewal_outcome.vtt`

## What's deliberately planted

Every file carries labeled-by-design material: ⚡ pains and ➡️ workarounds grounded in past behavior, 💰 with real numbers, 🤝 commitments that close (or slip) in later calls, 🎈 compliments that should be flagged as zero-signal, one interviewer pitch-slip for the critique to catch, statement drift across calls ("legal approves everything" → "we file directly now"), and a recurring belief ("nothing unlocks budget like an angry distributor") for the synthesizer to spot across conversations.

## Using them for evals (T33)

Hand-label expected highlights per file once (~30 min), then the harness scores any model against them: per-tag precision/recall, verbatim-quote validity, schema failure rate. That labeled set is the spec for "good tagging" — rerun it on every prompt or model change.
