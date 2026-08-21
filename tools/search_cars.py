import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "cars.json"


def search_cars(state: dict) -> dict:
    """
        Dummy-stage tool node. Loads fixed car JSON. 
        No LLM calls, no external API — pure state -> dict.
    """

    if not state.get("wants_rental_car"):
        return {"cars": []}

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            all_cars = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"cars": []}


    cars = [car for car in all_cars]

    return {"cars": cars}