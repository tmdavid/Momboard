"""T32 RED: Ollama client, config, and factory tests for local LLM hosting.

Tests verify:
- Backend selection via settings (openai vs local/ollama)
- Ollama native client sends correct format field with JSON schema
- Per-agent backend overrides route calls independently
- Schema violation triggers repair retry then LLMSchemaError
- Context budget from settings drives chunk size
- Factory creates correct client based on settings
- No real network calls (all mocked with respx)
"""

import json

import httpx
import pytest
import respx

from app.config import Settings
from app.llm.schemas import TaggerOutput


def test_backend_selected_by_settings():
    """LLM_BACKEND setting should determine which client is created."""
    from app.llm.factory import create_llm_client

    # Test openai backend selection
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="sk-test",
        env="test",
    )
    client = create_llm_client(settings, agent="tagger")
    from app.llm.client import OpenAIResponsesClient

    assert isinstance(client, OpenAIResponsesClient)


def test_local_backend_requires_base_url():
    """When LLM_BACKEND=local, LLM_BASE_URL must be set."""
    from app.llm.factory import create_llm_client

    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        llm_backend="local",
        llm_base_url="",
        env="test",
    )

    with pytest.raises(ValueError, match="LLM_BASE_URL must be set"):
        create_llm_client(settings, agent="tagger")


def test_per_agent_backend_override():
    """Local factory routes all agents to LLM_LOCAL_MODEL, not OpenAI model names."""
    from app.llm.factory import create_llm_client
    from app.llm.local import OllamaClient

    # Even though llm_model_tagger is set to a GPT model, the local backend
    # should use llm_local_model for all agents.
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        llm_backend="local",
        llm_base_url="http://ollama:11434",
        llm_local_model="qwen3:8b",
        llm_model_tagger="gpt-4o",
        llm_model_analyst="gpt-4o",
        env="test",
    )

    for agent in ("tagger", "analyst", "synthesizer", "normalizer"):
        client = create_llm_client(settings, agent=agent)
        assert isinstance(client, OllamaClient)
        # The model_map must contain qwen3:8b for every agent, not gpt-4o
        assert client.model_map[agent] == "qwen3:8b"
        assert client.model == "qwen3:8b"


def test_local_factory_defaults_to_qwen3_8b():
    """Local backend defaults to qwen3:8b when LLM_LOCAL_MODEL is not explicitly set."""
    from app.llm.factory import create_llm_client
    from app.llm.local import OllamaClient

    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        llm_backend="local",
        llm_base_url="http://ollama:11434",
        env="test",
    )

    # Default LLM_LOCAL_MODEL should be qwen3:8b
    assert settings.llm_local_model == "qwen3:8b"

    client = create_llm_client(settings, agent="tagger")
    assert isinstance(client, OllamaClient)
    assert client.model == "qwen3:8b"
    assert client.model_map == {
        "normalizer": "qwen3:8b",
        "tagger": "qwen3:8b",
        "analyst": "qwen3:8b",
        "synthesizer": "qwen3:8b",
    }


def test_local_factory_custom_model_override():
    """LLM_LOCAL_MODEL can be overridden to use a different model for all agents."""
    from app.llm.factory import create_llm_client
    from app.llm.local import OllamaClient

    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        llm_backend="local",
        llm_base_url="http://ollama:11434",
        llm_local_model="llama3.1:8b",
        env="test",
    )

    client = create_llm_client(settings, agent="tagger")
    assert isinstance(client, OllamaClient)
    assert client.model == "llama3.1:8b"
    assert all(m == "llama3.1:8b" for m in client.model_map.values())


def test_local_factory_passes_configured_timeout():
    """LLM_LOCAL_TIMEOUT should control the Ollama HTTP request timeout."""
    from app.llm.factory import create_llm_client
    from app.llm.local import OllamaClient

    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        llm_backend="local",
        llm_base_url="http://ollama:11434",
        llm_local_timeout=1800.0,
        env="test",
    )

    client = create_llm_client(settings, agent="tagger")
    assert isinstance(client, OllamaClient)
    assert client.timeout == 1800.0


def test_openai_model_settings_independent_of_local():
    """OpenAI per-agent model settings remain independent when backend=openai."""
    from app.llm.client import OpenAIResponsesClient
    from app.llm.factory import create_llm_client

    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="sk-test-key",
        llm_backend="openai",
        llm_model_tagger="gpt-4o",
        llm_model_analyst="gpt-4o-mini",
        llm_model_normalizer="gpt-4o-mini",
        llm_model_synthesizer="gpt-4o",
        llm_local_model="qwen3:8b",  # Should be ignored for OpenAI
        env="test",
    )

    client = create_llm_client(settings, agent="tagger")
    assert isinstance(client, OpenAIResponsesClient)
    # OpenAI client should use per-agent models, not the local model
    assert client.model_map["tagger"] == "gpt-4o"
    assert client.model_map["analyst"] == "gpt-4o-mini"
    assert client.model_map["normalizer"] == "gpt-4o-mini"
    assert client.model_map["synthesizer"] == "gpt-4o"


@pytest.mark.asyncio
@respx.mock
async def test_ollama_native_client_sends_format_field():
    """Ollama native client uses 'format' field with JSON schema for structured output."""
    try:
        from app.llm.local import OllamaClient
    except ImportError:
        pytest.fail("app.llm.local.OllamaClient not found")

    # Mock Ollama API
    endpoint = respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"highlights": []}),
                },
                "done": True,
            },
        )
    )

    client = OllamaClient(base_url="http://localhost:11434", model="qwen3:8b")
    try:
        result, envelope = await client.structured(
            "tagger",
            {
                "taxonomy": "- pain: problems",
                "utterances": "[0] David: hi",
                "interviewer": "David",
                "company": "Acme",
            },
            TaggerOutput,
        )

        # Verify the request
        assert endpoint.called
        request_body = json.loads(endpoint.calls[0].request.content)

        # Ollama uses 'format' field for JSON schema constraint
        assert "format" in request_body
        # Format should contain the JSON schema
        format_schema = request_body["format"]
        assert format_schema.get("type") == "object"
        assert "properties" in format_schema

        # Verify model is sent
        assert request_body["model"] == "qwen3:8b"

        # Structured extraction should avoid Qwen's expensive thinking mode on local CPUs
        assert request_body["think"] is False

        # Result validates
        assert isinstance(result, TaggerOutput)
    finally:
        if hasattr(client, "close"):
            await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_ollama_schema_violation_triggers_repair_retry():
    """On schema validation failure, Ollama client retries once with error feedback."""
    try:
        from app.llm.local import OllamaClient
    except ImportError:
        pytest.fail("app.llm.local.OllamaClient not found")

    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call returns invalid schema
            return httpx.Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"highlights": "not a list"}),
                    },
                    "done": True,
                },
            )
        else:
            # Repair retry returns valid schema
            return httpx.Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"highlights": []}),
                    },
                    "done": True,
                },
            )

    respx.post("http://localhost:11434/api/chat").mock(side_effect=side_effect)

    client = OllamaClient(base_url="http://localhost:11434", model="qwen3:8b")
    try:
        result, _ = await client.structured(
            "tagger",
            {
                "taxonomy": "",
                "utterances": "",
                "interviewer": "",
                "company": "",
            },
            TaggerOutput,
        )
        assert isinstance(result, TaggerOutput)
        # Should have made 2 calls: first failed validation, second succeeded
        assert call_count == 2
    finally:
        if hasattr(client, "close"):
            await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_ollama_second_schema_failure_raises_llm_schema_error():
    """After repair retry also fails, LLMSchemaError is raised."""
    try:
        from app.llm.local import OllamaClient
    except ImportError:
        pytest.fail("app.llm.local.OllamaClient not found")

    from app.llm.client import LLMSchemaError

    # Always return invalid schema
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"highlights": "invalid forever"}),
                },
                "done": True,
            },
        )
    )

    client = OllamaClient(base_url="http://localhost:11434", model="qwen3:8b")
    try:
        with pytest.raises(LLMSchemaError):
            await client.structured(
                "tagger",
                {
                    "taxonomy": "",
                    "utterances": "",
                    "interviewer": "",
                    "company": "",
                },
                TaggerOutput,
            )
    finally:
        if hasattr(client, "close"):
            await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_ollama_no_auth_header_sent():
    """Ollama client should NOT send Authorization header (local model)."""
    try:
        from app.llm.local import OllamaClient
    except ImportError:
        pytest.fail("app.llm.local.OllamaClient not found")

    endpoint = respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": json.dumps({"highlights": []})},
                "done": True,
            },
        )
    )

    client = OllamaClient(base_url="http://localhost:11434", model="qwen3:8b")
    try:
        await client.structured(
            "tagger",
            {
                "taxonomy": "",
                "utterances": "",
                "interviewer": "",
                "company": "",
            },
            TaggerOutput,
        )

        auth_header = endpoint.calls[0].request.headers.get("authorization")
        assert auth_header is None, "Ollama client should not send auth header"
    finally:
        if hasattr(client, "close"):
            await client.close()


def test_ollama_config_settings_fields():
    """Settings should have Ollama-related configuration fields."""
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        env="test",
        llm_max_context=32768,
        _env_file=None,
    )
    # Test that new settings fields exist:
    required_fields = [
        "llm_backend",
        "llm_base_url",
        "llm_local_flavor",
        "llm_local_model",
        "llm_max_context",
    ]
    missing = [f for f in required_fields if not hasattr(settings, f)]
    assert not missing, (
        f"Settings is missing required Ollama config fields: {missing}. "
        f"Add llm_backend, llm_base_url, llm_local_flavor, llm_local_model, "
        f"llm_max_context to Settings."
    )
    # Verify defaults
    assert settings.llm_local_model == "qwen3:8b"
    assert settings.llm_backend == "openai"
    assert settings.llm_max_context == 32768


def test_context_budget_from_settings_drives_chunk_size():
    """LLM_MAX_CONTEXT setting should influence the chunking of long transcripts."""
    try:
        from app.llm.tagging import calculate_chunk_size
    except ImportError:
        pytest.fail(
            "app.llm.tagging.calculate_chunk_size does not exist. "
            "This function should calculate optimal chunk size based on context budget."
        )

    # With a small context (8192), chunks should be smaller
    small_ctx_size = calculate_chunk_size(max_context=8192)
    # With default context (32k), chunks can be larger
    large_ctx_size = calculate_chunk_size(max_context=32768)

    assert (
        small_ctx_size < large_ctx_size
    ), f"Small context ({small_ctx_size}) should produce smaller chunks than large ({large_ctx_size})"
    # Reasonable bounds
    assert 20 <= small_ctx_size <= 60
    assert 40 <= large_ctx_size <= 120


@pytest.mark.asyncio
@respx.mock
async def test_ollama_full_schema_preserves_nullable_anyof_and_enum():
    """Ollama format field must preserve full JSON Schema including nullable/anyOf and enum.

    Regression test: previous implementation whitelisted only type/properties/required/$defs/items,
    which dropped anyOf (used by Pydantic for Optional fields) and enum definitions.
    """
    from enum import StrEnum

    from pydantic import BaseModel as PydanticBaseModel

    from app.llm.local import OllamaClient
    from app.llm.prompts import PROMPTS, Prompt

    # Define a schema with nullable field (generates anyOf) and enum
    class Priority(StrEnum):
        low = "low"
        medium = "medium"
        high = "high"

    class TestSchema(PydanticBaseModel):
        name: str
        priority: Priority
        description: str | None = None  # Generates anyOf: [{type: string}, {type: null}]

    # Register a temporary test prompt
    test_prompt = Prompt(name="test_schema", version="v1", template="{data}")
    PROMPTS["test_schema"] = test_prompt

    try:
        valid_response = json.dumps(
            {
                "name": "task1",
                "priority": "high",
                "description": None,
            }
        )

        endpoint = respx.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": valid_response},
                    "done": True,
                },
            )
        )

        client = OllamaClient(base_url="http://localhost:11434", model="qwen3:8b")
        try:
            result, _ = await client.structured("test_schema", {"data": "test"}, TestSchema)

            assert endpoint.called
            request_body = json.loads(endpoint.calls[0].request.content)
            format_schema = request_body["format"]

            # Verify nullable field (anyOf) is preserved in properties
            desc_prop = format_schema.get("properties", {}).get("description", {})
            # Pydantic v2 uses anyOf for Optional fields
            assert (
                "anyOf" in desc_prop or desc_prop.get("type") == "string" or "default" in desc_prop
            ), f"Optional[str] field schema was lost. Got: {desc_prop}"

            # Verify enum is preserved
            priority_prop = format_schema.get("properties", {}).get("priority", {})
            # Pydantic renders enum as allOf/$ref or inline enum
            has_enum = (
                "enum" in priority_prop
                or "$ref" in priority_prop
                or "allOf" in priority_prop
                or ("$defs" in format_schema and "Priority" in format_schema["$defs"])
            )
            assert has_enum, (
                f"Enum schema was lost. priority prop: {priority_prop}, "
                f"$defs: {format_schema.get('$defs', {})}"
            )

            # Verify the result validates correctly
            assert result.name == "task1"
            assert result.priority == Priority.high
            assert result.description is None
        finally:
            await client.close()
    finally:
        del PROMPTS["test_schema"]
