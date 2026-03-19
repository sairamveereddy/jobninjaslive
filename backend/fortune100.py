import re

# Fortune 100 (USA) company names (ranked by revenue).
# Source: extracted from public Fortune 1000 list (top 100).
FORTUNE100_COMPANIES = [
    "Walmart",
    "Amazon",
    "Exxon Mobil",
    "Apple",
    "CVS Health",
    "Berkshire Hathaway",
    "Unitedhealth Group",
    "McKesson",
    "AT&T",
    "AmerisourceBergen",
    "Alphabet",
    "Ford Motor",
    "Cigna",
    "Costco Wholesale",
    "Chevron",
    "Cardinal Health",
    "JPMorgan Chase",
    "General Motors",
    "Walgreens Boots Alliance",
    "Verizon Communications",
    "Microsoft",
    "Marathon Petroleum",
    "Kroger",
    "Fannie Mae",
    "Bank Of America",
    "Home Depot",
    "Phillips 66",
    "Comcast",
    "Anthem",
    "Wells Fargo",
    "Citigroup",
    "Valero Energy",
    "General Electric",
    "Dell Technologies",
    "Johnson & Johnson",
    "State Farm Insurance",
    "Target",
    "Ibm",
    "Raytheon Technologies",
    "Boeing",
    "Freddie Mac",
    "Centene",
    "United Parcel Service",
    "Lowe’s",
    "Intel",
    "Facebook",
    "Fedex",
    "Metlife",
    "Walt Disney",
    "Procter & Gamble",
    "Pepsico",
    "Humana",
    "Prudential Financial",
    "Archer Daniels Midland",
    "Albertsons",
    "Sysco",
    "Lockheed Martin",
    "Hp",
    "Energy Transfer",
    "Goldman Sachs Group",
    "Morgan Stanley",
    "Caterpillar",
    "Cisco Systems",
    "Pfizer",
    "Hca Healthcare",
    "Aig",
    "American Express",
    "Delta Air Lines",
    "Merck",
    "American Airlines Group",
    "Charter Communications",
    "Allstate",
    "New York Life Insurance",
    "Nationwide",
    "Best Buy",
    "United Airlines Holdings",
    "Liberty Mutual Insurance Group",
    "Dow",
    "Tyson Foods",
    "Tjx",
    "Tiaa",
    "Oracle",
    "General Dynamics",
    "Deere",
    "Nike",
    "Progressive",
    "Publix Super Markets",
    "Coca-cola",
    "Massachusetts Mutual Life Insurance",
    "Tech Data",
    "World Fuel Services",
    "Honeywell International",
    "Conocophillips",
    "Usaa",
    "Exelon",
    "Northrop Grumman",
    "Capital One Financial",
    "Plains Gp Holdings",
    "Abbvie",
    "Stonex Group",
]


def _norm_company_name(s: str) -> str:
    s = (s or "").lower().strip()
    s = s.replace("&", "and")
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(inc|incorporated|corp|corporation|co|company|holdings|group|llc|ltd)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_FORTUNE100_NORM = {_norm_company_name(x) for x in FORTUNE100_COMPANIES}


def is_fortune100_company(company: str) -> bool:
    """
    Best-effort match against Fortune 100 names.
    We normalize and compare full-string equality and token containment (for suffix/prefix variants).
    """
    c = _norm_company_name(company)
    if not c:
        return False
    if c in _FORTUNE100_NORM:
        return True
    # containment fallback (e.g. "The Kroger Co" -> "kroger")
    for n in _FORTUNE100_NORM:
        if n and (c == n or c.startswith(n) or n.startswith(c) or f" {n} " in f" {c} "):
            return True
    return False

