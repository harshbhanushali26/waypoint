"""
core/llm.py — Dual-Model Architecture for Groq
----------------------------------------------
- Fast tier: openai/gpt-oss-20b for Concierge, Planner, Budget, Activity Extraction
- Reasoning tier: openai/gpt-oss-120b (reasoning_effort="low") for Itinerary Builder & Critic
"""

from langchain_groq import ChatGroq
from core.config import settings

MODEL_FAST = "openai/gpt-oss-20b"
MODEL_REASONING = "openai/gpt-oss-120b"

AGENT_MAX_TOKENS: dict = {
    "concierge": 650,
    "planner": 700,
    "budget": 550,
    "itinerary_builder": 4000,
    "critic": 800,
    "activity_extraction": 2000,
}

# Fast model (20B): independent 8,000 TPM bucket, zero reasoning overhead
llm_fast = ChatGroq(
    model=MODEL_FAST,
    api_key=settings.groq_api_key,
)

# Reasoning model (120B): reasoning_effort="low" keeps thinking tokens to ~300
llm_reasoning = ChatGroq(
    model=MODEL_REASONING,
    api_key=settings.groq_api_key,
    reasoning_effort="low",
)


def get_structured_llm(
    schema,
    include_raw=False,
    model_tier="fast",
    model_type=None,
    reasoning_effort=None,
    max_tokens=None,
    **kwargs,
):
    """
    Selects between the fast (20b) and reasoning (120b) tiers.
    Accepts both `model_tier` and `model_type` for full backward compatibility.
    """
    tier = model_type or model_tier
    target_llm = llm_reasoning if tier in ("reasoning", "120b") else llm_fast

    bind_kwargs = {}
    if max_tokens is not None:
        bind_kwargs["max_tokens"] = max_tokens
    if reasoning_effort is not None:
        bind_kwargs["reasoning_effort"] = reasoning_effort

    if bind_kwargs:
        target_llm = target_llm.bind(**bind_kwargs)

    return target_llm.with_structured_output(
        schema, 
        method="json_schema", 
        include_raw=include_raw
    )