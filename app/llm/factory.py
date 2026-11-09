"""LLM client factory: dispatches on settings to create the appropriate client."""

from app.config import Settings
from app.llm.bedrock import BedrockClient
from app.llm.client import FakeLLMClient, LLMClient, OpenAIResponsesClient
from app.llm.local import OllamaClient

# Every agent/model key the codebase actually uses, across structured() pipeline
# agents and free-form generate() features. Used to build complete model maps so
# per-agent overrides are honored everywhere (not just the pipeline agents).
ALL_AGENT_KEYS = (
    # structured() pipeline agents
    "normalizer",
    "tagger",
    "analyst",
    "synthesizer",
    "hypothesis_linker",
    # free-form generate() features
    "chat",
    "corpus_chat",
    "brief",
    "digest",
    "persona",
    "simulator",
    "lens",
    "drift_checker",
)


def _seed_fake_client() -> FakeLLMClient:
    """Build a FakeLLMClient pre-seeded so the pipeline runs end-to-end without creds.

    Shared by the OpenAI (no API key) and Bedrock (no AWS credentials) fallbacks.
    """
    fake = FakeLLMClient()
    fake.set_fixture("tagger", {"highlights": []})
    fake.set_fixture(
        "normalizer",
        {"utterances": [], "detected_participants": [], "language": "en"},
    )
    fake.set_fixture(
        "analyst",
        {
            "summary": "No analysis available (no LLM credentials configured)",
            "top_pains": [],
            "commitments": [],
            "compliment_ratio": 0.0,
            "mom_test_critique": {"score": 5, "good_questions": [], "violations": []},
            "suggested_followups": [],
            "open_questions": [],
        },
    )
    fake.set_fixture(
        "synthesizer",
        {"themes": [], "contradictions": [], "validate_next": []},
    )
    fake.set_fixture("hypothesis_linker", {"links": []})
    return fake


def create_llm_client(settings: Settings, agent: str = "tagger") -> LLMClient:
    """Create an LLM client based on settings.

    Args:
        settings: Application settings.
        agent: Agent name (tagger, analyst, synthesizer, normalizer, brief, …) for
            model routing. Unused for backend selection — the backend is global.

    Returns:
        An LLM client instance implementing the LLMClient protocol.

    Raises:
        ValueError: When backend=local but no llm_base_url is configured, or when
            the backend name is unknown.
    """
    backend = settings.llm_backend

    if backend == "local":
        if not settings.llm_base_url:
            raise ValueError(
                "LLM_BASE_URL must be set when LLM_BACKEND=local. Example: http://ollama:11434"
            )
        return OllamaClient(
            base_url=settings.llm_base_url,
            model=settings.llm_local_model,
            model_map=_build_local_model_map(settings),
            timeout=settings.llm_local_timeout,
        )
    elif backend == "openai":
        if not settings.openai_api_key:
            # Fall back to fake client for dev/test when no API key.
            return _seed_fake_client()
        return OpenAIResponsesClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model_map=_build_openai_model_map(settings),
        )
    elif backend == "bedrock":
        if not _has_aws_credentials():
            # Mirror the OpenAI no-key path: keep dev/tests green without AWS.
            return _seed_fake_client()
        return BedrockClient(
            region=settings.aws_region,
            model_map=_build_bedrock_model_map(settings),
            default_model=settings.bedrock_model_default,
            timeout=settings.bedrock_timeout,
        )
    else:
        raise ValueError(
            f"Unknown LLM_BACKEND: '{backend}'. Use 'openai', 'local', or 'bedrock'."
        )


def _has_aws_credentials() -> bool:
    """Check whether the standard AWS provider chain can resolve credentials.

    Returns False (→ FakeLLMClient) when running without AWS access, so tests and
    keyless dev don't attempt real Bedrock calls.
    """
    try:
        import boto3

        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


def _build_local_model_map(settings: Settings) -> dict[str, str]:
    """Build model map for local (Ollama) backend.

    All agents default to LLM_LOCAL_MODEL (qwen3:8b) to prevent OpenAI model
    names from leaking into Ollama requests.
    """
    local_model = settings.llm_local_model
    return {key: local_model for key in ALL_AGENT_KEYS}


def _build_openai_model_map(settings: Settings) -> dict[str, str]:
    """Build model map for OpenAI backend using per-agent settings."""
    return {
        "normalizer": settings.llm_model_normalizer,
        "tagger": settings.llm_model_tagger,
        "analyst": settings.llm_model_analyst,
        "synthesizer": settings.llm_model_synthesizer,
    }


def _build_bedrock_model_map(settings: Settings) -> dict[str, str]:
    """Build a complete model map for the Bedrock backend.

    Every agent key defaults to bedrock_model_default (Claude Haiku 5.5, EU profile)
    unless a per-agent BEDROCK_MODEL_* override is set and non-empty. Covering all
    keys means any agent can be independently repointed to another model via .env
    with no code change.
    """
    default = settings.bedrock_model_default
    overrides = {
        "normalizer": settings.bedrock_model_normalizer,
        "tagger": settings.bedrock_model_tagger,
        "analyst": settings.bedrock_model_analyst,
        "synthesizer": settings.bedrock_model_synthesizer,
        "hypothesis_linker": settings.bedrock_model_hypothesis_linker,
        "chat": settings.bedrock_model_chat,
        "corpus_chat": settings.bedrock_model_corpus_chat,
        "brief": settings.bedrock_model_brief,
        "digest": settings.bedrock_model_digest,
        "persona": settings.bedrock_model_persona,
        "simulator": settings.bedrock_model_simulator,
        "lens": settings.bedrock_model_lens,
        "drift_checker": settings.bedrock_model_drift_checker,
    }
    return {key: (overrides.get(key) or default) for key in ALL_AGENT_KEYS}
