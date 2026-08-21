import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "activities.json"


def search_activities(state: dict) -> dict:
    """
        Dummy-stage tool node. Loads fixed activity JSON. 
        No LLM calls, no external API — pure state -> dict.
    """

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            all_activities = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"activities": []}

    return {"activities": all_activities}