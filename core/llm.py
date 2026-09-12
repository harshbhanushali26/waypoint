from langchain_groq import ChatGroq
from core.config import settings

MODEL = "openai/gpt-oss-120b"


AGENT_MAX_TOKENS: dict = {
    "concierge": 650,
    "planner": 700,
    "budget": 550,
    "itinerary_builder": 3500,
    "critic": 800,
    "activity_extraction": 2000,
}


llm = ChatGroq(
    model=MODEL,
    api_key=settings.groq_api_key
)


def get_structured_llm(schema, include_raw=False, reasoning_effort=None, max_tokens=None):
    """
    Wraps llm.with_structured_output() with method="json_schema" instead of
    the default tool-calling method. gpt-oss-120b's harmony format leaks
    internal channel names (e.g. "commentary", "json") into the tool-call
    envelope under the default "function_calling" method, which Groq's
    strict tool-call validator rejects. Native json_schema mode asks the
    model directly for JSON matching the schema - no tool-calling illusion
    for those internal channels to leak into.

    Use this in every agent instead of calling llm.with_structured_output()
    directly, so the fix lives in one place.

    include_raw: when True, returns a dict {"raw": AIMessage, "parsed":
    schema instance or None, "parsing_error": ... or None} instead of a
    bare parsed schema instance - needed to inspect actual token usage
    (response["raw"].usage_metadata) or to see the raw completion when
    parsing fails (e.g. truncated output).

    reasoning_effort: per-agent override for Groq's reasoning_effort param
    ("low", "medium", "high" - "medium" is Groq's own default for
    openai/gpt-oss-120b if unset). Left as None for every agent except
    those that opt in, matching the existing per-agent AGENT_MAX_TOKENS
    pattern - a shared client setting would affect every agent, but only
    Itinerary Builder has shown token-budget pressure so far.

    max_tokens: bound onto the LLM object itself via .bind(), same
    pattern as reasoning_effort - NOT passed at .invoke() time. When
    include_raw=True, with_structured_output() wraps the LLM inside a
    RunnableParallel rather than a plain sequence, and RunnableParallel
    doesn't forward .invoke()-time kwargs down into its branches. Binding
    happens before any wrapping occurs, so it survives regardless of
    which chain shape include_raw produces - this is why reasoning_effort
    already worked but max_tokens (passed at invoke-time) silently didn't
    for itinerary_builder.
    """
    target_llm = llm
    bind_kwargs = {}
    if reasoning_effort is not None:
        bind_kwargs["reasoning_effort"] = reasoning_effort
    if max_tokens is not None:
        bind_kwargs["max_tokens"] = max_tokens
    if bind_kwargs:
        target_llm = llm.bind(**bind_kwargs)


    return target_llm.with_structured_output(schema, method="json_schema", include_raw=include_raw)