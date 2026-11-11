# Checking hypothesis matching

Hypothesis matching is two stages: it **finds** candidate quotes broadly (the belief is widened
into search terms and every customer utterance is scanned, so untagged speech counts), then
**judges** them strictly (supports / contradicts / unrelated, with a reason). It keeps the
strongest, at most 2 per call and 10 overall.

Because the model is in the loop, check it against reality whenever you change matching, the
prompts or the tagger:

```bash
python scripts/eval_matching.py path/to/known_beliefs.json        # add -v to list every match
```

The bar: **each known belief returns its known call in the top 5, and at most 1 in 5 matches is
unrelated.** Exit code `0` passed, `1` failed, `2` bad input.

It is **read-only**: the database is opened read-only and the preview never saves anything. It
does spend LLM calls (roughly 10 to 20 per belief).

## The known-beliefs file

About ten beliefs whose answer you know. Real files name real calls, so **keep yours out of the
repository**.

```json
{
  "version": 1,
  "beliefs": [
    {
      "belief": "Law firms won't buy an annual plan without a pilot first",
      "segment": "law firm",
      "expected":  [{"conversation_title_contains": "Example"}],
      "unrelated": [{"conversation_title_contains": "Watch"}]
    }
  ]
}
```

- `expected`: the call(s) that really say it. A selector is `conversation_id`, or
  `conversation_title_contains`, or `company_name_contains` (all must match if you give several).
- `unrelated` (optional): calls that definitely do **not** speak to the belief. The 1-in-5 check
  only counts matches that hit one of these, so label a few obvious wrong calls per belief.
  Matches that are neither expected nor labelled are not counted either way.
- `segment` (optional): same meaning as the Segment field on the page.

Include the two beliefs that motivated this work: one that used to find nothing though a call said
it outright, and one that used to find a single quote while hundreds of examples existed.

`tests/fixtures/tagger_eval/known_beliefs_example.json` is a synthetic example.

## Notes

- There is no embedding model in MomBoard. Stage 1 is keyword search widened by terms the model
  proposes. If recall is still low on a belief, look at the search terms (run with `-v`) before
  changing anything else.
- A quote you confirm that was never tagged is saved as an accepted highlight tagged `context`, so
  decisions, integrity checks and Explore treat it like any other evidence.
- Matching ignores the seller's own team (see Settings: Your company) and filler like "Okay".
