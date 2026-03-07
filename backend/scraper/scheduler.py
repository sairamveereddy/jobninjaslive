"""
jobninjas.live — Job Scrapers (USA Only)
────────────────────────────────────────
API (every 5 min):     Remotive · Arbeitnow · The Muse · Jobicy · FindWork · Greenhouse
Browser (every 5 min): LinkedIn · Indeed · Dice · ZipRecruiter · Monster · Glassdoor

All results filtered to USA. Jobs auto-expire after 48 h.
Browser scrapers use Scrapling StealthyFetcher via asyncio.to_thread.
"""

import asyncio, hashlib, json, logging, os, re
from datetime import datetime, timedelta
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete
from database import AsyncSessionLocal
from models import Job
from scraper.certs_scheduler import run_cert_scrape_cycle

log = logging.getLogger("jobninjas.scraper")
TIMEOUT = aiohttp.ClientTimeout(total=25)
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# ── Helpers ──────────────────────────────────────────────────────

def make_id(title, company, url):
    return hashlib.md5(
        f"{title.lower().strip()}|{company.lower().strip()}|{url}".encode()
    ).hexdigest()[:16]

def strip_html(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()[:800]

def detect_mode(t):
    t = (t or "").lower()
    if "hybrid" in t:
        return "Hybrid"
    if any(x in t for x in ("remote", "work from home", "wfh", "anywhere", "distributed")):
        return "Remote"
    if any(x in t for x in ("on-site", "onsite", "in-office", "in office")):
        return "On-site"
    return "On-site"

def norm_type(t):
    t = (t or "").lower().replace("_", " ")
    if "contract" in t: return "Contract"
    if "part" in t:     return "Part-time"
    if "intern" in t:   return "Internship"
    return "Full-time"

# ── USA Location Filter ─────────────────────────────────────────

_US_ST = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY","DC",
}
_US_KW = [
    "united states", "usa", "u.s.", "remote", "new york", "san francisco",
    "los angeles", "chicago", "seattle", "austin", "boston", "denver",
    "atlanta", "dallas", "houston", "miami", "portland", "washington",
    "philadelphia", "phoenix", "minneapolis", "nashville", "raleigh",
    "charlotte", "columbus", "pittsburgh", "baltimore", "salt lake",
    "tampa", "orlando", "san diego", "san jose", "sacramento", "las vegas",
    "detroit", "cincinnati", "cleveland", "kansas city", "indianapolis",
    "milwaukee", "st. louis", "richmond", "nationwide", "distributed",
    "anywhere in the u.s", "worldwide", "americas", "north america",
    "anywhere", "global", "world",
    "europe", "emea", "uk", "canada", "australia", "latin america",
]

def is_usa(loc):
    if not loc or not loc.strip():
        return True
    low = loc.lower()
    if any(k in low for k in _US_KW):
        return True
    for tok in re.findall(r"\b([A-Z]{2})\b", loc):
        if tok in _US_ST:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════
#  API SCRAPERS  (fast, JSON, no browser)
# ═══════════════════════════════════════════════════════════════════

async def scrape_remotive(http):
    jobs = []
    for q in ["software engineer","product manager","data scientist","devops",
              "backend","frontend","machine learning","data engineer","designer","security",
              "marketing","sales","customer support","finance","writing","hr"]:
        try:
            async with http.get(
                f"https://remotive.com/api/remote-jobs?search={q.replace(' ','%20')}&limit=20",
                timeout=TIMEOUT,
            ) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    for it in data.get("jobs", []):
                        loc = it.get("candidate_required_location", "")
                        if not is_usa(loc):
                            continue
                        jobs.append({
                            "id": make_id(it.get("title",""), it.get("company_name",""), it.get("url","")),
                            "title": it.get("title",""), "company": it.get("company_name",""),
                            "company_logo": it.get("company_logo_url",""),
                            "location": loc or "USA (Remote)",
                            "salary": it.get("salary",""), "job_type": norm_type(it.get("job_type","")),
                            "work_mode": "Remote",
                            "description": strip_html(it.get("description","")),
                            "url": it.get("url",""), "source": "Remotive", "source_color": "#4F46E5",
                            "tags": json.dumps((it.get("tags") or [])[:8]),
                        })
        except Exception as e:
            log.warning(f"[Remotive/{q}] {e}")
        await asyncio.sleep(0.15)
    log.info(f"[Remotive] {len(jobs)}")
    return jobs


async def scrape_arbeitnow(http):
    jobs = []
    try:
        for page in range(1, 6):
            async with http.get(
                f"https://www.arbeitnow.com/api/job-board-api?page={page}", timeout=TIMEOUT
            ) as r:
                if r.status != 200: break
                data = await r.json(content_type=None)
                items = data.get("data", [])
                if not items: break
                for it in items:
                    loc = it.get("location", "Remote")
                    if not is_usa(loc):
                        continue
                    jobs.append({
                        "id": make_id(it.get("title",""), it.get("company_name",""), it.get("url","")),
                        "title": it.get("title",""), "company": it.get("company_name",""),
                        "company_logo": it.get("company_logo",""), "location": loc,
                        "salary": "", "job_type": "Full-time",
                        "work_mode": "Remote" if it.get("remote", True) else "On-site",
                        "description": strip_html(it.get("description","")),
                        "url": it.get("url",""), "source": "Arbeitnow", "source_color": "#0CAA41",
                        "tags": json.dumps((it.get("tags") or [])[:8]),
                    })
            await asyncio.sleep(0.4)
    except Exception as e:
        log.warning(f"[Arbeitnow] {e}")
    log.info(f"[Arbeitnow] {len(jobs)}")
    return jobs


async def scrape_themuse(http):
    jobs = []
    try:
        for cat in ["Engineering","Data%20Science","Design","Product","DevOps%20%2F%20Sysadmin",
                     "Marketing","Sales","Finance","HR%20%2F%20Recruiting","Customer%20Service",
                     "Healthcare","Education","Operations","Legal","Business%20Development"]:
            async with http.get(
                f"https://www.themuse.com/api/public/jobs?category={cat}"
                "&level=Mid%20Level&level=Senior%20Level&page=1&descending=true",
                timeout=TIMEOUT,
            ) as r:
                if r.status != 200: continue
                data = await r.json(content_type=None)
                for it in data.get("results", []):
                    locs = it.get("locations", [])
                    loc  = locs[0].get("name","Remote") if locs else "Remote"
                    if not is_usa(loc):
                        continue
                    co = it.get("company", {})
                    jobs.append({
                        "id": make_id(it.get("name",""), co.get("name",""),
                                      it.get("refs",{}).get("landing_page","")),
                        "title": it.get("name",""), "company": co.get("name",""),
                        "company_logo": co.get("refs",{}).get("logo_image",""),
                        "location": loc, "salary": "", "job_type": "Full-time",
                        "work_mode": detect_mode(loc + " " + it.get("name","")),
                        "description": strip_html(it.get("contents","")),
                        "url": it.get("refs",{}).get("landing_page",""),
                        "source": "The Muse", "source_color": "#E8272A",
                        "tags": json.dumps([cat.replace("%20"," ").replace("%2F","/")])
                    })
            await asyncio.sleep(0.3)
    except Exception as e:
        log.warning(f"[TheMuse] {e}")
    log.info(f"[TheMuse] {len(jobs)}")
    return jobs


async def scrape_jobicy(http):
    jobs = []
    try:
        # API v2: count only (geo/industry can return 400); response has jobs[], jobGeo, salaryMin/Max
        async with http.get(
            "https://jobicy.com/api/v2/remote-jobs?count=50",
            timeout=TIMEOUT,
        ) as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                for it in data.get("jobs", []):
                    mn = it.get("salaryMin") or it.get("annualSalaryMin")
                    mx = it.get("salaryMax") or it.get("annualSalaryMax")
                    sal = ""
                    if mn is not None and mx is not None:
                        try: sal = f"${int(mn/1000)}k-${int(mx/1000)}k/yr"
                        except (ValueError, TypeError): pass
                    loc = it.get("jobGeo") or "Remote"
                    if not is_usa(loc):
                        continue
                    jobs.append({
                        "id": make_id(it.get("jobTitle",""), it.get("companyName",""), it.get("url","")),
                        "title": it.get("jobTitle",""), "company": it.get("companyName",""),
                        "company_logo": it.get("companyLogo",""),
                        "location": loc, "salary": sal,
                        "job_type": norm_type((it.get("jobType") or ["Full-Time"])[0] if isinstance(it.get("jobType"), list) else (it.get("jobType") or "Full-time")),
                        "work_mode": "Remote",
                        "description": strip_html(it.get("jobDescription","")),
                        "url": it.get("url",""), "source": "Jobicy", "source_color": "#F97316",
                        "tags": json.dumps((it.get("jobIndustry") or [])[:5] if isinstance(it.get("jobIndustry"), list) else []),
                    })
    except Exception as e:
        log.warning(f"[Jobicy] {e}")
    log.info(f"[Jobicy] {len(jobs)}")
    return jobs


def _findwork_headers():
    """FindWork API requires Authorization: Bearer KEY (get key at findwork.dev/developers)."""
    key = os.environ.get("FINDWORK_API_KEY", "")
    if not key:
        return HDR
    return {**HDR, "Authorization": f"Bearer {key}"}


async def scrape_findwork(http):
    jobs = []
    if not os.environ.get("FINDWORK_API_KEY"):
        log.info("[FindWork] FINDWORK_API_KEY not set; skipping (API requires key).")
        return jobs
    try:
        headers = _findwork_headers()
        for kw in ["python", "javascript", "react", "golang", "devops", "data", "typescript", "java"]:
            async with http.get(
                f"https://findwork.dev/api/jobs/?search={kw}&sort_by=date&employment_type=full%20time",
                timeout=TIMEOUT,
                headers=headers,
            ) as r:
                if r.status != 200:
                    continue
                data = await r.json(content_type=None)
                for it in data.get("results", []):
                    loc = it.get("location", "Remote")
                    if not is_usa(loc):
                        continue
                    jobs.append({
                        "id": make_id(it.get("role",""), it.get("company_name",""), it.get("url","")),
                        "title": it.get("role",""), "company": it.get("company_name",""),
                        "company_logo": it.get("company_logo",""), "location": loc,
                        "salary": "", "job_type": "Full-time",
                        "work_mode": "Remote" if it.get("remote") else detect_mode(loc),
                        "description": strip_html(it.get("text","")),
                        "url": it.get("url",""), "source": "FindWork", "source_color": "#6C1F7A",
                        "tags": json.dumps((it.get("keywords") or [])[:6]),
                    })
            await asyncio.sleep(0.2)
    except Exception as e:
        log.warning(f"[FindWork] {e}")
    log.info(f"[FindWork] {len(jobs)}")
    return jobs


# ── Greenhouse public JSON API (no browser, no key) ─────────────

GREENHOUSE_BOARDS = [
    ("stripe", "Stripe"), ("cloudflare", "Cloudflare"), ("notion", "Notion"),
    ("discord", "Discord"), ("figma", "Figma"), ("squareup", "Square"),
    ("coinbase", "Coinbase"), ("datadog", "Datadog"), ("airtable", "Airtable"),
    ("duolingo", "Duolingo"), ("gusto", "Gusto"), ("doordash", "DoorDash"),
    ("instacart", "Instacart"), ("plaid", "Plaid"), ("brex", "Brex"),
    ("ramp", "Ramp"), ("verkada", "Verkada"), ("anduril", "Anduril"),
    ("anthropic", "Anthropic"), ("openai", "OpenAI"),
    ("airbnb", "Airbnb"), ("lyft", "Lyft"), ("pinterest", "Pinterest"),
    ("robinhood", "Robinhood"), ("chime", "Chime"), ("reddit", "Reddit"),
    ("netlify", "Netlify"), ("hashicorp", "HashiCorp"), ("elastic", "Elastic"),
    ("mongodb", "MongoDB"), ("hubspot", "HubSpot"), ("twilio", "Twilio"),
    ("zendesk", "Zendesk"), ("okta", "Okta"), ("paloaltonetworks", "Palo Alto Networks"),
    ("crowdstrike", "CrowdStrike"), ("zscaler", "Zscaler"),
    ("servicenow", "ServiceNow"), ("snowflakecomputing", "Snowflake"),
    ("databricks", "Databricks"), ("dbt-labs", "dbt Labs"),
]

async def scrape_greenhouse(http):
    jobs = []
    for slug, company in GREENHOUSE_BOARDS:
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
            async with http.get(url, timeout=TIMEOUT) as r:
                if r.status != 200:
                    continue
                data = await r.json(content_type=None)
                for it in data.get("jobs", []):
                    loc_obj = it.get("location")
                    loc = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj or "")
                    if not is_usa(loc):
                        continue
                    title = it.get("title", "")
                    jurl  = it.get("absolute_url", "")
                    depts = [d.get("name","") for d in (it.get("departments") or [])]
                    jobs.append({
                        "id": make_id(title, company, jurl),
                        "title": title, "company": company, "company_logo": "",
                        "location": loc or "United States",
                        "salary": "", "job_type": "Full-time",
                        "work_mode": detect_mode(loc + " " + title),
                        "description": strip_html(it.get("content", "")),
                        "url": jurl,
                        "source": "Greenhouse", "source_color": "#24A47F",
                        "tags": json.dumps(depts[:5]),
                    })
        except Exception as e:
            log.warning(f"[Greenhouse/{slug}] {e}")
        await asyncio.sleep(0.3)
    log.info(f"[Greenhouse] {len(jobs)}")
    return jobs


# ═══════════════════════════════════════════════════════════════════
#  BROWSER SCRAPERS  (Scrapling StealthyFetcher — USA only)
# ═══════════════════════════════════════════════════════════════════

_BROWSER_OK = None

def _browser_available():
    global _BROWSER_OK
    if _BROWSER_OK is not None:
        return _BROWSER_OK
    try:
        from scrapling.fetchers import StealthyFetcher  # noqa: F401
        _BROWSER_OK = True
    except ImportError:
        _BROWSER_OK = False
        log.warning("scrapling not installed — browser scrapers disabled")
    return _BROWSER_OK


async def _bfetch(url, timeout_sec=45):
    if not _browser_available():
        return None
    try:
        from scrapling.fetchers import StealthyFetcher
        page = await asyncio.wait_for(
            asyncio.to_thread(StealthyFetcher.fetch, url, headless=True, network_idle=True),
            timeout=timeout_sec,
        )
        return page
    except asyncio.TimeoutError:
        log.warning(f"[Browser] timeout {url[:80]}")
    except Exception as e:
        log.warning(f"[Browser] {type(e).__name__}: {e}")
    return None


def _txt(el):
    try:
        return (el.text or "").strip()
    except Exception:
        return ""

def _css_text(el, *sels):
    for sel in sels:
        try:
            hits = el.css(sel)
            if hits:
                t = _txt(hits[0])
                if t:
                    return t
        except Exception:
            pass
    return ""

def _css_attr(el, sel, attr):
    try:
        hits = el.css(sel)
        if hits and hasattr(hits[0], "attrib"):
            return hits[0].attrib.get(attr, "")
    except Exception:
        pass
    return ""


QUERIES = [
    # AI / ML focused first
    "machine learning engineer", "ml engineer", "ai engineer",
    "applied scientist", "research scientist", "ml researcher",
    "data scientist", "computer vision engineer", "nlp engineer",
    "generative ai engineer", "deep learning engineer",
    # Core software & infra
    "software engineer", "backend developer", "frontend developer",
    "full stack developer", "devops engineer", "data engineer",
    "network engineer", "cloud engineer",
    # Healthcare & medical
    "public health", "epidemiologist", "registered nurse",
    "nurse practitioner", "clinical nurse", "physician",
    "family medicine physician", "dentist", "dental hygienist",
    "physiotherapist", "physical therapist", "occupational therapist",
    "pharmacist", "clinical research coordinator", "healthcare administrator",
    # Other domains
    "product manager", "project manager", "business analyst",
    "mechanical engineer", "electrical engineer", "civil engineer",
    "accountant", "marketing manager", "sales representative",
    "customer service", "human resources", "financial analyst",
    "operations manager", "graphic designer", "teacher", "supply chain",
]


# ── LinkedIn (public job search, no login) ───────────────────────

async def scrape_linkedin():
    jobs = []
    for q in QUERIES[:12]:
        url = (
            f"https://www.linkedin.com/jobs/search/?"
            f"keywords={q.replace(' ','%20')}&location=United%20States"
            f"&geoId=103644278&f_TPR=r86400&position=1&pageNum=0"
        )
        page = await _bfetch(url)
        if not page:
            continue
        try:
            cards = page.css(".base-card, .base-search-card, .job-search-card")
            for c in cards:
                title   = _css_text(c, ".base-search-card__title", "h3", "h4")
                company = _css_text(c, ".base-search-card__subtitle a",
                                       ".base-search-card__subtitle", "h4 a")
                loc     = _css_text(c, ".job-search-card__location")
                link    = (_css_attr(c, "a.base-card__full-link", "href")
                           or _css_attr(c, "a", "href"))
                if not title or not link:
                    continue
                link = link.split("?")[0]
                jobs.append({
                    "id": make_id(title, company, link),
                    "title": title, "company": company, "company_logo": "",
                    "location": loc or "United States", "salary": "",
                    "job_type": "Full-time", "work_mode": detect_mode(loc),
                    "description": "", "url": link,
                    "source": "LinkedIn", "source_color": "#0A66C2",
                    "tags": json.dumps([q]),
                    "easy_apply": "easy apply" in (title + " " + company).lower(),
                })
        except Exception as e:
            log.warning(f"[LinkedIn/{q}] parse: {e}")
        await asyncio.sleep(3)
    log.info(f"[LinkedIn] {len(jobs)}")
    return jobs


# ── Indeed ────────────────────────────────────────────────────────

async def scrape_indeed():
    jobs = []
    for q in QUERIES[:12]:
        url = (
            f"https://www.indeed.com/jobs?"
            f"q={q.replace(' ','+')}&l=United+States&sort=date&fromage=3"
        )
        page = await _bfetch(url)
        if not page:
            continue
        try:
            cards = page.css(
                ".job_seen_beacon, .resultContent, "
                ".jobsearch-ResultsList > li, div[data-jk]"
            )
            for c in cards:
                title   = _css_text(c, ".jobTitle span", ".jobTitle a span",
                                       "h2 a span", "h2 span")
                company = _css_text(c, "[data-testid='company-name']",
                                       ".companyName", ".company_location .companyName")
                loc     = _css_text(c, "[data-testid='text-location']",
                                       ".companyLocation")
                link    = (_css_attr(c, ".jobTitle a", "href")
                           or _css_attr(c, "h2 a", "href")
                           or _css_attr(c, "a", "href"))
                if link and not link.startswith("http"):
                    link = "https://www.indeed.com" + link
                salary = _css_text(c, ".salary-snippet-container",
                                      ".estimated-salary",
                                      "[data-testid='attribute_snippet_testid']")
                if not title:
                    continue
                jobs.append({
                    "id": make_id(title, company, link or ""),
                    "title": title, "company": company, "company_logo": "",
                    "location": loc or "United States", "salary": salary,
                    "job_type": "Full-time", "work_mode": detect_mode(loc),
                    "description": _css_text(c, ".job-snippet", ".heading6"),
                    "url": link or "",
                    "source": "Indeed", "source_color": "#2164F3",
                    "tags": json.dumps([q]),
                    "easy_apply": bool(c.css(".iaLabel, .easily-apply-badge")),
                })
        except Exception as e:
            log.warning(f"[Indeed/{q}] parse: {e}")
        await asyncio.sleep(3)
    log.info(f"[Indeed] {len(jobs)}")
    return jobs


# ── Dice (Tailwind CSS / card-based DOM) ──────────────────────────

def _parse_dice_cards(page, query):
    """Extract jobs from Dice's rendered DOM using link-based discovery."""
    jobs = []
    seen_urls = set()
    try:
        links = page.css('a[href*="/job-detail/"]')
        for a in links:
            href = a.attrib.get("href", "") if hasattr(a, "attrib") else ""
            if not href or href in seen_urls:
                continue
            title = (a.text or "").strip()
            if not title:
                continue
            seen_urls.add(href)
            if not href.startswith("http"):
                href = "https://www.dice.com" + href

            card = a
            for _ in range(8):
                p = card.parent if hasattr(card, "parent") else None
                if p is None:
                    break
                cls = p.attrib.get("class", "") if hasattr(p, "attrib") else ""
                if "rounded" in cls and "border" in cls:
                    card = p
                    break
                card = p

            company = ""
            location = ""
            for p_el in card.css("p"):
                cls = p_el.attrib.get("class", "") if hasattr(p_el, "attrib") else ""
                t = (p_el.text or "").strip()
                if not t:
                    continue
                if "line-clamp" in cls and not company:
                    company = t
                elif "text-zinc-600" in cls and not location:
                    location = t

            jobs.append({
                "id": make_id(title, company, href),
                "title": title, "company": company, "company_logo": "",
                "location": location or "United States", "salary": "",
                "job_type": "Full-time",
                "work_mode": detect_mode(location or title),
                "description": "", "url": href,
                "source": "Dice", "source_color": "#EB1C26",
                "tags": json.dumps([query]),
                "easy_apply": False,
            })
    except Exception as e:
        log.warning(f"[Dice] card parse: {e}")
    return jobs

async def scrape_dice():
    jobs = []
    for q in QUERIES[:12]:
        url = (
            f"https://www.dice.com/jobs?"
            f"q={q.replace(' ','%20')}&location=United%20States"
            f"&countryCode=US&radius=30&radiusUnit=mi&page=1&pageSize=20&language=en"
        )
        page = await _bfetch(url, timeout_sec=55)
        if not page:
            continue
        try:
            found = _parse_dice_cards(page, q)
            jobs.extend(found)
        except Exception as e:
            log.warning(f"[Dice/{q}] {e}")
        await asyncio.sleep(3)
    log.info(f"[Dice] {len(jobs)}")
    return jobs


# ── ZipRecruiter (article-based cards) ────────────────────────────

def _parse_zip_cards(page, query):
    """Extract jobs from ZipRecruiter's rendered article elements."""
    jobs = []
    try:
        articles = page.css("article")
        for card in articles:
            title = _css_text(card, "h2")
            if not title:
                continue

            company = ""
            a_tags = card.css("a")
            for a in a_tags:
                cls = a.attrib.get("class", "") if hasattr(a, "attrib") else ""
                t = (a.text or "").strip()
                if t and "z-[2]" in cls:
                    company = t
                    break
                if t and "break-words" in cls:
                    company = t
                    break
            if not company:
                for a in a_tags:
                    t = (a.text or "").strip()
                    if t and t != title:
                        company = t
                        break

            location = ""
            for p_el in card.css("p, span, div"):
                cls = p_el.attrib.get("class", "") if hasattr(p_el, "attrib") else ""
                t = (p_el.text or "").strip()
                if not t:
                    continue
                if any(x in cls for x in ("text-secondary", "text-muted", "text-gray")):
                    location = t
                    break
                if any(x in t.lower() for x in ("remote", ", ", " - ")):
                    if t != title and t != company:
                        location = t
                        break

            link = ""
            for a in a_tags:
                h = a.attrib.get("href", "") if hasattr(a, "attrib") else ""
                if "/jobs/" in h or "/c/" in h:
                    link = h
                    break
            if not link:
                for a in a_tags:
                    h = a.attrib.get("href", "") if hasattr(a, "attrib") else ""
                    if h and h.startswith("http"):
                        link = h
                        break
            if link and not link.startswith("http"):
                link = "https://www.ziprecruiter.com" + link

            salary = ""
            for el in card.css("p, span"):
                t = (el.text or "").strip()
                if t and ("$" in t or "/yr" in t or "/hr" in t or "salary" in t.lower()):
                    salary = t
                    break

            jobs.append({
                "id": make_id(title, company, link),
                "title": title, "company": company, "company_logo": "",
                "location": location or "United States", "salary": salary,
                "job_type": "Full-time", "work_mode": detect_mode(location),
                "description": "", "url": link,
                "source": "ZipRecruiter", "source_color": "#6BBE45",
                "tags": json.dumps([query]),
                "easy_apply": False,
            })
    except Exception as e:
        log.warning(f"[ZipRecruiter] article parse: {e}")
    return jobs

async def scrape_ziprecruiter():
    jobs = []
    for q in QUERIES[:12]:
        url = (
            f"https://www.ziprecruiter.com/jobs-search?"
            f"search={q.replace(' ','+')}&location=United+States"
        )
        page = await _bfetch(url)
        if not page:
            continue
        try:
            found = _parse_zip_cards(page, q)
            jobs.extend(found)
        except Exception as e:
            log.warning(f"[ZipRecruiter/{q}] {e}")
        await asyncio.sleep(3)
    log.info(f"[ZipRecruiter] {len(jobs)}")
    return jobs


# ── Monster ───────────────────────────────────────────────────────

async def scrape_monster():
    jobs = []
    for q in QUERIES[:12]:
        url = (
            f"https://www.monster.com/jobs/search?"
            f"q={q.replace(' ','+')}&where=United+States&page=1&so=m.h.s"
        )
        page = await _bfetch(url)
        if not page:
            continue
        try:
            cards = page.css(
                "[data-testid='svx_jobCard'], .job-cardstyle, "
                ".job-search-card, article"
            )
            for c in cards:
                title   = _css_text(c, "[data-testid='svx_jobCard-title']",
                                       ".job-cardstyle__JobCardTitle", "h3 a", "h2 a")
                company = _css_text(c, "[data-testid='svx_jobCard-company']",
                                       ".job-cardstyle__JobCardCompany", ".company")
                loc     = _css_text(c, "[data-testid='svx_jobCard-location']",
                                       ".job-cardstyle__JobCardLocation", ".location")
                link    = (_css_attr(c, "a[data-testid='svx_jobCard-title']", "href")
                           or _css_attr(c, "h3 a", "href")
                           or _css_attr(c, "a", "href"))
                if link and not link.startswith("http"):
                    link = "https://www.monster.com" + link
                if not title:
                    continue
                jobs.append({
                    "id": make_id(title, company, link or ""),
                    "title": title, "company": company, "company_logo": "",
                    "location": loc or "United States", "salary": "",
                    "job_type": "Full-time", "work_mode": detect_mode(loc),
                    "description": "", "url": link or "",
                    "source": "Monster", "source_color": "#6E45A5",
                    "tags": json.dumps([q]), "easy_apply": False,
                })
        except Exception as e:
            log.warning(f"[Monster/{q}] parse: {e}")
        await asyncio.sleep(3)
    log.info(f"[Monster] {len(jobs)}")
    return jobs


# ── Glassdoor ─────────────────────────────────────────────────────

async def scrape_glassdoor():
    jobs = []
    for q in QUERIES[:12]:
        url = (
            f"https://www.glassdoor.com/Job/jobs.htm?"
            f"sc.keyword={q.replace(' ','+')}&locT=N&locId=1&sortBy=date_desc"
        )
        page = await _bfetch(url, timeout_sec=55)
        if not page:
            continue
        try:
            cards = page.css(
                "[data-test='jobListing'], .JobCard_jobCard, "
                "li[data-jobid], .react-job-listing"
            )
            for c in cards:
                title   = _css_text(c, "[data-test='job-title']", ".JobCard_jobTitle",
                                       "a[data-test='job-link']", ".jobTitle")
                company = _css_text(c, "[data-test='emp-name']",
                                       ".EmployerProfile_employerName", ".jobCard_employer")
                loc     = _css_text(c, "[data-test='emp-location']",
                                       ".JobCard_location", ".location")
                link    = (_css_attr(c, "a[data-test='job-link']", "href")
                           or _css_attr(c, ".JobCard_jobTitle a", "href")
                           or _css_attr(c, "a", "href"))
                if link and not link.startswith("http"):
                    link = "https://www.glassdoor.com" + link
                salary = _css_text(c, "[data-test='detailSalary']",
                                      ".salary-estimate", ".SalaryEstimate_salaryRange")
                if not title:
                    continue
                jobs.append({
                    "id": make_id(title, company, link or ""),
                    "title": title, "company": company, "company_logo": "",
                    "location": loc or "United States", "salary": salary,
                    "job_type": "Full-time", "work_mode": detect_mode(loc),
                    "description": "", "url": link or "",
                    "source": "Glassdoor", "source_color": "#00A162",
                    "tags": json.dumps([q]), "easy_apply": False,
                })
        except Exception as e:
            log.warning(f"[Glassdoor/{q}] parse: {e}")
        await asyncio.sleep(3)
    log.info(f"[Glassdoor] {len(jobs)}")
    return jobs


# ── Browser runner (sequential to save resources) ────────────────

async def _run_browser_scrapers():
    if not _browser_available():
        log.info("[Browser] Scrapers skipped (no browser/Scrapling); using API sources only.")
        return []
    all_jobs = []
    scrapers = [
        scrape_linkedin, scrape_indeed, scrape_dice,
        scrape_ziprecruiter, scrape_monster, scrape_glassdoor,
    ]
    for fn in scrapers:
        try:
            result = await fn()
            all_jobs.extend(result)
            log.info(f"[Browser] {fn.__name__} done — {len(result)} jobs")
        except Exception as e:
            log.error(f"[Browser] {fn.__name__} crashed: {e}")
    return all_jobs


# ═══════════════════════════════════════════════════════════════════
#  SCRAPE CYCLE
# ═══════════════════════════════════════════════════════════════════

async def _api_group():
    """Run all 6 API scrapers (Remotive, Arbeitnow, The Muse, Jobicy, FindWork, Greenhouse)."""
    async with aiohttp.ClientSession(headers=HDR) as http:
        results = await asyncio.gather(
            scrape_remotive(http), scrape_arbeitnow(http),
            scrape_themuse(http), scrape_jobicy(http),
            scrape_findwork(http), scrape_greenhouse(http),
            return_exceptions=True,
        )
    out = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
        elif isinstance(r, Exception):
            log.error(f"API scraper error: {r}")
    return out


async def _save_jobs_to_db(all_jobs: list) -> int:
    """Dedupe, filter USA, purge expired, insert/refresh. Returns new_count."""
    usa_jobs = [j for j in all_jobs if is_usa(j.get("location", ""))]
    log.info(f"[Cycle] {len(all_jobs)} raw -> {len(usa_jobs)} USA")

    seen = {}
    for j in usa_jobs:
        k = f"{(j.get('title') or '').lower().strip()}|{(j.get('company') or '').lower().strip()}"
        if k and k not in seen:
            seen[k] = j
    deduped = list(seen.values())
    log.info(f"[Cycle] {len(usa_jobs)} USA -> {len(deduped)} deduped")

    now = datetime.utcnow()
    new_count = refreshed = purged = 0

    async with AsyncSessionLocal() as db:
        res = await db.execute(delete(Job).where(Job.expires_at < now))
        purged = res.rowcount

        for j in deduped:
            jid = j.get("id") or make_id(
                j.get("title",""), j.get("company",""), j.get("url",""))
            if not jid:
                continue
            existing = await db.get(Job, jid)
            if existing:
                existing.expires_at = now + timedelta(hours=48)
                if j.get("salary") and not existing.salary:
                    existing.salary = j["salary"]
                if j.get("description") and not existing.description:
                    existing.description = j["description"]
                refreshed += 1
                continue

            db.add(Job(
                id=jid,
                title=(j.get("title") or "")[:299],
                company=(j.get("company") or "")[:199],
                company_logo=(j.get("company_logo") or "")[:499],
                location=(j.get("location") or "")[:299],
                salary=(j.get("salary") or "")[:199],
                job_type=(j.get("job_type") or "Full-time")[:79],
                work_mode=(j.get("work_mode") or "Remote")[:49],
                description=j.get("description") or "",
                url=(j.get("url") or "")[:999],
                source=(j.get("source") or "")[:79],
                source_color=(j.get("source_color") or "#7C3AED")[:9],
                tags=j.get("tags") or "[]",
                easy_apply=j.get("easy_apply", False),
                scraped_at=now,
                expires_at=now + timedelta(hours=48),
            ))
            new_count += 1

        await db.commit()

    log.info(f"[Cycle] +{new_count} new, ~{refreshed} refreshed, -{purged} expired")
    return new_count


async def run_api_only_cycle() -> int:
    """Run only API scrapers (no browser). Use at startup so all 6 API sources fill quickly."""
    log.info("[API-only] Starting")
    api_jobs = await _api_group()
    return await _save_jobs_to_db(api_jobs)


async def run_scrape_cycle() -> int:
    log.info(f"[Cycle] Starting {datetime.utcnow().isoformat()}")

    api_future = _api_group()
    browser_future = _run_browser_scrapers()

    api_jobs, browser_jobs = await asyncio.gather(
        api_future, browser_future, return_exceptions=True,
    )

    all_jobs = []
    if isinstance(api_jobs, list):
        all_jobs.extend(api_jobs)
    elif isinstance(api_jobs, Exception):
        log.error(f"API group: {api_jobs}")
    if isinstance(browser_jobs, list):
        all_jobs.extend(browser_jobs)
    elif isinstance(browser_jobs, Exception):
        log.error(f"Browser group: {browser_jobs}")

    return await _save_jobs_to_db(all_jobs)


# ═══════════════════════════════════════════════════════════════════
#  SCHEDULER
# ═══════════════════════════════════════════════════════════════════

def create_scheduler() -> AsyncIOScheduler:
    s = AsyncIOScheduler()
    s.add_job(
        run_scrape_cycle, "interval", minutes=5,
        id="scrape", replace_existing=True,
        misfire_grace_time=120, max_instances=1,
    )
    s.add_job(
        run_cert_scrape_cycle, "interval", hours=6,
        id="certs", replace_existing=True,
        misfire_grace_time=600, max_instances=1,
    )
    return s
