"""
test_critic_step7.py — Standalone verification for Step 7
"""

import sys
import os
import unittest
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage
from langgraph.types import Command

# Set dummy environment variables
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_pass")
os.environ.setdefault("GROQ_API_KEY", "gsk_dummy_test_key_for_offline_evaluation")
os.environ.setdefault("TAVILY_API_KEY", "tvly_dummy_test_key_for_offline_evaluation")
os.environ.setdefault("SERPAPI_API_KEY", "serp_dummy_test_key_for_offline_evaluation")
os.environ.setdefault("RAILRADAR_API_KEY", "rail_dummy_test_key_for_offline_evaluation")

from models.schemas import CriticAnalysis
from agents.critic import critic_node, _extract_budget, _extract_transport_pref, _extract_num_travelers


def test_regex_parameter_extraction():
    assert _extract_budget("Can you change budget to 50000?") == 50000.0
    assert _extract_budget("Increase budget to 60k") == 60000.0
    assert _extract_transport_pref("I'd rather take the train for everything") == "trains"
    assert _extract_transport_pref("Only flights please") == "flights"
    assert _extract_num_travelers("We are 3 travelers now") == 3
    print("✅ Regex Parameter Extraction: PASSED")


def test_budget_revision_state_update():
    # User asks to increase budget
    state = {
        "trip_id": "test-critic-1",
        "normalized_input": {
            "destination": "Goa, India",
            "budget": 25000.0,
            "transport_pref": "flights",
            "num_travelers": 2,
        },
        "messages": [HumanMessage(content="Can you increase budget to 50000?")],
    }

    # Mock structured LLM
    mock_llm_response = {
        "parsed": CriticAnalysis(
            user_request="Can you increase budget to 50000?",
            interpretation="User wants to increase budget to 50000 INR",
            target=["planner"],
            updated_budget=50000.0,
            reasoning="Budget changed significantly, requires replan.",
        ),
        "raw": MagicMock(usage_metadata={}),
    }

    from unittest.mock import patch
    with patch("agents.critic.get_structured_llm") as mock_get_llm:
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = mock_llm_response
        mock_get_llm.return_value = mock_instance

        cmd: Command = critic_node(state)

        # Assertions
        assert "planner" in cmd.goto, "Must route to planner"
        updated_input = cmd.update["normalized_input"]
        assert updated_input["budget"] == 50000.0, f"Expected 50000.0, got {updated_input['budget']}"
        print("✅ Budget State Update in Review Loop: PASSED")


def test_transport_mode_revision_state_update():
    # User asks to switch to trains
    state = {
        "trip_id": "test-critic-2",
        "normalized_input": {
            "destination": "Jaipur, India",
            "budget": 20000.0,
            "transport_pref": "flights",
            "num_travelers": 1,
        },
        "messages": [HumanMessage(content="I'd rather take the train for everything")],
    }

    mock_llm_response = {
        "parsed": CriticAnalysis(
            user_request="I'd rather take the train for everything",
            interpretation="User wants to use trains instead of flights",
            target=["planner"],
            updated_transport_pref="trains",
            reasoning="Core transport preference changed.",
        ),
        "raw": MagicMock(usage_metadata={}),
    }

    from unittest.mock import patch
    with patch("agents.critic.get_structured_llm") as mock_get_llm:
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = mock_llm_response
        mock_get_llm.return_value = mock_instance

        cmd: Command = critic_node(state)

        assert "planner" in cmd.goto, "Must route to planner"
        updated_input = cmd.update["normalized_input"]
        assert updated_input["transport_pref"] == "trains", f"Expected 'trains', got {updated_input['transport_pref']}"
        print("✅ Transport Preference State Update in Review Loop: PASSED")


def test_pure_itinerary_edit_no_param_mutation():
    # User asks for simple schedule rearrangement
    state = {
        "trip_id": "test-critic-3",
        "normalized_input": {
            "destination": "Goa, India",
            "budget": 25000.0,
            "transport_pref": "flights",
            "num_travelers": 2,
        },
        "messages": [HumanMessage(content="Swap day 1 and day 2 activities")],
    }

    mock_llm_response = {
        "parsed": CriticAnalysis(
            user_request="Swap day 1 and day 2 activities",
            interpretation="User wants to swap the activities between day 1 and day 2",
            target=["itinerary_builder"],
            reasoning="Pure scheduling rearrangement, no new data or parameter change.",
        ),
        "raw": MagicMock(usage_metadata={}),
    }

    from unittest.mock import patch
    with patch("agents.critic.get_structured_llm") as mock_get_llm:
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = mock_llm_response
        mock_get_llm.return_value = mock_instance

        cmd: Command = critic_node(state)

        assert cmd.goto == ["itinerary_builder"]
        assert cmd.update["critic_analysis"] is not None
        assert cmd.update["normalized_input"]["budget"] == 25000.0
        print("✅ Targeted Itinerary Rearrangement (No Param Drift): PASSED")


if __name__ == "__main__":
    print("\nRunning Step 7 Verification...")
    test_regex_parameter_extraction()
    test_budget_revision_state_update()
    test_transport_mode_revision_state_update()
    test_pure_itinerary_edit_no_param_mutation()
    print("\n🎉 ALL STEP 7 CHECKS PASSED!\n")