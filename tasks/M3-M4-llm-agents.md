# M3 — LLM module & tagger · M4 — Analyst & reprocess

## T09 — LLM client wrapper + prompt registry

**Depends on:** T01 (isolated module; parallel-safe with T05–T08)

**RED** — `tests/test_llm_client.py`

```python
def test_prompt_registry_returns_versioned_prompt():
    p = registry.get("tagger")
    assert p.version.startswith("tagger-v") and "{taxonomy}" in p.template

@pytest.mark.asyncio
async def test_openai_client_sends_strict_json_schema(respx_mock):
    # mock the /v1/responses HTTP call; assert text.format type=json_schema, strict=True,
    # and that response.output json is validated against the pydantic twin
    ...

@pytest.mark.asyncio
async def test_schema_violation_raises_LLMSchemaError(respx_mock): ...

@pytest.mark.asyncio
async def test_fake_client_replays_fixture():
    fake = FakeLLMClient.from_dir("tests/fixtures/llm")
    out = await fake.structured("tagger", input=..., schema=TaggerOutput)
    assert isinstance(out, TaggerOutput)
```

**GREEN**

- `app/llm/client.py`: `LLMClient` protocol → `structured(prompt_name, input, schema) -> BaseModel`; `OpenAIResponsesClient` (httpx, retries on 429/5xx, records `response.id`, model, prompt_version into a returned envelope); `FakeLLMClient`.
- `app/llm/prompts/` : one file per agent, `PROMPTS` registry with explicit version strings (bump on any wording change).
- `app/llm/schemas.py`: `NormalizerOutput`, `TaggerOutput`, `AnalystOutput`, `SynthesizerOutput` (Pydantic, mirrored to JSON Schema for the API call via `.model_json_schema()`).
- Model names per agent from settings (`LLM_MODEL_TAGGER` etc.).

---

## T10 — Tagger agent + verbatim-quote validator

**Depends on:** T08, T09
**This is the heart of the product — spend the prompt effort here.**

**RED** — `tests/test_tagger.py`

```python
@pytest.mark.asyncio
async def test_tagger_persists_suggested_highlights(db_session, convo_good, fake_llm):
    await run_tag(db_session, convo_good.id, llm=fake_llm)
    hs = await highlights_for(convo_good)
    assert all(h.origin == "ai" and h.status == "suggested" for h in hs)
    assert {"workaround", "pain", "commitment"} <= {h.tag_key for h in hs}

def test_verbatim_validator_accepts_exact_substring(): ...
def test_verbatim_validator_fuzzy_matches_minor_whitespace(): ...   # normalize spaces/quotes
def test_verbatim_validator_drops_fabricated_quote_with_warning(caplog):
    # quote not in utterance → highlight dropped, warning logged with utterance_idx

@pytest.mark.asyncio
async def test_unknown_tag_key_from_llm_is_dropped_not_crashing(db_session, fake_llm_bad_tag): ...

@pytest.mark.asyncio
async def test_taxonomy_is_loaded_from_db_including_custom_tags(db_session, fake_llm):
    # add custom tag `competitor_mention`; assert it appears in the rendered prompt input
```

**GREEN**

- `run_tag`: load utterances + active tags → render prompt (numbered utterances, taxonomy with definitions and the Mom Test rules from DESIGN.md §5.2) → `llm.structured(...)` → validate quotes (exact, then fuzzy: casefold + collapse whitespace + strip curly quotes; drop below 0.9 ratio) → bulk insert `suggested` highlights → store envelope (response id, model, prompt_version) on each highlight row (add columns or a JSON `provenance` field — pick JSON).
- Prompt rules encoded as explicit bullet constraints; include 2 few-shot examples (one hypothetical-vs-past-behavior contrast, one compliment).

---

## T11 — Chunking for long transcripts

**Depends on:** T10

**RED** — `tests/test_chunking.py`

```python
def test_chunks_of_80_utterances_with_10_overlap(): ...
def test_highlights_deduped_on_utterance_and_tag_across_chunks():
    # same (utterance_idx, tag_key) from two chunks → one highlight, max confidence wins
@pytest.mark.asyncio
async def test_short_transcript_is_single_call(fake_llm_spy): ...
```

**GREEN** — pure chunker + dedupe in `app/llm/tagging.py`; `run_tag` iterates chunks sequentially (rate-limit friendly).

---

## T12 — Analyst agent

**Depends on:** T10

**RED** — `tests/test_analyst.py`

```python
@pytest.mark.asyncio
async def test_analysis_row_created_with_expected_shape(db_session, convo_good, fake_llm):
    await run_analyze(db_session, convo_good.id, llm=fake_llm)
    a = await analysis_for(convo_good)
    out = AnalystOutput.model_validate(a.result)      # schema twin validates stored JSON
    assert 0 <= out.mom_test_critique.score <= 10
    assert a.prompt_version and a.model

@pytest.mark.asyncio
async def test_analyst_input_includes_only_non_rejected_highlights(fake_llm_spy): ...

@pytest.mark.asyncio
async def test_evidence_highlight_ids_must_exist(db_session, fake_llm_bad_ids):
    # unknown ids are stripped; analysis still saved; warning logged
```

**GREEN** — `run_analyze` per DESIGN.md §5.3; input = utterances + accepted/suggested highlights (ids included so the model can reference them); validate evidence ids post-hoc.

---

## T13 — Highlight review + reprocess

**Depends on:** T10

**RED** — `tests/test_review_and_reprocess.py`

```python
@pytest.mark.asyncio
async def test_patch_highlight_accept_reject_edit_retag(auth_client): ...
@pytest.mark.asyncio
async def test_manual_highlight_creation_origin_human_status_accepted(auth_client): ...

@pytest.mark.asyncio
async def test_reprocess_replaces_suggested_but_preserves_human_decisions(auth_client, fake_llm):
    # accept one, reject one, leave one suggested → POST /reprocess
    # → accepted & rejected untouched; suggested replaced by new run
    ...

@pytest.mark.asyncio
async def test_reprocess_enqueues_tag_then_analyze(auth_client): ...
```

**GREEN** — `PATCH /api/highlights/{id}`, `POST /api/conversations/{id}/highlights`, `POST /api/conversations/{id}/reprocess`. Idempotency rule: delete-where `origin='ai' AND status='suggested'` only.
