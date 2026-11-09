"""Bedrock backend tests: factory routing, model map, Converse tool-use, repair retry.

No real AWS calls are made. The aioboto3 Session is replaced with a fake that
returns canned Converse responses, and the factory's credential probe is monkey-
patched so backend selection is deterministic.
"""

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.llm.bedrock import BedrockClient
from app.llm.client import LLMSchemaError
from app.llm.schemas import TaggerOutput

FIXTURES = Path(__file__).parent / "fixtures" / "llm"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / f"{name}.json") as fh:
        return json.load(fh)


# ── Fake aioboto3 session ────────────────────────────────────────────────────


class _FakeConverseClient:
    """Stands in for the bedrock-runtime client as an async context manager."""

    def __init__(self, responses: list[dict]):
        self._responses = responses
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def converse(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("converse() called more times than stubbed")
        return self._responses.pop(0)


class _FakeSession:
    """Fake aioboto3.Session whose .client() yields canned Converse responses."""

    def __init__(self, responses: list[dict]):
        self._responses = responses
        self.client_instances: list[_FakeConverseClient] = []
        self.client_kwargs: list[dict] = []

    def client(self, service_name: str, **kwargs):
        self.client_kwargs.append({"service_name": service_name, **kwargs})
        inst = _FakeConverseClient(self._responses)
        self.client_instances.append(inst)
        return inst


def _tool_use_response(payload: dict) -> dict:
    """Build a Converse response whose forced tool returns `payload`."""
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {"name": "emit_structured_output", "input": payload}}
                ],
            }
        },
        "stopReason": "tool_use",
    }


def _bedrock_settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        llm_backend="bedrock",
        env="test",
    )
    base.update(overrides)
    return Settings(**base, _env_file=None)


# ── Factory routing & model map ──────────────────────────────────────────────


def test_factory_selects_bedrock_when_credentials_present(monkeypatch):
    import app.llm.factory as factory

    monkeypatch.setattr(factory, "_has_aws_credentials", lambda: True)
    client = factory.create_llm_client(_bedrock_settings(), agent="tagger")
    assert isinstance(client, BedrockClient)
    assert client.region == "eu-central-1"
    assert client.default_model == "eu.anthropic.claude-haiku-5-5"


def test_factory_falls_back_to_fake_without_credentials(monkeypatch):
    import app.llm.factory as factory
    from app.llm.client import FakeLLMClient

    monkeypatch.setattr(factory, "_has_aws_credentials", lambda: False)
    client = factory.create_llm_client(_bedrock_settings(), agent="tagger")
    assert isinstance(client, FakeLLMClient)


def test_bedrock_model_map_covers_all_agent_keys(monkeypatch):
    import app.llm.factory as factory

    monkeypatch.setattr(factory, "_has_aws_credentials", lambda: True)
    client = factory.create_llm_client(_bedrock_settings(), agent="tagger")
    assert isinstance(client, BedrockClient)
    # Every consumer key must resolve, defaulting to Haiku 5.5.
    for key in factory.ALL_AGENT_KEYS:
        assert client.model_map[key] == "eu.anthropic.claude-haiku-5-5"
    # The two previously-unlabeled features are present as distinct keys.
    assert "simulator" in client.model_map
    assert "lens" in client.model_map


def test_bedrock_per_agent_override_is_independent(monkeypatch):
    """Tag on Haiku, brief on Sonnet — overrides apply per agent, others unchanged."""
    import app.llm.factory as factory

    monkeypatch.setattr(factory, "_has_aws_credentials", lambda: True)
    settings = _bedrock_settings(bedrock_model_brief="eu.anthropic.claude-sonnet-5-5")
    client = factory.create_llm_client(settings, agent="tagger")
    assert isinstance(client, BedrockClient)
    assert client.model_map["brief"] == "eu.anthropic.claude-sonnet-5-5"
    assert client.model_map["tagger"] == "eu.anthropic.claude-haiku-5-5"
    assert client.model_map["lens"] == "eu.anthropic.claude-haiku-5-5"


# ── Converse tool-use path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_structured_uses_forced_tool_and_returns_fixture():
    fixture = _load_fixture("tagger")
    session = _FakeSession([_tool_use_response(fixture)])
    client = BedrockClient(region="eu-central-1", session=session)

    result, env = await client.structured(
        "tagger",
        {"taxonomy": "", "utterances": "", "interviewer": "", "company": ""},
        TaggerOutput,
    )

    assert isinstance(result, TaggerOutput)
    assert env.model == "eu.anthropic.claude-haiku-5-5"

    # Verify the request forced the structured-output tool and hit bedrock-runtime.
    call = session.client_instances[0].calls[0]
    assert call["modelId"] == "eu.anthropic.claude-haiku-5-5"
    tool_cfg = call["toolConfig"]
    assert tool_cfg["toolChoice"] == {"tool": {"name": "emit_structured_output"}}
    assert tool_cfg["tools"][0]["toolSpec"]["name"] == "emit_structured_output"
    assert session.client_kwargs[0]["service_name"] == "bedrock-runtime"
    assert session.client_kwargs[0]["region_name"] == "eu-central-1"


@pytest.mark.asyncio
async def test_structured_repairs_after_invalid_first_response():
    invalid = _tool_use_response({"highlights": "not a list"})
    valid = _tool_use_response(_load_fixture("tagger"))
    session = _FakeSession([invalid, valid])
    client = BedrockClient(region="eu-central-1", session=session)

    result, _ = await client.structured(
        "tagger",
        {"taxonomy": "", "utterances": "", "interviewer": "", "company": ""},
        TaggerOutput,
    )
    assert isinstance(result, TaggerOutput)
    # Two Converse calls: initial + repair (each opens a fresh client instance).
    total_calls = sum(len(c.calls) for c in session.client_instances)
    assert total_calls == 2


@pytest.mark.asyncio
async def test_structured_raises_after_second_failure():
    invalid = _tool_use_response({"highlights": "still wrong"})
    session = _FakeSession([invalid, dict(invalid)])
    client = BedrockClient(region="eu-central-1", session=session)

    with pytest.raises(LLMSchemaError):
        await client.structured(
            "tagger",
            {"taxonomy": "", "utterances": "", "interviewer": "", "company": ""},
            TaggerOutput,
        )


@pytest.mark.asyncio
async def test_missing_tool_block_raises_after_repair():
    empty = {"output": {"message": {"role": "assistant", "content": [{"text": "hi"}]}}}
    session = _FakeSession([empty, dict(empty)])
    client = BedrockClient(region="eu-central-1", session=session)

    with pytest.raises(LLMSchemaError):
        await client.structured(
            "tagger",
            {"taxonomy": "", "utterances": "", "interviewer": "", "company": ""},
            TaggerOutput,
        )


@pytest.mark.asyncio
async def test_generate_resolves_model_from_map():
    """generate(model='brief') must route to the brief model, not the default."""
    session = _FakeSession([_tool_use_response(_load_fixture("tagger"))])
    client = BedrockClient(
        region="eu-central-1",
        model_map={"brief": "eu.anthropic.claude-sonnet-5-5"},
        session=session,
    )

    await client.generate(prompt="Summarize.", schema=TaggerOutput, model="brief")

    call = session.client_instances[0].calls[0]
    assert call["modelId"] == "eu.anthropic.claude-sonnet-5-5"


def test_model_name_attribute_exposed_for_provenance():
    """simulator/lenses/briefs read getattr(llm, 'model_name', None)."""
    client = BedrockClient(region="eu-central-1", default_model="eu.anthropic.claude-haiku-5-5")
    assert client.model_name == "eu.anthropic.claude-haiku-5-5"
