import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "hotels.json"


def search_hotels(state: dict) -> dict:
    """
        Dummy-stage tool node. Loads fixed hotel JSON. 
        No LLM calls, no external API — pure state -> dict.
    """

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            all_hotels = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"hotels": []}

    return {"hotels": all_hotels}