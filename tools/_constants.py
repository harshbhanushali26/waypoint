"""
Static lookup maps for Indian airports and railway stations.

No API calls — deterministic, zero quota burn. SerpApi accepts both
city names and IATA codes; we normalize to IATA for consistency.
RailRadar accepts station codes (NDLS, BCT, etc.).

Extend these dicts as you add more cities to your route coverage.
"""


# ── Indian airport IATA codes ──────────────────────────────────────────────
# Keyed by lowercase city name. SerpApi's google_flights engine accepts
# either the city name or the IATA code as departure_id / arrival_id.

INDIAN_AIRPORTS: dict[str, str] = {
    "ahmedabad": "AMD",
    "bengaluru": "BLR",
    "bangalore": "BLR",
    "bhubaneswar": "BBI",
    "bhopal": "BHO",
    "chandigarh": "IXC",
    "chennai": "MAA",
    "coimbatore": "CJB",
    "dehradun": "DED",
    "delhi": "DEL",
    "new delhi": "DEL",
    "goa": "GOI",
    "panaji": "GOI",
    "guwahati": "GAU",
    "hyderabad": "HYD",
    "indore": "IDR",
    "jaipur": "JAI",
    "kochi": "COK",
    "cochin": "COK",
    "kolkata": "CCU",
    "lucknow": "LKO",
    "mangalore": "IXE",
    "mumbai": "BOM",
    "nagpur": "NAG",
    "patna": "PAT",
    "pune": "PNQ",
    "raipur": "RPR",
    "ranchi": "IXR",
    "thiruvananthapuram": "TRV",
    "trivandrum": "TRV",
    "vadodara": "BDQ",
    "varanasi": "VNS",
    "visakhapatnam": "VTZ",
}


# ── Indian railway station codes ────────────────────────────────────────────
# Keyed by lowercase city name. RailRadar uses the standard Indian
# Railways station codes as path params.
#
# NOTE: "delhi" deliberately maps to DLI (Old Delhi Jn), not NDLS
# (New Delhi) — kept as a distinct entry from "new delhi" on purpose.

INDIAN_STATIONS: dict[str, str] = {
    "ahmedabad": "ADI",
    "bengaluru": "SBC",
    "bangalore": "SBC",
    "banglore": "SBC",
    "ksr bengaluru": "SBC",
    "bhopal": "BPL",
    "bhubaneswar": "BBS",
    "chandigarh": "CDG",
    "chennai": "MAS",
    "coimbatore": "CBE",
    "delhi": "DLI",
    "new delhi": "NDLS",
    "goa": "MAO",
    "madgaon": "MAO",
    "guwahati": "GHY",
    "hyderabad": "SC",
    "secunderabad": "SC",
    "indore": "INDB",
    "jaipur": "JP",
    "ernakulam": "ERS",
    "kochi": "ERS",
    "kolkata": "KOAA",
    "howrah": "HWH",
    "lucknow": "LKO",
    "mumbai": "MMCT",
    "nagpur": "NGP",
    "patna": "PNBE",
    "pune": "PUNE",
    "raipur": "R",
    "ranchi": "RNC",
    "thiruvananthapuram": "TVC",
    "trivandrum": "TVC",
    "vadodara": "BRC",
    "varanasi": "BSB",
    "visakhapatnam": "VSKP",
    "surat": "ST",
    "vapi": "VAPI",
}


def resolve_airport(city: str) -> str:  
    """
    Resolve a city name to its IATA code.
    Falls back to the original string if not found (SerpApi accepts city names too).
    """
    return INDIAN_AIRPORTS.get(city.strip().lower(), city.strip())


def resolve_station(city: str) -> str:
    """
    Resolve a city name to its Indian Railways station code.
    Falls back to the original string if not found.
    """
    return INDIAN_STATIONS.get(city.strip().lower(), city.strip())