# Mom Test Taxonomy

The signal system MomBoard tags conversations with — adapted from the note-taking symbols at the back of *The Mom Test*, stored as seed data in the `tags` table (extend it in Admin without code changes).

| key | emoji | marks | signal strength |
|---|---|---|---|
| `pain` | ⚡ | a problem they actually have | strong |
| `obstacle` | 🧱 | what blocks them from solving it | strong |
| `workaround` | ➡️ | what they already do to cope — past behavior | **very strong** |
| `emotion_pos` | 😄 | genuine excitement | strong |
| `emotion_neg` | 😠 | anger / embarrassment | strong |
| `context` | 🎯 | facts about their world, team, process | medium |
| `feature_request` | ☐ | what they *say* they want — treat skeptically | weak |
| `money` | 💰 | budgets, willingness to pay, buying process | strong |
| `person` | 👤 | someone or some company to talk to next | medium |
| `followup` | ☆ | something *we* must do next | n/a |
| `commitment` | 🤝 | gave up time, reputation, or money | **very strong** |
| `compliment` | 🎈 | "sounds great, I'd totally use it" | **anti-signal** |

## Tagging rules the LLM is held to

- `workaround` and `pain` require **past or current behavior** — "I would…" is a hypothetical, not a workaround.
- `commitment` requires an explicit cost: time booked, an intro promised, money discussed, a pilot agreed.
- Compliments are tagged, not dropped — surfacing fluff is the point. The Insights page tracks your compliment ratio and celebrates when it falls.
- Quotes must be verbatim substrings of the utterance; fabricated quotes are rejected in code.

## The interviewer critique

Beyond tagging the customer, the analyst grades **you**: did you ask about the past or pitch the future, did you fish for compliments, did you push for commitment? Each conversation gets a 0–10 score with cited violations and suggested better questions.
