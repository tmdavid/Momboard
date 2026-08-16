"""T09: LLM client and prompt registry tests."""

from pathlib import Path

import pytest

from app.llm.client import FakeLLMClient
from app.llm.prompts import PROMPTS
from app.llm.schemas import AnalystOutput, SynthesizerOutput, TaggerOutput


def test_prompt_registry_returns_versioned_prompt():
    p = PROMPTS.get("tagger")
    assert p is not None
    assert p.version.startswith("tagger-v")
    assert "{taxonomy}" in p.template


def test_all_prompts_registered():
    assert "normalizer" in PROMPTS
    assert "tagger" in PROMPTS
    assert "analyst" in PROMPTS
    assert "synthesizer" in PROMPTS


def test_prompt_renders_with_data():
    p = PROMPTS["tagger"]
    rendered = p.render({
        "taxonomy": "- pain: problems",
        "utterances": "[0] David: hi",
        "interviewer": "David",
        "company": "Acme",
    })
    assert "pain: problems" in rendered
    assert "David" in rendered


@pytest.mark.asyncio
async def test_fake_client_replays_fixture():
    fixtures_dir = Path(__file__).parent / "fixtures" / "llm"
    fake = FakeLLMClient.from_dir(str(fixtures_dir))
    out, envelope = await fake.structured("tagger", input_data={}, schema=TaggerOutput)
    assert isinstance(out, TaggerOutput)
    assert len(out.highlights) > 0
    assert envelope.model == "fake-model"
    assert envelope.prompt_version == "tagger-v1"


@pytest.mark.asyncio
async def test_fake_client_validates_against_schema():
    fake = FakeLLMClient()
    fake.set_fixture("tagger", {"highlights": [
        {"utterance_idx": 0, "tag_key": "pain", "quote": "test", "confidence": 0.9, "rationale": "test"}
    ]})
    out, _ = await fake.structured("tagger", {}, TaggerOutput)
    assert out.highlights[0].tag_key == "pain"


@pytest.mark.asyncio
async def test_fake_client_raises_on_missing_fixture():
    fake = FakeLLMClient()
    with pytest.raises(ValueError, match="No fixture"):
        await fake.structured("nonexistent", {}, TaggerOutput)


@pytest.mark.asyncio
async def test_fake_client_records_calls():
    fake = FakeLLMClient()
    fake.set_fixture("tagger", {"highlights": []})
    await fake.structured("tagger", {"key": "value"}, TaggerOutput)
    assert len(fake.calls) == 1
    assert fake.calls[0]["prompt_name"] == "tagger"
    assert fake.calls[0]["input_data"] == {"key": "value"}


@pytest.mark.asyncio
async def test_analyst_fixture_validates():
    fixtures_dir = Path(__file__).parent / "fixtures" / "llm"
    fake = FakeLLMClient.from_dir(str(fixtures_dir))
    out, _ = await fake.structured("analyst", {}, AnalystOutput)
    assert isinstance(out, AnalystOutput)
    assert 0 <= out.mom_test_critique.score <= 10


@pytest.mark.asyncio
async def test_synthesizer_fixture_validates():
    fixtures_dir = Path(__file__).parent / "fixtures" / "llm"
    fake = FakeLLMClient.from_dir(str(fixtures_dir))
    out, _ = await fake.structured("synthesizer", {}, SynthesizerOutput)
    assert isinstance(out, SynthesizerOutput)
    assert len(out.themes) > 0
