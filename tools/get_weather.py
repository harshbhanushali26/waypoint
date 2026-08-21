import json
from pathlib import Path
from datetime import date


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "weather.json"



def get_weather(state: dict) -> dict:
    """
    Dummy-stage tool node. Loads fixed weather JSON and slices it to the
    trip's date range. No LLM calls, no external API — pure state -> dict.
    """

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            all_days = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"weather": []}

    start = date.fromisoformat(state["start_date"])
    end = date.fromisoformat(state["end_date"])

    sliced = [
        day for day in all_days
        if start <= date.fromisoformat(day["date"]) <= end
    ]

    return {"weather": sliced}