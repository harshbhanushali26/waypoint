"""
core/llm.py — Dual-Model Architecture for Groq
----------------------------------------------
- Fast tier: openai/gpt-oss-20b for Planner, Budget, Activity Extraction
- Reasoning tier: openai/gpt-oss-120b for Itinerary Builder & Critic

max_tokens / reasoning_effort / temperature are set on the ChatGroq object itself.
Binding them and then calling with_structured_output() silently drops them.
"""

from langchain_groq import ChatGroq
from core.config import settings

MODEL_FAST = "openai/gpt-oss-20b"
MODEL_REASONING = "openai/gpt-oss-120b"

# Groq counts max_tokens toward the TPM pre-flight check, so these are a
# budget as well as a ceiling. input + max_tokens must stay under 8,000.
AGENT_MAX_TOKENS: dict = {
    "concierge": 650,
    "planner": 700,
    "budget": 550,
    "itinerary_builder": 2800,
    "critic": 800,
    "activity_extraction": 2500,
}

DEFAULT_TEMPERATURE = {"fast": 0.2, "reasoning": 0.4}


def _build_llm(tier: str, max_tokens, reasoning_effort, temperature) -> ChatGroq:
    is_reasoning = tier in ("reasoning", "120b")
    return ChatGroq(
        model=MODEL_REASONING if is_reasoning else MODEL_FAST,
        api_key=settings.groq_api_key,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort or "low",
        temperature=(
            temperature if temperature is not None
            else DEFAULT_TEMPERATURE["reasoning" if is_reasoning else "fast"]
        ),
    )


# Kept for any module that imports them directly.
llm_fast = _build_llm("fast", None, "low", None)
llm_reasoning = _build_llm("reasoning", None, "low", None)


def get_structured_llm(
    schema,
    include_raw=False,
    model_tier="fast",
    model_type=None,
    reasoning_effort=None,
    max_tokens=None,
    temperature=None,
    **kwargs,
):
    """
    Selects the fast (20b) or reasoning (120b) tier and returns a structured-output runnable.
    Accepts both `model_tier` and `model_type` for backward compatibility.
    """
    tier = model_type or model_tier
    llm = _build_llm(tier, max_tokens, reasoning_effort, temperature)
    return llm.with_structured_output(
        schema,
        method="json_schema",
        include_raw=include_raw,
    )