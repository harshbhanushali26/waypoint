"""
scripts/check_agent_token_usage.py

One-off usage check: calls Concierge, Planner, and Budget with real prompts
against realistic sample state, using include_raw=True to read actual
Groq token usage (not the requested max_tokens ceiling). This exists to
right-size AGENT_MAX_TOKENS with real numbers instead of the current
default/guessed values, before deciding on Groq TPM pacing.

This makes REAL Groq calls - not free, but cheap (a handful of calls).

Run via: uv run python -m scripts.check_agent_token_usage
"""

from core.llm import get_structured_llm

from prompts.concierge_prompt import CONCIERGE_SYSTEM_PROMPT, build_concierge_user_message
from prompts.planner_prompt import PLANNER_SYSTEM_PROMPT, build_planner_user_message
from prompts.budget_prompt import BUDGET_SYSTEM_PROMPT, build_budget_user_message

from models.schemas import NormalizedInput, SearchPlan, BudgetAnalysis


def _print_usage(agent_name: str, response: dict):
    usage = response["raw"].usage_metadata
    print(f"\n[{agent_name}] usage_metadata: {usage}")
    if response["parsed"] is None:
        print(f"[{agent_name}] WARNING: parsing failed, raw content below")
        print(response["raw"].content)


def check_concierge():
    print("\n--- Concierge ---")

    raw_form_input = {
        "destination": "Goa",
        "origin_city": "Mumbai",
        "start_date": "2026-10-10",
        "end_date": "2026-10-15",
        "budget": 25000.0,
        "currency": "INR",
        "num_travelers": 2,
        "interests": ["beaches", "nightlife"],
        "transport_pref": "trains",
        "wants_rental_car": False,
        "pace": "moderate",
    }

    structured_llm = get_structured_llm(NormalizedInput, include_raw=True)
    response = structured_llm.invoke(
        [
            {"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
            {"role": "user", "content": build_concierge_user_message(raw_form_input)},
        ],
    )
    _print_usage("Concierge", response)


def check_planner():
    print("\n--- Planner ---")

    # ASSUMPTION: normalized_input mirrors the raw form fields, normalized.
    # Adjust field names here if models/schemas.py's NormalizedInput differs.
    normalized_input = {
        "destination": "Goa",
        "origin_city": "Mumbai",
        "start_date": "2026-10-10",
        "end_date": "2026-10-15",
        "budget": 25000.0,
        "currency": "INR",
        "num_travelers": 2,
        "interests": ["beaches", "nightlife"],
        "transport_pref": "trains",
        "wants_rental_car": False,
        "pace": "moderate",
    }

    structured_llm = get_structured_llm(SearchPlan, include_raw=True)
    response = structured_llm.invoke(
        [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": build_planner_user_message(normalized_input)},
        ],
    )
    _print_usage("Planner", response)


def check_budget():
    print("\n--- Budget ---")

    state_slice = {
        "budget": 25000.0,
        "currency": "INR",
        "estimated_total": 27500.0,
        "cost_breakdown": {"trains": 1200.0, "hotels": 18000.0, "activities": 2000.0},
        "over_budget": True,
        "overage_amount": 2500.0,
    }

    structured_llm = get_structured_llm(BudgetAnalysis, include_raw=True)
    response = structured_llm.invoke(
        [
            {"role": "system", "content": BUDGET_SYSTEM_PROMPT},
            {"role": "user", "content": build_budget_user_message(state_slice)},
        ],
    )
    _print_usage("Budget", response)


if __name__ == "__main__":
    check_concierge()
    check_planner()
    check_budget()