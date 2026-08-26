# prompts/concierge_fallback_prompt.py

SYSTEM_PROMPT = """You are the fallback normalizer for a trip-planning assistant.

You will receive raw trip form input, and possibly one prior clarification
question and the user's answer to it. The input may still be incomplete or
ambiguous after that exchange.

Your job is different from a normal intake step: you MUST produce a complete,
valid trip context. You cannot ask a follow-up question — that option does
not exist here. If something is genuinely missing or unclear, make the most
reasonable assumption a careful travel planner would make, and proceed.

Rules:
- Never leave a field blank or null.
- Prefer the user's own words/values wherever they exist, even if informal
  (e.g. "cheap", "a week") — convert them to the closest reasonable
  structured value rather than discarding them.
- Only invent a value when the input truly gives you nothing to work with
  for that field.
- Do not explain your assumptions. Return only the structured trip context.
"""


def build_concierge_fallback_user_message(raw_form_input: dict, clarification_qa: dict | None = None) -> str:
    """
    raw_form_input: the original, untouched form data from the user
    clarification_qa: optional {"question": str, "answer": str} from the one
        clarification round that was attempted before falling back here
    """
    parts = [f"Raw trip form input:\n{raw_form_input}"]

    if clarification_qa:
        parts.append(
            f"\nA clarification was asked and answered, but the input is "
            f"still incomplete or ambiguous:\n"
            f"Question: {clarification_qa['question']}\n"
            f"Answer: {clarification_qa['answer']}"
        )

    parts.append(
        "\nProduce the best possible complete trip context now. "
        "No further questions are possible."
    )
    return "\n".join(parts)