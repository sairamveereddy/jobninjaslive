import re

from sqlalchemy import or_ as sa_or

# Sidebar / API filter label (must match frontend ALL_SOURCES name).
H1B_VIRTUAL_SOURCE_NAMES = frozenset(
    {
        "h1b sponsors",
        "h1b sponsoring companies",
        "h1b sponsor companies",
    }
)


def is_h1b_virtual_source_filter(name: str) -> bool:
    """True if this source checkbox name refers to the H1B employer filter (not Job.source)."""
    x = (name or "").lower().strip()
    return x in H1B_VIRTUAL_SOURCE_NAMES or (x.startswith("h1b") and "sponsor" in x)


# Curated list of 50 employers often cited as H1B-friendly tech / consulting / health-tech names.
# Source: user-provided social list (2026). Matching is best-effort on job `company` strings.
H1B_SPONSOR_COMPANIES = [
    "Databricks",
    "Snowflake",
    "ServiceNow",
    "Workday",
    "Atlassian",
    "HubSpot",
    "Okta",
    "MongoDB",
    "Elastic",
    "Splunk",
    "Datadog",
    "Twilio",
    "Zscaler",
    "Cloudflare",
    "CrowdStrike",
    "Stripe",
    "Block",
    "Plaid",
    "Robinhood",
    "Coinbase",
    "SoFi",
    "Affirm",
    "Marqeta",
    "Chime",
    "Brex",
    "Epic Systems",
    "Cerner",
    "GE HealthCare",
    "Philips",
    "Allscripts",
    "Medtronic",
    "Change Healthcare",
    "Hims & Hers",
    "ResMed",
    "Guardant Health",
    "ZS Associates",
    "Slalom",
    "EPAM Systems",
    "Capgemini",
    "Cognizant",
    "LTIMindtree",
    "Infosys",
    "Tata Consultancy Services",
    "Wipro",
    "HCL Technologies",
    "Wayfair",
    "Chewy",
    "DoorDash",
    "Instacart",
    "Flexport",
]

# Extra strings that often appear instead of the primary name (same employers as above).
H1B_SPONSOR_ALIASES = [
    "Square",
    "TCS",
    "Oracle Health",
    "Hims",
    "LTI",
]


def _norm_company_name(s: str) -> str:
    s = (s or "").lower().strip()
    s = s.replace("&", "and")
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(
        r"\b(inc|incorporated|corp|corporation|co|company|holdings|group|llc|ltd)\b",
        "",
        s,
    )
    s = re.sub(r"\s+", " ", s).strip()
    return s


_ALL_NAMES = list(H1B_SPONSOR_COMPANIES) + list(H1B_SPONSOR_ALIASES)
_H1B_NORM = {_norm_company_name(x) for x in _ALL_NAMES}


def h1b_company_sql_or(Job):
    """
    SQL OR(Job.company ILIKE ...) for coarse prefilter when no text search is applied.
    Keeps results aligned with sidebar counts (all H1B sponsor rows, not a capped window).
    """
    seen = set()
    clauses = []
    for name in H1B_SPONSOR_COMPANIES + H1B_SPONSOR_ALIASES:
        n = name.strip()
        if len(n) < 2:
            continue
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        clauses.append(Job.company.ilike(f"%{n}%"))
    return sa_or(*clauses)


def is_h1b_sponsor_company(company: str) -> bool:
    """
    Best-effort match against the H1B sponsor list (normalized equality + token containment).
    """
    c = _norm_company_name(company)
    if not c:
        return False
    if c in _H1B_NORM:
        return True
    for n in _H1B_NORM:
        if not n:
            continue
        if c == n or c.startswith(n) or n.startswith(c) or f" {n} " in f" {c} ":
            return True
    return False
