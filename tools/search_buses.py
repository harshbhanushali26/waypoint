import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "buses.json"


def search_cars(state: dict) -> dict:
    """
        Dummy-stage tool node. Loads fixed bus JSON. 
        No LLM calls, no external API — pure state -> dict.
    """

    if "buses" not in state.get("search_plan", {}).get("transport_modes", []):
        return {"buses": []}

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            all_buses = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"buses": []}

    return {"buses": all_buses}