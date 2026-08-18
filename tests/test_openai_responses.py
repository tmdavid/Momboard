"""T09 RED: Mocked OpenAI Responses API — strict schema and schema error tests.

Tests verify:
- OpenAI client sends correct payload with strict JSON schema
- Response output text is validated against pydantic schema twin
- Schema violation raises LLMSchemaError
- Retries on 429/5xx
- additionalProperties: false is added recursively (strict mode requirement)
"""

import json

import httpx
import pytest
import respx

from app.llm.client import LLMSchemaError, OpenAIResponsesClient, _make_schema_strict
from app.llm.schemas import AnalystOutput, TaggerOutput


@pytest.mark.asyncio
@respx.mock
async def test_openai_client_sends_strict_json_schema():
    """Client sends text.format with type=json_schema, strict=True to /responses."""
    # Mock the OpenAI responses endpoint
    endpoint = respx.post("https://api.openai.com/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp_123",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"highlights": []}),
                            }
                        ],
                    }
                ],
            },
        )
    )

    client = OpenAIResponsesClient(api_key="test-key")
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

        # Verify the request payload
        assert endpoint.called
        request_body = json.loads(endpoint.calls[0].request.content)

        # Must have text.format.type = json_schema and strict = True
        assert request_body["text"]["format"]["type"] == "json_schema"
        assert request_body["text"]["format"]["strict"] is True
        assert request_body["text"]["format"]["name"] == "TaggerOutput"

        # Schema must have additionalProperties: false (strict mode requirement)
        schema = request_body["text"]["format"]["schema"]
        assert schema.get("additionalProperties") is False

        # Result should be a valid TaggerOutput
        assert isinstance(result, TaggerOutput)
        assert envelope.response_id == "resp_123"
        assert envelope.prompt_version.startswith("tagger-v")
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_schema_violation_raises_llm_schema_error():
    """When LLM returns invalid JSON that doesn't match schema, raises LLMSchemaError."""
    respx.post("https://api.openai.com/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp_bad",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                # Invalid: highlights should be a list, not a string
                                "text": json.dumps({"highlights": "not a list"}),
                            }
                        ],
                    }
                ],
            },
        )
    )

    client = OpenAIResponsesClient(api_key="test-key")
    try:
        with pytest.raises(LLMSchemaError, match="doesn't match schema"):
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
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_empty_output_text_raises_schema_error():
    """When response has no output text, raises LLMSchemaError."""
    respx.post("https://api.openai.com/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={"id": "resp_empty", "output": []},
        )
    )

    client = OpenAIResponsesClient(api_key="test-key")
    try:
        with pytest.raises(LLMSchemaError, match="No output text"):
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
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_429_rate_limit():
    """Client retries on 429 status before succeeding."""
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={
                "id": "resp_retry",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps({"highlights": []})}
                        ],
                    }
                ],
            },
        )

    respx.post("https://api.openai.com/v1/responses").mock(side_effect=side_effect)

    client = OpenAIResponsesClient(api_key="test-key")
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
        assert call_count == 2
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_500_server_error():
    """Client retries on 5xx errors."""
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(500, json={"error": "server error"})
        return httpx.Response(
            200,
            json={
                "id": "resp_5xx",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps({"highlights": []})}
                        ],
                    }
                ],
            },
        )

    respx.post("https://api.openai.com/v1/responses").mock(side_effect=side_effect)

    client = OpenAIResponsesClient(api_key="test-key")
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
        assert call_count == 3
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_exhausted_retries_raises():
    """After all retries exhausted, the error is raised."""
    respx.post("https://api.openai.com/v1/responses").mock(
        return_value=httpx.Response(500, json={"error": "permanent failure"})
    )

    client = OpenAIResponsesClient(api_key="test-key")
    try:
        with pytest.raises(httpx.HTTPStatusError):
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
        await client.close()


def test_make_schema_strict_adds_additional_properties_false():
    """_make_schema_strict should recursively add additionalProperties: false."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "nested": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                },
            },
        },
    }
    _make_schema_strict(schema)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["nested"]["additionalProperties"] is False
    # All properties should be required
    assert schema["required"] == ["name", "nested"]
    assert schema["properties"]["nested"]["required"] == ["x"]


@pytest.mark.asyncio
@respx.mock
async def test_analyst_output_schema_validated():
    """AnalystOutput schema twin validates correctly from API response."""
    valid_analyst = {
        "summary": "Good interview with clear pains.",
        "top_pains": [{"pain": "manual export", "evidence_highlight_ids": [1], "severity": "high"}],
        "commitments": [{"what": "15min follow-up", "type": "time", "next_step": "email"}],
        "compliment_ratio": 0.2,
        "mom_test_critique": {
            "score": 8,
            "good_questions": ["Asked about current process"],
            "violations": [],
        },
        "suggested_followups": ["Ask about timeline"],
        "open_questions": ["How many team members?"],
    }

    respx.post("https://api.openai.com/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp_analyst",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(valid_analyst)}],
                    }
                ],
            },
        )
    )

    client = OpenAIResponsesClient(api_key="test-key")
    try:
        result, envelope = await client.structured(
            "analyst",
            {
                "utterances": "...",
                "highlights": "...",
            },
            AnalystOutput,
        )
        assert isinstance(result, AnalystOutput)
        assert result.mom_test_critique.score == 8
        assert len(result.top_pains) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_auth_header_sent():
    """OpenAI client sends Authorization Bearer header."""
    endpoint = respx.post("https://api.openai.com/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp_auth",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps({"highlights": []})}
                        ],
                    }
                ],
            },
        )
    )

    client = OpenAIResponsesClient(api_key="sk-test-12345")
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
        assert auth_header == "Bearer sk-test-12345"
    finally:
        await client.close()


def test_make_schema_strict_removes_defaults_from_nullable_fields():
    """OpenAI strict mode rejects Pydantic default annotations at any depth."""
    schema = {
        "type": "object",
        "properties": {
            "actor": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
            "nested": {
                "type": "object",
                "properties": {"enabled": {"type": "boolean", "default": True}},
            },
        },
    }

    _make_schema_strict(schema)

    assert "default" not in schema["properties"]["actor"]
    assert "default" not in schema["properties"]["nested"]["properties"]["enabled"]
    assert schema["required"] == ["actor", "nested"]
    assert schema["properties"]["nested"]["required"] == ["enabled"]
