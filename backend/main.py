"""
jobNinjas.live — FastAPI v2
uvicorn main:app --reload --port 8000
"""
import asyncio, hashlib, json, logging, os, re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Query, Request, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, and_, or_
from dotenv import load_dotenv
import httpx

load_dotenv()

from database import init_db, AsyncSessionLocal
from models import Job, User, Certification
from auth import router as auth_router, get_current_user
from payments import router as pay_router
from admin import router as admin_router
from resume_parser import parse_resume
from job_matcher import rank_jobs
from scraper.scheduler import run_scrape_cycle, run_api_only_cycle, create_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
log = logging.getLogger("jobninjas")
scheduler = create_scheduler()

# When API sees 0 jobs, run seed once so deploy/cold start always recovers
_seed_on_empty_lock = asyncio.Lock()
_seed_on_empty_done = False


async def _run_seed_once():
    try:
        await seed_remotive_jobs()
    except Exception as e:
        log.warning("On-demand seed failed: %s", e)


def _seed_job_id(title, company, url):
    return hashlib.md5(f"{(title or '').lower().strip()}|{(company or '').lower().strip()}|{url}".encode()).hexdigest()[:16]


def _norm_type(t):
    if not t:
        return "Full-time"
    low = (t or "").lower().replace("_", " ")
    if "contract" in low:
        return "Contract"
    if "part" in low:
        return "Part-time"
    if "intern" in low:
        return "Internship"
    return "Full-time"


def _strip_html(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()[:800]


async def seed_remotive_jobs() -> int:
    """Fetch up to 50 jobs from Remotive and insert. Guarantees jobs on cold start."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get("https://remotive.com/api/remote-jobs?limit=50")
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Seed Remotive fetch failed: %s", e)
        return 0
    jobs = data.get("jobs") or []
    if not jobs:
        return 0
    now = datetime.utcnow()
    exp = now + timedelta(hours=48)
    added = 0
    async with AsyncSessionLocal() as db:
        for it in jobs:
            title = (it.get("title") or "").strip()
            company = (it.get("company_name") or "").strip()
            url = (it.get("url") or "").strip()
            if not title or not url:
                continue
            jid = _seed_job_id(title, company, url)
            existing = await db.get(Job, jid)
            if existing:
                existing.expires_at = exp
                continue
            loc = (it.get("candidate_required_location") or "Remote").strip() or "Remote"
            db.add(Job(
                id=jid,
                title=title[:299],
                company=company[:199],
                company_logo=(it.get("company_logo_url") or "")[:499],
                location=loc[:299],
                salary=(it.get("salary") or "")[:199],
                job_type=_norm_type(it.get("job_type")),
                work_mode="Remote",
                description=_strip_html(it.get("description") or ""),
                url=url[:999],
                source="Remotive",
                source_color="#4F46E5",
                tags=json.dumps((it.get("tags") or [])[:8]),
                easy_apply=False,
                scraped_at=now,
                expires_at=exp,
            ))
            added += 1
        await db.commit()
    log.info("Seed Remotive: %s jobs inserted.", added)
    return added


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # 1) Seed Remotive (fast, guarantees some jobs)
    try:
        n = await asyncio.wait_for(seed_remotive_jobs(), timeout=45.0)
        if n:
            log.info("Seed finished: %s jobs in DB.", n)
    except Exception as e:
        log.warning("Seed failed: %s", e)
    # 2) API-only cycle: all 6 API sources (Arbeitnow, The Muse, Jobicy, FindWork, Greenhouse + Remotive)
    try:
        log.info("Running API-only scrape (all 6 API sources)...")
        n = await asyncio.wait_for(run_api_only_cycle(), timeout=120.0)
        log.info("API-only scrape finished: %s new/refreshed jobs.", n)
    except asyncio.TimeoutError:
        log.warning("API-only scrape timed out after 120s.")
    except Exception as e:
        log.exception("API-only scrape failed: %s", e)
    # 3) Start scheduler (full cycle every 5 min, includes browser sources)
    scheduler.start()
    # 4) Run one full cycle in background (LinkedIn, Indeed, Dice, etc. — needs Chromium/Docker)
    async def _first_full_cycle():
        try:
            log.info("Running first full scrape (API + browser) in background...")
            await asyncio.wait_for(run_scrape_cycle(), timeout=600.0)
        except asyncio.TimeoutError:
            log.warning("First full scrape timed out; scheduler will retry every 5 min.")
        except Exception as e:
            log.warning("First full scrape failed: %s; scheduler will retry.", e)
    asyncio.create_task(_first_full_cycle())
    yield
    scheduler.shutdown()

app = FastAPI(title="jobNinjas.live", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=True)

app.include_router(auth_router)
app.include_router(pay_router)
app.include_router(admin_router)

_CAP_EXEMPT_KW = [
    "university", "college", "institute of technology", "school of medicine",
    "medical center", "medical school", "hospital", "health system", "clinic",
    "research institute", "research center", "national lab", "laboratory",
    "foundation", "non-profit", "nonprofit", "academy of sciences",
    "smithsonian", "nih", "nasa", "doe", "department of",
]
_VISA_KW = [
    "visa sponsor", "h-1b", "h1b", "sponsorship available", "will sponsor",
    "immigration sponsor", "work visa", "visa assistance", "sponsor visa",
    "employment visa", "green card", "ead", "opt", "cpt",
]
_STARTUP_KW = [
    "series a", "series b", "series c", "seed stage", "startup", "early-stage",
    "early stage", "venture-backed", "yc ", "y combinator",
]
_STARTUP_COMPANIES = {
    "stripe", "notion", "figma", "discord", "airtable", "brex", "ramp",
    "plaid", "gusto", "verkada", "anduril", "anthropic", "openai",
    "coinbase", "instacart", "doordash", "duolingo",
}

def _parse_experience_years(text):
    """Extract (min_years, max_years) from job title/description. Returns (None, None) if no clear match."""
    if not text:
        return None, None
    text = (text or "").lower()
    # Patterns: "5 years", "5+ years", "5 - 7 years", "3-5 years", "10+ years", "at least 5 years"
    min_y, max_y = None, None
    # Single number or X+: (\d+)\+?\s*years?
    for m in re.finditer(r"(\d+)\s*[\+\-]\s*(\d+)\s*years?", text):
        a, b = int(m.group(1)), int(m.group(2))
        low, high = min(a, b), max(a, b)
        if min_y is None or low < min_y:
            min_y = low
        if max_y is None or high > max_y:
            max_y = high
    for m in re.finditer(r"(\d+)\+\s*years?", text):
        n = int(m.group(1))
        if min_y is None or n < min_y:
            min_y = n
        if max_y is None or n > max_y:
            max_y = n
    for m in re.finditer(r"\b(\d+)\s*years?\b", text):
        n = int(m.group(1))
        if min_y is None or n < min_y:
            min_y = n
        if max_y is None or n > max_y:
            max_y = n
    if "senior" in text and max_y is None and min_y is None:
        min_y, max_y = 10, None  # senior often implies 10+
    if "junior" in text or "entry" in text or "entry-level" in text:
        if max_y is None or max_y > 5:
            max_y = 5 if max_y is None else min(max_y, 5)
    return min_y, max_y


def _match_experience(experience, job_row):
    """True if job matches experience filter (0, 1, ..., 9, 10plus)."""
    blob = f"{(job_row.title or '')} {(job_row.description or '')}"
    min_y, max_y = _parse_experience_years(blob)
    if experience == "10plus":
        if min_y is not None and min_y >= 10:
            return True
        if max_y is not None and max_y >= 10:
            return True
        if "10+" in blob or "senior" in blob.lower():
            return True
        return False
    try:
        n = int(experience)
    except (TypeError, ValueError):
        return True
    if n < 0 or n > 9:
        return True
    # Job requirement overlaps year n: min_y <= n <= max_y (or unbounded side)
    if min_y is None and max_y is None:
        return False
    return (min_y is None or min_y <= n) and (max_y is None or max_y >= n)


def _match_category(cat, job_row):
    co = (job_row.company or "").lower()
    desc = (job_row.description or "").lower()
    title = (job_row.title or "").lower()
    jtype = (job_row.job_type or "").lower()
    blob = f"{title} {co} {desc}"
    if cat == "full-time":
        return "full" in jtype and "intern" not in jtype
    if cat == "contract":
        return "contract" in jtype
    if cat == "internship":
        return "intern" in jtype or "intern" in title
    if cat == "cap-exempt":
        return any(k in co for k in _CAP_EXEMPT_KW)
    if cat == "visa":
        return any(k in blob for k in _VISA_KW)
    if cat == "startup":
        if co.strip() in _STARTUP_COMPANIES:
            return True
        return any(k in blob for k in _STARTUP_KW)
    return True


def _diversify(items, key_fn, max_per_round=2):
    """Round-robin reorder: pick max_per_round items per group before cycling."""
    from collections import OrderedDict
    buckets = OrderedDict()
    for item in items:
        k = key_fn(item)
        buckets.setdefault(k, []).append(item)
    result = []
    rnd = 0
    while True:
        added = False
        for k in list(buckets.keys()):
            start = rnd * max_per_round
            chunk = buckets[k][start:start + max_per_round]
            if chunk:
                result.extend(chunk)
                added = True
        rnd += 1
        if not added:
            break
    return result


@app.get("/api/jobs")
async def get_jobs(
    request: Request,
    q: str = Query(""), location: str = Query(""),
    source: str = Query(""), mode: str = Query(""),
    jtype: str = Query(""), tier: str = Query(""),
    category: str = Query(""), experience: str = Query(""),
    page: int = Query(1, ge=1), per: int = Query(20, ge=1, le=100),
):
    now = datetime.utcnow()
    user_jwt = get_current_user(request)
    user_skills, user_title = [], ""

    if user_jwt:
        async with AsyncSessionLocal() as db:
            u = await db.get(User, user_jwt["sub"])
            if u and u.resume_text:
                user_skills = u.skills_list()
                user_title  = u.resume_title or ""

    need_postfilter = bool(category)

    def _build_filters():
        f = [Job.expires_at > now]
        if q:
            f.append(or_(Job.title.ilike(f"%{q}%"), Job.company.ilike(f"%{q}%")))
        if location:
            f.append(Job.location.ilike(f"%{location}%"))
        if source and source != "all":
            src_list = [s.strip() for s in source.split(",") if s.strip()]
            if len(src_list) == 1:
                f.append(Job.source.ilike(f"%{src_list[0]}%"))
            elif src_list:
                f.append(or_(*[Job.source.ilike(f"%{s}%") for s in src_list]))
        if mode and mode not in ("", "Any"):
            f.append(Job.work_mode == mode)
        if jtype and jtype not in ("", "Any"):
            f.append(Job.job_type == jtype)
        if category == "full-time":
            f.append(Job.job_type == "Full-time")
        elif category == "contract":
            f.append(Job.job_type == "Contract")
        elif category == "internship":
            f.append(or_(Job.job_type == "Internship", Job.title.ilike("%intern%")))
        return f

    filters = _build_filters()
    if category == "full-time":
        need_postfilter = False
    elif category == "contract":
        need_postfilter = False
    elif category == "internship":
        need_postfilter = False

    async with AsyncSessionLocal() as db:
        total = (await db.execute(
            select(func.count(Job.id)).where(and_(*filters))
        )).scalar() or 0

        rows = (await db.execute(
            select(Job).where(and_(*filters))
            .order_by(Job.scraped_at.desc())
            .limit(3000)
        )).scalars().all()

    # If DB is empty (e.g. cold start), run full API-only cycle once so all 6 API sources get jobs
    did_seed = False
    if total == 0:
        async with _seed_on_empty_lock:
            global _seed_on_empty_done
            if not _seed_on_empty_done:
                log.info("API saw 0 jobs; running Remotive seed first, then API-only cycle...")
                try:
                    await seed_remotive_jobs()
                    did_seed = True
                except Exception as e:
                    log.warning("Remotive seed failed: %s", e)
                try:
                    await asyncio.wait_for(run_api_only_cycle(), timeout=90.0)
                    _seed_on_empty_done = True
                    did_seed = True
                except asyncio.TimeoutError:
                    log.warning("On-demand API cycle timed out.")
                    _seed_on_empty_done = True
                    did_seed = True
                except Exception as e:
                    log.warning("On-demand API cycle failed: %s", e)
                    _seed_on_empty_done = True
                    did_seed = True
        if did_seed:
            async with AsyncSessionLocal() as db2:
                total = (await db2.execute(
                    select(func.count(Job.id)).where(and_(*filters))
                )).scalar() or 0
                rows = (await db2.execute(
                    select(Job).where(and_(*filters))
                    .order_by(Job.scraped_at.desc())
                    .limit(3000)
                )).scalars().all()

    if need_postfilter:
        rows = [r for r in rows if _match_category(category, r)]
        total = len(rows)

    _exp_vals = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10plus")
    if experience and experience in _exp_vals:
        rows = [r for r in rows if _match_experience(experience, r)]
        total = len(rows)

    # Keep newest jobs on top (no diversification — strict scraped_at desc)
    jobs = [{
        "id": j.id, "title": j.title, "company": j.company, "company_logo": j.company_logo,
        "location": j.location, "salary": j.salary, "job_type": j.job_type,
        "work_mode": j.work_mode, "description": (j.description or "")[:300],
        "url": j.url, "source": j.source, "source_color": j.source_color,
        "tags": j.tags_list(), "easy_apply": j.easy_apply,
        "scraped_at": j.scraped_at.isoformat() if j.scraped_at else "",
        "hours_left": round(j.hours_remaining(), 1), "is_featured": j.is_featured,
        "match_score": 0, "match_tier": "none", "matched_skills": [],
    } for j in rows]

    if user_skills:
        jobs = rank_jobs(jobs, user_skills, user_title)
        if tier and tier not in ("", "all"):
            jobs = [j for j in jobs if j["match_tier"] == tier]
        total = len(jobs)

    start = (page - 1) * per
    jobs  = jobs[start:start + per]

    # When 0 jobs with no filters, backend may still be seeding (cold start)
    empty_reason = None
    if total == 0 and not (q or location or (source and source != "all") or mode or jtype or category or experience):
        empty_reason = "loading"

    return {"total": total, "page": page, "pages": max(1,(total+per-1)//per),
            "has_resume": bool(user_skills), "user_title": user_title, "jobs": jobs,
            "empty_reason": empty_reason}

@app.get("/api/stats")
async def get_stats():
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        active_q = Job.expires_at > now
        total  = (await db.execute(select(func.count(Job.id)).where(active_q))).scalar() or 0
        remote = (await db.execute(select(func.count(Job.id)).where(and_(active_q, Job.work_mode == "Remote")))).scalar() or 0
        src    = (await db.execute(
            select(Job.source, Job.source_color, func.count(Job.id))
            .where(active_q).group_by(Job.source, Job.source_color)
            .order_by(func.count(Job.id).desc())
        )).all()
        latest = (await db.execute(select(func.max(Job.scraped_at)).where(active_q))).scalar()
        recent_cutoff = now - timedelta(minutes=10)
        added_recent = (await db.execute(
            select(func.count(Job.id)).where(and_(active_q, Job.scraped_at >= recent_cutoff))
        )).scalar() or 0
    # If DB empty, run full API-only cycle once (same as get_jobs) so all 6 sources get counts
    if total == 0:
        async with _seed_on_empty_lock:
            global _seed_on_empty_done
            if not _seed_on_empty_done:
                log.info("Stats saw 0 jobs; running on-demand API-only cycle (all 6 sources)...")
                try:
                    await asyncio.wait_for(run_api_only_cycle(), timeout=90.0)
                    _seed_on_empty_done = True
                except (asyncio.TimeoutError, Exception) as e:
                    log.warning("On-demand API cycle failed: %s; trying Remotive seed.", e)
                    await _run_seed_once()
                    _seed_on_empty_done = True
        async with AsyncSessionLocal() as db2:
            active_q = Job.expires_at > now
            total = (await db2.execute(select(func.count(Job.id)).where(active_q))).scalar() or 0
            remote = (await db2.execute(select(func.count(Job.id)).where(and_(active_q, Job.work_mode == "Remote")))).scalar() or 0
            src = (await db2.execute(
                select(Job.source, Job.source_color, func.count(Job.id))
                .where(active_q).group_by(Job.source, Job.source_color)
                .order_by(func.count(Job.id).desc())
            )).all()
            latest = (await db2.execute(select(func.max(Job.scraped_at)).where(active_q))).scalar()
            added_recent = (await db2.execute(
                select(func.count(Job.id)).where(and_(active_q, Job.scraped_at >= recent_cutoff))
            )).scalar() or 0
    return {
        "total": total,
        "remote": remote,
        "remote_pct": round(remote/total*100) if total else 0,
        "sources": [{"name": r[0], "color": r[1], "count": r[2]} for r in src],
        "last_updated": (latest or now).isoformat(),
        "added_recent": added_recent,
        "expiry_hours": 48,
    }


@app.get("/api/certs")
async def get_certs(
    q: str = Query(""),
    provider: str = Query(""),
    category: str = Query(""),
    price: str = Query(""),      # "", "free", "paid"
    level: str = Query(""),
    mode: str = Query(""),
    page: int = Query(1, ge=1),
    per: int = Query(20, ge=1, le=100),
):
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        filters = [Certification.expires_at > now]
        if q:
            like = f"%{q}%"
            filters.append(
                or_(
                    Certification.title.ilike(like),
                    Certification.provider.ilike(like),
                    Certification.category.ilike(like),
                )
            )
        if provider:
            filters.append(Certification.provider.ilike(f"%{provider}%"))
        if category:
            filters.append(Certification.category.ilike(f"%{category}%"))
        if price in ("free", "paid"):
            filters.append(Certification.price_type == price)
        if level:
            filters.append(Certification.level.ilike(f"%{level}%"))
        if mode:
            filters.append(Certification.mode == mode)

        total = (
            await db.execute(
                select(func.count(Certification.id)).where(and_(*filters))
            )
        ).scalar() or 0

        rows = (
            await db.execute(
                select(Certification)
                .where(and_(*filters))
                .order_by(Certification.scraped_at.desc())
                .offset((page - 1) * per)
                .limit(per)
            )
        ).scalars().all()

    certs = [
        {
            "id": c.id,
            "title": c.title,
            "provider": c.provider,
            "category": c.category,
            "level": c.level,
            "price_type": c.price_type,
            "price_text": c.price_text,
            "mode": c.mode,
            "duration": c.duration,
            "url": c.url,
            "source": c.source,
            "tags": c.tags_list(),
            "scraped_at": c.scraped_at.isoformat(),
            "hours_left": round(c.hours_remaining(), 1),
        }
        for c in rows
    ]

    return {
        "total": total,
        "page": page,
        "pages": max(1, (total + per - 1) // per),
        "certs": certs,
    }

@app.post("/api/resume/upload")
async def upload_resume(request: Request, file: UploadFile = File(...)):
    user_jwt = get_current_user(request)
    if not user_jwt:
        raise HTTPException(401, "Sign in required")

    ext = (file.filename or "").lower().rsplit(".", 1)[-1]
    if ext not in ("pdf","docx","doc"):
        raise HTTPException(400, "Only PDF and DOCX supported")

    data = await file.read()
    if len(data) > 5*1024*1024:
        raise HTTPException(400, "Max file size: 5MB")

    try:
        parsed = parse_resume(data, file.filename)
    except Exception as e:
        raise HTTPException(422, f"Could not parse resume: {e}")

    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_jwt["sub"])
        if not u: raise HTTPException(404)
        u.resume_filename = file.filename
        u.resume_text     = parsed["text"]
        u.resume_skills   = json.dumps(parsed["skills"])
        u.resume_title    = parsed["title"]
        u.resume_uploaded = datetime.utcnow()
        await db.commit()

    return {"ok": True, "skills": parsed["skills"], "title": parsed["title"],
            "skill_count": parsed["skill_count"], "word_count": parsed["word_count"]}

@app.get("/api/resume")
async def get_resume(request: Request):
    u = get_current_user(request)
    if not u: return {"has_resume": False}
    async with AsyncSessionLocal() as db:
        user = await db.get(User, u["sub"])
        if not user or not user.resume_text: return {"has_resume": False}
        return {"has_resume": True, "filename": user.resume_filename,
                "skills": user.skills_list(), "title": user.resume_title,
                "uploaded_at": user.resume_uploaded.isoformat() if user.resume_uploaded else None}

@app.get("/api/health")
async def health():
    """Lightweight endpoint for keep-alive pings. Ping every 4–5 min so Railway does not sleep and the 5-min scraper keeps running."""
    return {"ok": True, "scheduler": "running"}

@app.post("/api/scrape")
async def trigger_scrape():
    n = await run_scrape_cycle()
    return {"ok": True, "new_jobs": n}

# Only serve frontend when directory exists (local dev). On Railway we deploy backend only; Vercel serves frontend.
_frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="static")
