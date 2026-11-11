# Retagging the corpus

Retagging replaces the AI's suggestions on every call with ones made by the improved tagger. It
spends LLM tokens on each call, so it runs in stages, and **each gate must pass before the next
step**. Everything below runs through the API from your machine over your SSH tunnel (or an https
URL); you need an **admin** login, and the scripts ask for your password (hidden).

## What a retag does, and does not, touch

- **Kept:** every highlight a person accepted or rejected, and any suggestion that a decision cites
  or a confirmed hypothesis link uses (replacing those would silently break the decision or the
  belief). Retagging reports how many it kept.
- **Replaced:** plain AI suggestions nobody has relied on. A suggested hypothesis link to one of
  those goes with it and the linker proposes new ones from the fresh tags.
- Retagged calls are stamped with the taxonomy version, which is how the rollout is resumable and
  how Library and Explore know whether a result is partial.

## The steps

**0. Set up** (once). In Settings, fill in **Your company** (name, aliases, email domains) so our
own team's lines are never tagged as customer evidence, and sharpen your custom tags'
descriptions, "don't tag when" hints and examples.

**1. Gate: the test set.** Hand-tag about 20 calls and run the tagger against them:

```bash
python scripts/eval_tagger.py path/to/testset.json --tags-json tags.json
```

Precision of 0.8 or better on the ten most-used tags. If it fails, fix the prompts and tags and run
it again; do not retag. See [`tagger-evaluation.md`](tagger-evaluation.md).

**2. Gate: known beliefs.** Check that matching finds what you know is there:

```bash
python scripts/eval_matching.py path/to/known_beliefs.json
```

See [`matching-evaluation.md`](matching-evaluation.md).

**3. Pilot.** Take a snapshot of today's tag counts, then retag the 100 newest calls:

```bash
python scripts/retag_rollout.py status
python scripts/retag_rollout.py snapshot --label "before pilot"
python scripts/retag_rollout.py batch --limit 100            # dry run first
python scripts/retag_rollout.py batch --limit 100 --yes
```

**4. Check the pilot.** Wait for `status` to show nothing in progress, then:

```bash
python scripts/retag_rollout.py compare
```

Spot-check about 10 retagged calls in conversation review. Investigate any tag flagged **JUMPED**,
**DROPPED**, **VANISHED** or **NEW** before going on: it means the new prompt or taxonomy changed
behaviour.

**5. Cost check.** `status` shows the measured seconds per call and an estimate for the rest. The
time is real; the dollar cost is yours to work out from your model's token price and a sample of
the calls' sizes. Decide before the full run.

**6. Full run.** The rest, in batches, newest first, waiting between batches:

```bash
python scripts/retag_rollout.py run --batch-size 100             # dry run: how many batches
python scripts/retag_rollout.py run --batch-size 100 --yes
```

It is resumable: if it stops for any reason, run it again and it continues with what is left. Settings
shows "N of M calls on the current taxonomy" while it runs, and Library and Explore say so when a
filtered tag has not reached every call yet.

## If something looks wrong

Stop the script (Ctrl-C). Calls already queued will finish. Nothing is lost: accepted and rejected
highlights and anything a decision or belief depends on were never touched. Fix the cause, then
run `run` again.
