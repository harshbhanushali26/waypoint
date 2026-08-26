"""
scripts/smoke_test_critic_invalid_target.py

Test 5 in the Step 7 sequence: deliberately trigger InvalidCriticTargetError
to confirm the raise path works correctly.

WHY THIS TEST MOCKS THE LLM CALL RATHER THAN CRAFTING AN ADVERSARIAL PROMPT:
We could try to trick the real LLM into returning an invalid target with a
weird user message, but that's unreliable - the LLM might refuse, interpret
oddly, or occasionally return something valid by chance. That would make
this test flaky rather than a real verification of the validation logic.

What we actually want to test is critic_node's OWN validation code, not the
LLM's judgment. So this test patches agents.critic.get_structured_llm to
return a stub whose .invoke() returns a fixed CriticAnalysis with an
invalid target ("budget" - deliberately excluded from VALID_TARGETS per
Step 7 discussion: cost-related re-plans are meant to go through "planner",
never targeted directly). No real API call happens.

This also means no graph, checkpointer, or DB is needed - critic_node is a
plain function called directly with a minimal fake state containing just
what it reads (state["messages"][-1].content) before calling the LLM.

Run with:
    python -m scripts.smoke_test_critic_invalid_target
"""

import logging
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from agents.critic import critic_node, InvalidCriticTargetError
from models.schemas import CriticAnalysis


class ListLogHandler(logging.Handler):
    """Captures log records in a list so we can assert on them afterward,
    instead of just trusting stdout output visually."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class StubStructuredLLM:
    """Stands in for llm.with_structured_output(...) - .invoke() returns a
    fixed response regardless of input, so no real API call happens."""

    def __init__(self, fixed_response):
        self.fixed_response = fixed_response

    def invoke(self, *args, **kwargs):
        return self.fixed_response


def main() -> None:
    fake_response = CriticAnalysis(
        user_request="Can you make this trip cheaper overall?",
        interpretation="User wants overall cost reduced.",
        target=["budget"],  # deliberately invalid - not in VALID_TARGETS
        reasoning="Budget Agent should re-evaluate cost.",
    )

    fake_state = {
        "messages": [HumanMessage(content="Can you make this trip cheaper overall?")],
    }

    # Capture logger.error(...) calls from agents.critic specifically.
    critic_logger = logging.getLogger("agents.critic")
    log_handler = ListLogHandler()
    critic_logger.addHandler(log_handler)
    critic_logger.setLevel(logging.ERROR)

    print("Patching agents.critic.get_structured_llm to return a stub "
          "with an invalid target (['budget'])...")

    raised = False
    error_message = None

    try:
        with patch(
            "agents.critic.get_structured_llm",
            return_value=StubStructuredLLM(fake_response),
        ):
            critic_node(fake_state)
    except InvalidCriticTargetError as e:
        raised = True
        error_message = str(e)
    finally:
        critic_logger.removeHandler(log_handler)

    print("\n--- Results ---")

    if raised:
        print("PASS: InvalidCriticTargetError was raised.")
        print(f"Error message: {error_message}")
        if "budget" in error_message:
            print("PASS: error message mentions the invalid target ('budget').")
        else:
            print("FAIL: error message doesn't mention the invalid target.")
    else:
        print("FAIL: InvalidCriticTargetError was NOT raised - "
              "critic_node accepted an invalid target silently.")

    if log_handler.records:
        print(f"\nPASS: logger.error(...) fired ({len(log_handler.records)} "
              f"record(s)) before the raise.")
        for record in log_handler.records:
            print(f"  {record.getMessage()}")
    else:
        print("\nFAIL: no error-level log record captured - expected "
              "logger.error(...) to fire before raising.")


if __name__ == "__main__":
    main()