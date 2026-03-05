"""
jobNinjas.live — FastAPI v2
uvicorn main:app --reload --port 8000
"""
import asyncio, json, logging, os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Query, Request, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, and_, or_
from dotenv import load_dotenv

load_dotenv()

from database import init_db, AsyncSessionLocal
from models import Job, User, Certification
from auth import router as auth_router, get_current_user
from payments import router as pay_router
from admin import router as admin_router
from resume_parser import parse_resume
from job_matcher import rank_jobs
from scraper.scheduler import run_scrape_cycle, create_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
log = logging.getLogger("jobninjas")
scheduler = create_scheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(run_scrape_cycle())
    scheduler.start()
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
    category: str = Query(""),
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

    async with AsyncSessionLocal() as db:
        filters = [Job.expires_at > now]
        if q:
            filters.append(or_(Job.title.ilike(f"%{q}%"), Job.company.ilike(f"%{q}%")))
        if location:
            filters.append(Job.location.ilike(f"%{location}%"))
        if source and source != "all":
            src_list = [s.strip() for s in source.split(",") if s.strip()]
            if len(src_list) == 1:
                filters.append(Job.source.ilike(f"%{src_list[0]}%"))
            elif src_list:
                filters.append(or_(*[Job.source.ilike(f"%{s}%") for s in src_list]))
        if mode and mode not in ("", "Any"):
            filters.append(Job.work_mode == mode)
        if jtype and jtype not in ("", "Any"):
            filters.append(Job.job_type == jtype)

        if category == "full-time":
            filters.append(Job.job_type == "Full-time")
            need_postfilter = False
        elif category == "contract":
            filters.append(Job.job_type == "Contract")
            need_postfilter = False
        elif category == "internship":
            filters.append(or_(Job.job_type == "Internship", Job.title.ilike("%intern%")))
            need_postfilter = False

        total = (await db.execute(
            select(func.count(Job.id)).where(and_(*filters))
        )).scalar() or 0

        rows = (await db.execute(
            select(Job).where(and_(*filters))
            .order_by(Job.scraped_at.desc())
            .limit(3000)
        )).scalars().all()

    if need_postfilter:
        rows = [r for r in rows if _match_category(category, r)]
        total = len(rows)

    rows = _diversify(rows, lambda j: (j.company or "").lower(), max_per_round=2)

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

    return {"total": total, "page": page, "pages": max(1,(total+per-1)//per),
            "has_resume": bool(user_skills), "user_title": user_title, "jobs": jobs}

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

@app.post("/api/scrape")
async def trigger_scrape():
    n = await run_scrape_cycle()
    return {"ok": True, "new_jobs": n}

app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")
