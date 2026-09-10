"""
transport_utils — shared helpers for lists that mix outbound and return
legs in one flat array (flights, trains — buses deferred, cars aren't
point-to-point legs at all).

search_flights and search_trains both tag each entry with a "direction"
field but return everything in a single list. Anything that needs to
reason about one direction at a time (cheapest-leg lookup, a per-direction
top-N cut) should split with split_by_direction rather than
re-implementing the grouping inline.
"""


def split_by_direction(options: list[dict]) -> dict[str, list[dict]]:
    """Groups a flat list of transport options by their 'direction' field.

    Returns {"outbound": [...], "return": [...]}. An entry with a missing
    or unrecognized direction value is dropped - tool nodes only ever
    write "outbound" or "return", so this only fires on malformed data.
    """
    grouped: dict[str, list[dict]] = {"outbound": [], "return": []}
    for option in options:
        direction = option.get("direction")
        if direction in grouped:
            grouped[direction].append(option)
    return grouped


def top_n_per_direction(options: list[dict], price_key: str, n: int) -> list[dict]:
    """Keeps the n cheapest options per direction, dropping unpriced ones.

    A price of 0/None is treated as a failed fare lookup, not a free
    option (same rule budget_node applies) - ranking by price without
    this filter would let a bogus zero-fare entry sort to the top and
    get kept purely because it looks cheapest.

    Outbound and return are ranked independently so a direction that's
    genuinely more expensive across the board can't get starved out by
    the other direction's cheaper options - each side always keeps up
    to n entries of its own.

    Returns outbound's survivors followed by return's, each internally
    sorted cheapest-first.
    """
    grouped = split_by_direction(options)
    result = []
    for direction in ("outbound", "return"):
        priced = [
            o for o in grouped[direction]
            if o.get(price_key) is not None and o[price_key] > 0
        ]
        priced.sort(key=lambda o: o[price_key])
        result.extend(priced[:n])
    return result