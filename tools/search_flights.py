import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "flights.json"


def search_flights(state: dict) -> dict:
    """
        Dummy-stage tool node. Loads fixed flight JSON. 
        No LLM calls, no external API — pure state -> dict.
    """

    if "flights" not in state.get("search_plan", {}).get("transport_modes", []):
        return {"flights": []}

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            all_flights = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"flights": []}

    return {"flights": all_flights}