import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "trains.json"


def search_trains(state: dict) -> dict:
    """
        Dummy-stage tool node. Loads fixed train JSON. 
        No LLM calls, no external API — pure state -> dict.
    """

    if "trains" not in state.get("search_plan", {}).get("transport_modes", []):
        return {"trains": []}

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            all_trains = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"trains": []}

    return {"trains": all_trains}