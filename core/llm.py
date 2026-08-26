from langchain_groq import ChatGroq
from core.config import settings

MODEL = "openai/gpt-oss-120b"

AGENT_MAX_TOKENS: dict = {
    "concierge": 1000,
    "planner": 1000,
    "budget": 1500,
    "itinerary_builder": 2500,   # was 4000 — testing whether max_tokens counts toward Groq's TPM check
    "critic": 800,
}


llm = ChatGroq(
    model=MODEL,
    api_key=settings.groq_api_key
)


def get_structured_llm(schema):
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
    """
    return llm.with_structured_output(schema, method="json_schema")