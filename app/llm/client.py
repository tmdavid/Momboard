"""LLM client implementations: protocol, OpenAI Responses API, and Fake for testing."""

import json
import logging
from pathlib import Path
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.prompts import PROMPTS

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMSchemaError(Exception):
    """Raised when LLM response doesn't match the expected schema."""

    pass


def _make_schema_strict(schema: dict) -> None:
    """Normalize a Pydantic JSON schema for OpenAI strict structured outputs.

    OpenAI requires every object property to be required, forbids additional
    properties, and rejects Pydantic's ``default`` annotations (nullable values
    remain represented by ``anyOf`` with ``null``).
    """
    schema.pop("default", None)
    if schema.get("type") == "object" or "properties" in schema:
        schema["additionalProperties"] = False
        if "properties" in schema:
            schema["required"] = list(schema["properties"].keys())
    for key in ("properties", "$defs"):
        if key in schema:
            for prop in schema[key].values():
                if isinstance(prop, dict):
                    _make_schema_strict(prop)
    if "items" in schema and isinstance(schema["items"], dict):
        _make_schema_strict(schema["items"])
    if "$ref" not in schema:
        for key in ("allOf", "anyOf", "oneOf"):
            if key in schema:
                for item in schema[key]:
                    if isinstance(item, dict):
                        _make_schema_strict(item)


class LLMEnvelope(BaseModel):
    """Metadata envelope returned with every LLM call."""

    response_id: str = ""
    model: str = ""
    prompt_version: str = ""
    data: Any = None


class LLMClient(Protocol):
    """Protocol for LLM clients — both structured() and generate() must be supported."""

    async def structured(
        self, prompt_name: str, input_data: dict[str, Any], schema: type[T]
    ) -> tuple[T, LLMEnvelope]:
        """Call LLM with registered prompt + structured output."""
        ...

    async def generate(
        self,
        prompt: str,
        schema: type[T],
        model: str = "default",
    ) -> T:
        """Free-form prompt → structured output (used by brief/chat/digest)."""
        ...

    async def close(self) -> None:
        """Release resources (httpx client etc.)."""
        ...


class OpenAIResponsesClient:
    """Real OpenAI Responses API client using httpx."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model_map: dict[str, str] | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_map = model_map or {}
        self._client = httpx.AsyncClient(
            timeout=120.0,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def structured(
        self, prompt_name: str, input_data: dict[str, Any], schema: type[T]
    ) -> tuple[T, LLMEnvelope]:
        """Call OpenAI Responses API with strict JSON schema output."""
        prompt = PROMPTS.get(prompt_name)
        if prompt is None:
            raise ValueError(f"Unknown prompt: {prompt_name}")

        model = self.model_map.get(prompt_name, "gpt-4o")
        rendered = prompt.render(input_data)

        json_schema = schema.model_json_schema()
        _make_schema_strict(json_schema)
        payload = {
            "model": model,
            "input": rendered,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema.__name__,
                    "schema": json_schema,
                    "strict": True,
                }
            },
        }

        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = await self._client.post(
                    f"{self.base_url}/responses",
                    json=payload,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < retries - 1:
                        import asyncio

                        await asyncio.sleep(2**attempt)
                        continue
                response.raise_for_status()
                break
            except httpx.HTTPStatusError:
                if attempt == retries - 1:
                    raise
                import asyncio

                await asyncio.sleep(2**attempt)

        assert response is not None
        resp_data = response.json()
        response_id = resp_data.get("id", "")

        output_text = ""
        for item in resp_data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text", "")

        if not output_text:
            raise LLMSchemaError("No output text in response")

        try:
            parsed = schema.model_validate_json(output_text)
        except (ValidationError, json.JSONDecodeError) as e:
            raise LLMSchemaError(f"Response doesn't match schema: {e}")

        envelope = LLMEnvelope(
            response_id=response_id,
            model=model,
            prompt_version=prompt.version,
            data=parsed,
        )

        return parsed, envelope

    async def generate(
        self,
        prompt: str,
        schema: type[T],
        model: str = "default",
    ) -> T:
        """Free-form prompt → structured output via Responses API.

        Same protocol as FakeLLMClient.generate — no interface divergence.
        """
        resolved_model = self.model_map.get(model, "gpt-4o")

        json_schema = schema.model_json_schema()
        _make_schema_strict(json_schema)

        payload = {
            "model": resolved_model,
            "input": [{"role": "user", "content": prompt}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema.__name__,
                    "schema": json_schema,
                    "strict": True,
                }
            },
        }

        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = await self._client.post(
                    f"{self.base_url}/responses",
                    json=payload,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < retries - 1:
                        import asyncio

                        await asyncio.sleep(2**attempt)
                        continue
                response.raise_for_status()
                break
            except httpx.HTTPStatusError:
                if attempt == retries - 1:
                    raise
                import asyncio

                await asyncio.sleep(2**attempt)

        assert response is not None
        resp_data = response.json()

        output_text = ""
        for item in resp_data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text", "")

        if not output_text:
            raise LLMSchemaError("No output text in response")

        try:
            return schema.model_validate_json(output_text)
        except (ValidationError, json.JSONDecodeError) as e:
            raise LLMSchemaError(f"Response doesn't match schema: {e}")

    async def close(self) -> None:
        await self._client.aclose()


class FakeLLMClient:
    """Fake LLM client that replays fixture files for testing."""

    def __init__(self, fixtures: dict[str, Any] | None = None):
        self._fixtures = fixtures or {}
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def from_dir(cls, path: str | Path) -> "FakeLLMClient":
        """Load all .json files from a directory as fixtures keyed by filename stem."""
        fixtures: dict[str, Any] = {}
        p = Path(path)
        if p.exists():
            for f in p.glob("*.json"):
                with open(f) as fh:
                    fixtures[f.stem] = json.load(fh)
        return cls(fixtures)

    def set_fixture(self, prompt_name: str, data: dict[str, Any]) -> None:
        """Set a fixture for a specific prompt."""
        self._fixtures[prompt_name] = data

    async def structured(
        self, prompt_name: str, input_data: dict[str, Any], schema: type[T]
    ) -> tuple[T, LLMEnvelope]:
        """Return fixture data validated against the schema."""
        self.calls.append({"prompt_name": prompt_name, "input_data": input_data})

        fixture = self._fixtures.get(prompt_name)
        if fixture is None:
            raise ValueError(
                f"No fixture for prompt '{prompt_name}'. "
                f"Available: {list(self._fixtures.keys())}"
            )

        try:
            parsed = schema.model_validate(fixture)
        except ValidationError as e:
            raise LLMSchemaError(f"Fixture doesn't match schema: {e}")

        prompt = PROMPTS.get(prompt_name)
        version = prompt.version if prompt else "fake-v0"

        envelope = LLMEnvelope(
            response_id="fake-response-id",
            model="fake-model",
            prompt_version=version,
            data=parsed,
        )

        return parsed, envelope

    async def generate(
        self,
        prompt: str,
        schema: type[T],
        model: str = "default",
    ) -> T:
        """Free-form prompt → structured output (test fake).

        Looks up fixture by model name or schema name. Falls back to
        default-constructed instance. Same signature as OpenAIResponsesClient.generate.
        """
        self.calls.append({"prompt": prompt[:200], "model": model, "schema": schema.__name__})

        # Try to find a fixture by model name or schema name
        fixture = self._fixtures.get(model) or self._fixtures.get(schema.__name__.lower())
        if fixture is not None:
            try:
                return schema.model_validate(fixture)
            except ValidationError:
                pass

        # Return default-constructed schema
        return schema.model_construct()

    async def close(self) -> None:
        """No-op for fake client."""
        pass
