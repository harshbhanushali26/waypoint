"""
tools/_constants.py

Static IATA airport codes, railway station codes, and geographic normalization helpers.
Zero API cost — deterministic dictionary lookups.
"""

INDIAN_AIRPORTS: dict[str, str] = {
    "ahmedabad": "AMD", "bengaluru": "BLR", "bangalore": "BLR", "bhubaneswar": "BBI",
    "bhopal": "BHO", "chandigarh": "IXC", "chennai": "MAA", "coimbatore": "CJB",
    "dehradun": "DED", "delhi": "DEL", "new delhi": "DEL", "goa": "GOI", "panaji": "GOI",
    "guwahati": "GAU", "hyderabad": "HYD", "indore": "IDR", "jaipur": "JAI",
    "kochi": "COK", "cochin": "COK", "kolkata": "CCU", "lucknow": "LKO", "mangalore": "IXE",
    "mumbai": "BOM", "nagpur": "NAG", "patna": "PAT", "pune": "PNQ", "raipur": "RPR",
    "ranchi": "IXR", "thiruvananthapuram": "TRV", "trivandrum": "TRV", "vadodara": "BDQ",
    "varanasi": "VNS", "visakhapatnam": "VTZ", "bhuj": "BHJ",
}

INDIAN_STATIONS: dict[str, str] = {
    "ahmedabad": "ADI", "bengaluru": "SBC", "bangalore": "SBC", "bhopal": "BPL",
    "bhubaneswar": "BBS", "chandigarh": "CDG", "chennai": "MAS", "coimbatore": "CBE",
    "delhi": "DLI", "new delhi": "NDLS", "goa": "MAO", "madgaon": "MAO", "guwahati": "GHY",
    "hyderabad": "SC", "secunderabad": "SC", "indore": "INDB", "jaipur": "JP",
    "kochi": "ERS", "ernakulam": "ERS", "kolkata": "KOAA", "howrah": "HWH",
    "lucknow": "LKO", "mumbai": "MMCT", "nagpur": "NGP", "patna": "PNBE", "pune": "PUNE",
    "raipur": "R", "ranchi": "RNC", "thiruvananthapuram": "TVC", "trivandrum": "TVC",
    "vadodara": "BRC", "varanasi": "BSB", "visakhapatnam": "VSKP", "surat": "ST", "vapi": "VAPI",
}


def strip_country(city_str: str) -> str:
    """
    Strips trailing state/country parts:
    'Mumbai, Maharashtra, India' -> 'Mumbai'
    'Goa, India' -> 'Goa'
    """
    if not city_str:
        return ""
    return city_str.split(",")[0].strip()


def resolve_airport(city: str) -> str:
    """
    Resolve a city name to its IATA code.
    Automatically strips country/state suffixes ('Mumbai, India' -> 'Mumbai' -> 'BOM').
    Falls back to the clean city name if not in static dict.
    """
    clean = strip_country(city)
    return INDIAN_AIRPORTS.get(clean.lower(), clean)
def resolve_station(city: str) -> str:
    """
    Resolve a city name to its Indian Railways station code.
    Automatically strips country/state suffixes ('Mumbai, India' -> 'Mumbai' -> 'MMCT').
    Falls back to the clean city name if not in static dict.
    """
    clean = strip_country(city)
    return INDIAN_STATIONS.get(clean.lower(), clean)