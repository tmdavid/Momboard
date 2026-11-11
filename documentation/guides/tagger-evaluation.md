# Measuring the tagger

Run this after every change to the tagger prompt or the taxonomy, and **before any full
retag**. The rule: precision of **0.8 or better on the ten most-used tags**.

```bash
python scripts/eval_tagger.py path/to/testset.json
python scripts/eval_tagger.py path/to/testset.json --tags-json tags.json \
    --company-name "Your Company" --alias "YourCo" --domain yourco.com
```

Exit code `0` = gate passed, `1` = failed (do not retag), `2` = the test set or setup is wrong.

It tags every call in the set with your **real configured LLM** (so it costs a few LLM calls
per call), using the same pipeline as production: speaker sides, the filler filter, and
one-tag-per-quote all apply. It works in a throwaway database in a temporary directory and
never touches your data.

## The test set

A JSON file. Hand-tag about 20 calls (any mix of companies). For each call list the
utterances in order and the highlights a careful person would make.

```json
{
  "version": 1,
  "description": "free text",
  "calls": [
    {
      "id": "call-01",
      "interviewer": "Rep",
      "company": "Client Co",
      "meta": {},
      "utterances": [
        {"speaker": "Rep",  "side": "us",   "text": "How do you handle the weekly report?"},
        {"speaker": "Dana", "side": "them", "text": "Every Monday I export it to Excel and clean it by hand"}
      ],
      "expected": [
        {"utterance_idx": 1, "tag_key": "workaround"}
      ]
    }
  ]
}
```

- `side` is `us`, `them` or `unknown`. Mark our own team as `us`: the tagger must not tag them.
- `utterance_idx` is the 0-based position in `utterances`.
- A prediction is correct when the **same tag** lands on the **same utterance**. The exact quote
  boundaries do not matter.
- Include examples of what should *not* be tagged (a rep's line, "Yes.") by simply not listing
  them: any tag the tagger puts there counts as a false positive.

`tests/fixtures/tagger_eval/example.json` is a small synthetic example.

**Keep real test sets out of the repository.** They contain customer text. Store them somewhere
private and pass the path on the command line.

## Custom tags

The throwaway database only knows the core taxonomy. To score your custom tags, save your tags
once (`GET /api/tags` while logged in) to a file and pass `--tags-json`. The evaluator reads
each tag's description, "don't tag when" hint and example, so improving those fields (Settings →
Taxonomy) is how you raise a tag's precision.

## Reading the report

| column | meaning |
|---|---|
| precision | of the highlights the tagger made with this tag, how many were expected |
| recall | of the expected highlights, how many the tagger found |
| tp / fp / fn | correct / extra / missed |

The gate checks precision only, on the ten tags your test set uses most (`--top` changes the
count, `--threshold` the bar). A top tag the tagger never produced fails: silence is not
accuracy. Recall is reported for information: fix a low-recall tag by sharpening its
description, not by lowering the bar.
