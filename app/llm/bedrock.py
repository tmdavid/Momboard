"""AWS Bedrock LLM client via the Converse API with tool-use JSON enforcement.

Bedrock/Anthropic has no OpenAI-style ``strict`` structured-output mode, so this
client enforces the output schema by declaring a single tool whose ``inputSchema``
is the Pydantic JSON schema and forcing ``toolChoice`` to it. The model's tool-use
input is then validated against the Pydantic model, with the same exact → repair
retry loop the Ollama client uses.

Credentials are resolved from the standard AWS provider chain (instance role, SSO,
environment). Nothing in this module reads or stores access keys. Using an EU region
plus an ``eu.`` inference profile keeps inference within the EU footprint.
"""

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.client import LLMEnvelope, LLMSchemaError
from app.llm.prompts import PROMPTS
from app.llm.seller import with_seller

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Name of the synthetic tool used to coerce structured output.
_TOOL_NAME = "emit_structured_output"


class BedrockClient:
    """Bedrock Converse API client with forced tool-use structured output.

    Implements the same ``LLMClient`` protocol as ``OpenAIResponsesClient`` and
    ``OllamaClient``: ``structured()``, ``generate()``, and ``close()``.
    """

    def __init__(
        self,
        region: str,
        model_map: dict[str, str] | None = None,
        default_model: str = "eu.anthropic.claude-haiku-5-5",
        timeout: float = 120.0,
        session: Any = None,
    ):
        self.region = region
        self.model_map = model_map or {}
        self.default_model = default_model
        self.timeout = timeout
        # model_name is read by simulator/lenses/briefs for provenance; expose the
        # default so callers that pass model=getattr(llm, "model_name", None) work.
        self.model_name = default_model
        # Lazily created aioboto3 session; injectable for tests so no real AWS call
        # is ever made.
        self._session = session

    def _get_session(self) -> Any:
        if self._session is None:
            import aioboto3

            self._session = aioboto3.Session()
        return self._session

    def _resolve_model(self, key: str) -> str:
        return self.model_map.get(key, self.default_model)

    @staticmethod
    def _tool_spec(schema: type[T]) -> dict[str, Any]:
        """Build a Converse toolConfig that forces the model to emit the schema."""
        json_schema = schema.model_json_schema()
        return {
            "tools": [
                {
                    "toolSpec": {
                        "name": _TOOL_NAME,
                        "description": (
                            f"Return the result as a {schema.__name__} object. "
                            "Call this tool exactly once with the full result."
                        ),
                        "inputSchema": {"json": json_schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": _TOOL_NAME}},
        }

    @staticmethod
    def _extract_tool_input(response: dict[str, Any]) -> dict[str, Any] | None:
        """Pull the forced tool's input object out of a Converse response."""
        message = response.get("output", {}).get("message", {})
        for block in message.get("content", []):
            tool_use = block.get("toolUse")
            if tool_use and tool_use.get("name") == _TOOL_NAME:
                tool_input = tool_use.get("input")
                if isinstance(tool_input, dict):
                    return tool_input
        return None

    async def _converse(
        self,
        model_id: str,
        messages: list[dict[str, Any]],
        tool_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Single Converse call. Isolated so tests can stub the client."""
        session = self._get_session()
        async with session.client(
            "bedrock-runtime",
            region_name=self.region,
        ) as client:
            response: dict[str, Any] = await client.converse(
                modelId=model_id,
                messages=messages,
                toolConfig=tool_config,
            )
            return response

    async def _run(
        self,
        model_id: str,
        rendered_prompt: str,
        schema: type[T],
    ) -> T:
        """Call Converse, validate, and repair-retry once on schema failure."""
        tool_config = self._tool_spec(schema)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"text": rendered_prompt}]}
        ]

        response = await self._converse(model_id, messages, tool_config)
        tool_input = self._extract_tool_input(response)

        first_error: Exception | None = None
        if tool_input is not None:
            try:
                return schema.model_validate(tool_input)
            except ValidationError as e:
                first_error = e
                logger.warning("Bedrock schema validation failed on first attempt: %s", e)
        else:
            first_error = LLMSchemaError("No tool-use block in Bedrock response")
            logger.warning("Bedrock response contained no tool-use block")

        # Repair retry: echo the model's (invalid) output back with the error.
        assistant_content: list[dict[str, Any]] = []
        if tool_input is not None:
            assistant_content = [
                {"text": f"Previous attempt: {json.dumps(tool_input)}"}
            ]
        repair_messages = messages + [
            {"role": "assistant", "content": assistant_content or [{"text": "(no output)"}]},
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "Your previous response did not match the required schema. "
                            f"Error: {first_error}. Call the "
                            f"{_TOOL_NAME} tool again with corrected, valid data."
                        )
                    }
                ],
            },
        ]

        response = await self._converse(model_id, repair_messages, tool_config)
        tool_input = self._extract_tool_input(response)
        if tool_input is None:
            raise LLMSchemaError("No tool-use block in Bedrock repair response")
        try:
            return schema.model_validate(tool_input)
        except ValidationError as second_error:
            raise LLMSchemaError(
                f"Bedrock schema validation failed after repair retry: {second_error}"
            )

    async def structured(
        self, prompt_name: str, input_data: dict[str, Any], schema: type[T]
    ) -> tuple[T, LLMEnvelope]:
        """Call Bedrock with a registered prompt + structured output."""
        prompt = PROMPTS.get(prompt_name)
        if prompt is None:
            raise ValueError(f"Unknown prompt: {prompt_name}")

        model_id = self._resolve_model(prompt_name)
        rendered = prompt.render(input_data)

        parsed = await self._run(model_id, rendered, schema)

        envelope = LLMEnvelope(
            response_id="bedrock",
            model=model_id,
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
        """Free-form prompt → structured output.

        ``model`` is an agent key (e.g. "brief", "lens") resolved through the
        model map, matching the OpenAI/Ollama ``generate()`` contract.
        """
        model_id = self._resolve_model(model)
        return await self._run(model_id, with_seller(prompt), schema)

    async def close(self) -> None:
        """No persistent client is held between calls; nothing to release."""
        return None
