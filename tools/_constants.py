"""
tools/_constants.py

Static IATA airport codes, railway station codes, and geographic normalization helpers.
Zero API cost — deterministic dictionary lookups.
"""

INDIAN_AIRPORTS: dict[str, str] = {
    "ahmedabad": "AMD", "bengaluru": "BLR", "bangalore": "BLR", "bhubaneswar": "BBI",
    "bhopal": "BHO", "chandigarh": "IXC", "chennai": "MAA", "coimbatore": "CJB",
    "dehradun": "DED", "delhi": "DEL", "new delhi": "DEL", "goa": "GOI", "panaji": "GOI",
    "dabolim": "GOI", "mopa": "GOX", "guwahati": "GAU", "hyderabad": "HYD",
    "indore": "IDR", "jaipur": "JAI", "kochi": "COK", "cochin": "COK", "kolkata": "CCU",
    "lucknow": "LKO", "mangalore": "IXE", "mumbai": "BOM", "nagpur": "NAG",
    "patna": "PAT", "pune": "PNQ", "raipur": "RPR", "ranchi": "IXR",
    "thiruvananthapuram": "TRV", "trivandrum": "TRV", "vadodara": "BDQ",
    "varanasi": "VNS", "visakhapatnam": "VTZ", "bhuj": "BHJ", "surat": "STV",
    "udaipur": "UDR", "amritsar": "ATQ", "srinagar": "SXR", "jodhpur": "JDH",
    "agra": "AGR", "madurai": "IXM", "tirupati": "TIR", "port blair": "IXZ",
    "bagdogra": "IXB", "darjeeling": "IXB", "siliguri": "IXB", "gwalior": "GWL",
    "jammu": "IXJ", "leh": "IXL", "aurangabad": "IXU", "shirdi": "SAG",
}

INDIAN_STATIONS: dict[str, str] = {
    "ahmedabad": "ADI", "bengaluru": "SBC", "bangalore": "SBC", "bhopal": "BPL",
    "bhubaneswar": "BBS", "chandigarh": "CDG", "chennai": "MAS", "coimbatore": "CBE",
    "delhi": "DLI", "new delhi": "NDLS", "goa": "MAO", "madgaon": "MAO",
    "vasco da gama": "VSG", "guwahati": "GHY", "hyderabad": "SC", "secunderabad": "SC",
    "indore": "INDB", "jaipur": "JP", "kochi": "ERS", "ernakulam": "ERS",
    "kolkata": "KOAA", "howrah": "HWH", "sealdah": "SDAH", "lucknow": "LKO",
    "mumbai": "MMCT", "mumbai central": "MMCT", "cst": "CSMT", "nagpur": "NGP",
    "patna": "PNBE", "pune": "PUNE", "raipur": "R", "ranchi": "RNC",
    "thiruvananthapuram": "TVC", "trivandrum": "TVC", "vadodara": "BRC",
    "varanasi": "BSB", "visakhapatnam": "VSKP", "surat": "ST", "vapi": "VAPI",
    "bhuj": "BHUJ", "udaipur": "UDZ", "amritsar": "ASR", "jodhpur": "JU",
    "agra": "AGC", "haridwar": "HW", "dehradun": "DDN", "gwalior": "GWL",
    "mathura": "MTJ", "ujjain": "UJN", "ajmer": "AII", "shimla": "SML",
}


def strip_country(city_str: str) -> str:
    """Strips trailing state/country parts: 'Mumbai, Maharashtra, India' -> 'Mumbai'."""
    if not city_str:
        return ""
    return city_str.split(",")[0].strip()


def resolve_airport(city: str) -> str:
    """
    Resolves a city name to its 3-letter IATA code.
    Returns the IATA code if found, or the clean city name if not mapped.
    """
    clean = strip_country(city)
    return INDIAN_AIRPORTS.get(clean.lower(), clean)


def is_valid_iata(code: str) -> bool:
    """Returns True only if code is a standard 3-letter uppercase alphabetic IATA code."""
    return bool(code and len(code) == 3 and code.isalpha() and code.isupper())


def resolve_station(city: str) -> str:
    """
    Resolves a city name to its Indian Railways station code.
    Returns station code if found, or clean city name if not mapped.
    """
    clean = strip_country(city)
    return INDIAN_STATIONS.get(clean.lower(), clean)