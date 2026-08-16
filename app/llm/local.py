"""Ollama local LLM client with native JSON-schema structured output."""

import json
import logging
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.client import LLMEnvelope, LLMSchemaError
from app.llm.prompts import PROMPTS

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class OllamaClient:
    """Ollama-compatible local LLM client using native JSON schema format field.

    Uses Ollama's /api/chat endpoint with the `format` field for structured output.
    Does NOT send Authorization headers (local model).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:8b",
        model_map: dict[str, str] | None = None,
        max_retries: int = 1,
        timeout: float = 300.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.model_map = model_map or {}
        self.max_retries = max_retries
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            # No auth header for local models
        )

    async def structured(
        self, prompt_name: str, input_data: dict[str, Any], schema: type[T]
    ) -> tuple[T, LLMEnvelope]:
        """Call Ollama with native JSON schema structured output.

        Args:
            prompt_name: Registered prompt name.
            input_data: Data to render into prompt template.
            schema: Pydantic model for output validation.

        Returns:
            Tuple of (validated model, envelope metadata).

        Raises:
            LLMSchemaError: If schema validation fails after repair retry.
        """
        prompt = PROMPTS.get(prompt_name)
        if prompt is None:
            raise ValueError(f"Unknown prompt: {prompt_name}")

        model = self.model_map.get(prompt_name, self.model)
        rendered = prompt.render(input_data)

        # Build JSON schema for Ollama's native `format` field
        json_schema = schema.model_json_schema()
        # Remove $defs reference indirection for simpler format compliance
        # Ollama expects a flat JSON schema in `format`
        format_schema = self._flatten_schema(json_schema)

        messages = [{"role": "user", "content": rendered}]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "format": format_schema,
            "stream": False,
            "think": False,
        }

        # First attempt
        response = await self._call(payload)
        content = response.get("message", {}).get("content", "")

        first_error: Exception | None = None
        try:
            parsed = schema.model_validate_json(content)
            return parsed, self._make_envelope(model, prompt)
        except (ValidationError, json.JSONDecodeError) as e:
            first_error = e
            logger.warning("Ollama schema validation failed on first attempt: %s", e)

        # Repair retry: add error context and ask again
        repair_messages = messages + [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    f"Your response did not match the required JSON schema. "
                    f"Error: {first_error}. Please fix and return valid JSON."
                ),
            },
        ]
        repair_payload: dict[str, Any] = {
            "model": model,
            "messages": repair_messages,
            "format": format_schema,
            "stream": False,
            "think": False,
        }

        response = await self._call(repair_payload)
        content = response.get("message", {}).get("content", "")

        try:
            parsed = schema.model_validate_json(content)
            return parsed, self._make_envelope(model, prompt)
        except (ValidationError, json.JSONDecodeError) as second_error:
            raise LLMSchemaError(f"Schema validation failed after repair retry: {second_error}")

    async def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Make a single call to Ollama /api/chat endpoint."""
        response = await self._client.post(
            f"{self.base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data: object = response.json()
        if not isinstance(data, dict):
            raise TypeError(f"Ollama returned non-dict JSON response: {type(data).__name__}")
        return data

    def _flatten_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Prepare JSON schema for Ollama format field.

        Ollama accepts full JSON Schema in the `format` field including
        $defs, anyOf, enum, nullable types, and all standard keywords.
        We pass through the complete schema to avoid lossy transformations.
        Only the 'title' and 'description' metadata keys are stripped at the
        top level since Ollama ignores them and they waste context tokens.
        """
        result = dict(schema)
        # Remove metadata-only keys that waste tokens but don't affect validation
        result.pop("title", None)
        result.pop("description", None)
        return result

    def _make_envelope(self, model: str, prompt: Any) -> LLMEnvelope:
        """Create metadata envelope."""
        return LLMEnvelope(
            response_id="ollama-local",
            model=model,
            prompt_version=prompt.version if prompt else "unknown",
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
