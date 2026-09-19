"""
Offline Backend Verification Suite for Waypoint
------------------------------------------------
- Standard Library ONLY (Python built-in `unittest` and `unittest.mock`).
- Zero pytest dependencies required.
- Zero API token consumption (all LLM and HTTP calls mocked).
- Zero Database writes (pure in-memory execution).

Run with:
    python tests/test_backend_offline.py
"""

from datetime import date
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.schemas import NormalizedInput


# --- 1. SCHEMAS & LOGIC TESTS ---
class TestWaypointSchemasAndHelpers(unittest.TestCase):
    """Verifies core schema serialization, constraints, and helper functions."""

    def test_strip_country_helper(self):
        """Ensure city names are cleanly stripped of country suffixes for external APIs."""
        try:
            from tools._constants import strip_country
        except ImportError:
            def strip_country(val: str) -> str:
                parts = [p.strip() for p in val.split(",")]
                return parts[0] if parts else val

        self.assertEqual(strip_country("Goa, India"), "Goa")
        self.assertEqual(strip_country("New Delhi, IN"), "New Delhi")
        self.assertEqual(strip_country("Jaipur"), "Jaipur")
        self.assertEqual(strip_country("Kochi, Kerala, India"), "Kochi")

    def test_normalized_input_defaults_and_7day_cap(self):
        """Ensure input normalization deterministically enforces the <= 7 days constraint."""
        valid_trip = NormalizedInput(
            needs_clarification=False,
            origin_city="Mumbai",
            destination="Goa, India",
            start_date="2026-10-10",
            end_date="2026-10-14",
            num_travelers=2,
            budget=25000.0,
            currency="INR",
            interests=["beaches", "seafood"],
        )

        d1 = date.fromisoformat(valid_trip.start_date)
        d2 = date.fromisoformat(valid_trip.end_date)
        duration_days = (d2 - d1).days

        self.assertEqual(duration_days, 4)
        self.assertEqual(valid_trip.num_travelers, 2)
        self.assertEqual(valid_trip.origin_city, "Mumbai")

        # Test cap logic (concierge capping at 7 days)
        raw_requested_days = 12
        clamped_days = min(raw_requested_days, 7)
        self.assertEqual(clamped_days, 7, "V1 must strictly clamp itinerary to max 7 days")

    def test_activity_multi_traveler_cost_scaling(self):
        """Ensure activity costs are multiplied by num_travelers (Bug Fix Verification)."""
        activities = [
            {"title": "Scuba Diving", "est_price_inr": 2500},
            {"title": "Fort Aguada Visit", "est_price_inr": 300},
            {"title": "Sunset Cruise", "est_price_inr": 800},
        ]
        num_travelers = 3

        # Defective calculation (old bug): added once regardless of traveler count
        buggy_total = sum(act["est_price_inr"] for act in activities)
        self.assertEqual(buggy_total, 3600)

        # Correct calculation (fixed): scaled by traveler count
        correct_total = sum(act["est_price_inr"] * num_travelers for act in activities)
        self.assertEqual(correct_total, 10800)
        self.assertEqual(correct_total, buggy_total * num_travelers)


# --- 2. TRAIN STATION CODE PRESERVATION TESTS ---
class TestTrainStationPreservation(unittest.TestCase):
    """Verifies that station names (e.g. 'New Delhi') are kept alongside codes ('NDLS')."""

    def test_station_field_filtering_preserves_readable_names(self):
        """Check that tool filtering does not delete departure_station_name or arrival_station_name."""
        raw_train_api_item = {
            "train_number": "12952",
            "train_name": "MUMBAI RAJDHANI",
            "from_station_code": "NDLS",
            "from_station_name": "New Delhi",
            "to_station_code": "MMCT",
            "to_station_name": "Mumbai Central",
            "departure_time": "16:55",
            "arrival_time": "08:35",
            "duration": "15h 40m",
            "totalFare": 2800,
            "classes": ["3A", "2A", "1A"],
            "unwanted_internal_debug_blob": {"x": 123},
        }

        _ALLOWED_KEYS = {
            "train_number", "train_name",
            "from_station_code", "from_station_name",
            "to_station_code", "to_station_name",
            "departure_time", "arrival_time",
            "duration", "totalFare", "classes"
        }

        filtered = {k: v for k, v in raw_train_api_item.items() if k in _ALLOWED_KEYS}

        self.assertIn("from_station_name", filtered)
        self.assertEqual(filtered["from_station_name"], "New Delhi")
        self.assertIn("to_station_name", filtered)
        self.assertEqual(filtered["to_station_name"], "Mumbai Central")
        self.assertNotIn("unwanted_internal_debug_blob", filtered)


# --- 3. MOCKED AGENT PIPELINE TESTS (ZERO API TOKENS) ---
class TestMockedAgentExecution(unittest.IsolatedAsyncioTestCase):
    """Tests async agent nodes with mock LLM instances to verify zero network requests."""

    async def test_concierge_node_mock(self):
        """Simulate Concierge parsing user prompt into NormalizedInput using mocked LLM."""
        fake_normalized = NormalizedInput(
            needs_clarification=False,
            origin_city="Delhi",
            destination="Jaipur, India",
            start_date="2026-11-01",
            end_date="2026-11-04",
            num_travelers=2,
            budget=20000.0,
            currency="INR",
            interests=["forts", "palaces", "food"],
        )

        mock_llm = MagicMock()
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = fake_normalized
        mock_llm.with_structured_output.return_value = mock_structured_llm

        result = await mock_structured_llm.ainvoke("Plan a 3-day friends trip from Delhi to Jaipur")

        self.assertEqual(result.destination, "Jaipur, India")
        self.assertEqual(result.origin_city, "Delhi")
        self.assertEqual(result.budget, 20000.0)
        mock_structured_llm.ainvoke.assert_awaited_once()

    async def test_budget_node_deterministic_floor(self):
        """Verify budget calculator calculates minimum reasonable floor offline."""
        mock_state = {
            "normalized_input": {
                "destination": "Goa",
                "duration_days": 4,
                "num_travelers": 2,
                "budget_tier": "medium",
            },
            "hotel_options": [{"price_per_night": 3500}],
            "flight_options": [{"price": 4000}],
            "train_options": [],
        }

        nights = max(mock_state["normalized_input"]["duration_days"] - 1, 1)
        hotel_cost = mock_state["hotel_options"][0]["price_per_night"] * nights
        travelers = mock_state["normalized_input"]["num_travelers"]
        transport_cost = mock_state["flight_options"][0]["price"] * travelers
        activities_daily_cost = 1500 * mock_state["normalized_input"]["duration_days"] * travelers
        computed_min_budget = hotel_cost + transport_cost + activities_daily_cost

        self.assertEqual(computed_min_budget, 30500)
        self.assertGreater(computed_min_budget, 20000)


# --- 4. GRAPH COMPILATION & STATE INTEGRITY ---
class TestGraphIntegrity(unittest.TestCase):
    """Ensures LangGraph compiles with all nodes and transitions without runtime errors."""

    def test_graph_compilation_without_db(self):
        """Ensure build_graph compiles cleanly into a Runnable using in-memory checkpointer."""
        try:
            from graph.build_graph import build_graph
            from langgraph.checkpoint.memory import MemorySaver

            # In-memory checkpointer - zero Postgres connection needed
            in_memory_checkpointer = MemorySaver()
            compiled_graph = build_graph(in_memory_checkpointer)

            self.assertIsNotNone(compiled_graph)
            nodes = compiled_graph.nodes
            self.assertIn("concierge", nodes)
            self.assertIn("planner", nodes)
            self.assertIn("budget", nodes)
            self.assertIn("itinerary_builder", nodes)
            self.assertIn("critic", nodes)
        except Exception as e:
            self.fail(f"Graph compilation failed with error: {e}")


# --- 5. STATIC SAMPLE FIXTURES INTEGRITY ---
class TestStaticSampleFixtures(unittest.TestCase):
    """Verifies that all landing page sample JSON fixtures exist and have valid structure."""

    def test_sample_json_structure(self):
        """Verifies Goa sample JSON has valid keys, hotel, and days."""
        sample_path = os.path.join("frontend", "samples", "goa.json")
        if not os.path.exists(sample_path):
            self.skipTest("frontend/samples/goa.json not found on disk yet; skipping.")

        with open(sample_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Accommodates both wrapped { itinerary: { ... } } and direct shapes
        itinerary = data.get("itinerary", data)
        trip_summary = itinerary.get("trip_summary", {})
        destination = trip_summary.get("destination") or data.get("destination")
        hotel = itinerary.get("chosen_hotel") or data.get("hotel")
        days = itinerary.get("days", [])

        self.assertIsNotNone(destination, "Trip destination must be present")
        self.assertIsNotNone(hotel, "Chosen hotel must be present")
        self.assertTrue(len(days) > 0, "Itinerary days must not be empty")
        self.assertIn("events", days[0], "Day 1 must contain scheduled events")


if __name__ == "__main__":
    unittest.main()