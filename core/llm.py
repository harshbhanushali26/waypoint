# from langchain_groq import ChatGroq
# from core.config import settings

# MODEL = "openai/gpt-oss-120b"

# AGENT_MAX_TOKENS: dict = {
#     "concierge": 1000,
#     "planner": 1000,
#     "budget": 1500,
#     "itinerary_builder": 3200, 
#     "critic": 800,
# }


# llm = ChatGroq(
#     model=MODEL,
#     api_key=settings.groq_api_key
# )


# def get_structured_llm(schema, include_raw=False):
#     """
#     Wraps llm.with_structured_output() with method="json_schema" instead of
#     the default tool-calling method. gpt-oss-120b's harmony format leaks
#     internal channel names (e.g. "commentary", "json") into the tool-call
#     envelope under the default "function_calling" method, which Groq's
#     strict tool-call validator rejects. Native json_schema mode asks the
#     model directly for JSON matching the schema - no tool-calling illusion
#     for those internal channels to leak into.

#     Use this in every agent instead of calling llm.with_structured_output()
#     directly, so the fix lives in one place.

#     include_raw: when True, returns a dict {"raw": AIMessage, "parsed":
#     schema instance or None, "parsing_error": ... or None} instead of a
#     bare parsed schema instance - needed to inspect actual token usage
#     (response["raw"].usage_metadata) or to see the raw completion when
#     parsing fails (e.g. truncated output).
#     """
#     return llm.with_structured_output(schema, method="json_schema", include_raw=include_raw)


from langchain_groq import ChatGroq
from core.config import settings

MODEL = "openai/gpt-oss-120b"

AGENT_MAX_TOKENS: dict = {
    "concierge": 1000,
    "planner": 1000,
    "budget": 1500,
    "itinerary_builder": 5000, 
    "critic": 800,
}


llm = ChatGroq(
    model=MODEL,
    api_key=settings.groq_api_key
)


def get_structured_llm(schema, include_raw=False, reasoning_effort=None):
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
    """
    target_llm = llm
    if reasoning_effort is not None:
        target_llm = llm.bind(reasoning_effort=reasoning_effort)

    return target_llm.with_structured_output(schema, method="json_schema", include_raw=include_raw)