"""
Debug script — raw RailRadar "Trains Between Stations" call for VAPI -> ADI.

Deliberately minimal: one direct call, no retry-wrapper reasoning, no
normalization. Just resolve stations and print the raw JSON to see what
RailRadar actually returns for this pair before assuming a bug.

Run from project root:
    uv run python -m scripts.debug_railradar_vapi_adi
"""

from tools.search_trains import _resolve_station, _fetch_trains_between


def main():
    from_city = "Vapi"
    to_city = "Ahmedabad"
    date_str = "2026-10-05"

    from_code = _resolve_station(from_city)
    to_code = _resolve_station(to_city)

    print(f"Resolved: {from_city} -> {from_code}")
    print(f"Resolved: {to_city} -> {to_code}\n")

    if not from_code or not to_code:
        print("Station resolution failed — stopping before API call.")
        return

    print(f"Calling /trains/between/{from_code}/{to_code}?byCity=true&date={date_str}\n")

    raw_trains = _fetch_trains_between(from_code, to_code, date_str)

    print(f"Trains returned: {len(raw_trains)}\n")
    for t in raw_trains:
        train = t.get("train", {})
        frm = t.get("from", {})
        to = t.get("to", {})
        print(f"  {train.get('number')} {train.get('name')} | "
              f"{frm.get('code')} {frm.get('departure')} -> "
              f"{to.get('code')} {to.get('arrival')} | "
              f"dist={t.get('distance')}km dur={t.get('duration')}min")


if __name__ == "__main__":
    main()