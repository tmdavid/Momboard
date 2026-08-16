"""LLM client factory: dispatches on settings to create the appropriate client."""

from app.config import Settings
from app.llm.client import FakeLLMClient, LLMClient, OpenAIResponsesClient
from app.llm.local import OllamaClient


def create_llm_client(settings: Settings, agent: str = "tagger") -> LLMClient:
    """Create an LLM client based on settings.

    Args:
        settings: Application settings.
        agent: Agent name (tagger, analyst, synthesizer, normalizer) for model routing.

    Returns:
        An LLM client instance implementing the LLMClient protocol.

    Raises:
        ValueError: When backend=local but no llm_base_url is configured.
    """
    backend = settings.llm_backend

    if backend == "local":
        if not settings.llm_base_url:
            raise ValueError(
                "LLM_BASE_URL must be set when LLM_BACKEND=local. Example: http://ollama:11434"
            )
        model_map = _build_local_model_map(settings)
        return OllamaClient(
            base_url=settings.llm_base_url,
            model=settings.llm_local_model,
            model_map=model_map,
            timeout=settings.llm_local_timeout,
        )
    elif backend == "openai":
        if not settings.openai_api_key:
            # Fall back to fake client for dev/test when no API key
            fake = FakeLLMClient()
            # Provide sensible defaults so pipeline runs end-to-end in tests
            fake.set_fixture("tagger", {"highlights": []})
            fake.set_fixture(
                "normalizer",
                {
                    "utterances": [],
                    "detected_participants": [],
                    "language": "en",
                },
            )
            fake.set_fixture(
                "analyst",
                {
                    "summary": "No analysis available (no API key configured)",
                    "top_pains": [],
                    "commitments": [],
                    "compliment_ratio": 0.0,
                    "mom_test_critique": {
                        "score": 5,
                        "good_questions": [],
                        "violations": [],
                    },
                    "suggested_followups": [],
                    "open_questions": [],
                },
            )
            fake.set_fixture(
                "synthesizer",
                {
                    "themes": [],
                    "contradictions": [],
                    "validate_next": [],
                },
            )
            fake.set_fixture(
                "hypothesis_linker",
                {
                    "links": [],
                },
            )
            return fake
        model_map = _build_openai_model_map(settings)
        return OpenAIResponsesClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model_map=model_map,
        )
    else:
        raise ValueError(f"Unknown LLM_BACKEND: '{backend}'. Use 'openai' or 'local'.")


def _build_local_model_map(settings: Settings) -> dict[str, str]:
    """Build model map for local (Ollama) backend.

    All agents default to LLM_LOCAL_MODEL (qwen3:8b) unless the user has
    explicitly set a per-agent LLM_MODEL_* env var that differs from the
    OpenAI defaults. This prevents OpenAI model names from leaking into
    Ollama requests.
    """
    local_model = settings.llm_local_model
    return {
        "normalizer": local_model,
        "tagger": local_model,
        "analyst": local_model,
        "synthesizer": local_model,
    }


def _build_openai_model_map(settings: Settings) -> dict[str, str]:
    """Build model map for OpenAI backend using per-agent settings."""
    return {
        "normalizer": settings.llm_model_normalizer,
        "tagger": settings.llm_model_tagger,
        "analyst": settings.llm_model_analyst,
        "synthesizer": settings.llm_model_synthesizer,
    }
