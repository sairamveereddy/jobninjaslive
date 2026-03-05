## JobNinjas.live — Real‑Time Job Board

JobNinjas.live is a real‑time job board and sub‑product of **jobninjas.ai**. It aggregates fresh roles from multiple sources, auto‑expires jobs after **48 hours**, and surfaces only live listings on a fast, single‑page UI.

- **Backend**: Python 3.12, FastAPI, APScheduler, SQLite (SQLAlchemy async)
- **Scraping**: Scrapling[ai] (Playwright + AsyncFetcher)
- **Frontend**: Vanilla HTML/CSS/JS (`frontend/index.html`)
- **DB**: SQLite for local dev (easy to swap to PostgreSQL for prod)

---

## Project Structure

```text
jobninjas-live/
├── backend/
│   ├── main.py              # FastAPI app + CORS + static mount
│   ├── database.py          # SQLAlchemy async setup + expiry purge
│   ├── models.py            # Job model with expires_at field
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── base.py          # BaseScraper + ScrapedJob dataclass
│   │   ├── remotive.py      # JSON API scraper
│   │   ├── linkedin.py
│   │   ├── indeed.py
│   │   ├── glassdoor.py
│   │   ├── dice.py
│   │   ├── monster.py
│   │   ├── ziprecruiter.py
│   │   ├── wellfound.py
│   │   └── scheduler.py     # APScheduler — runs every 5 min
│   └── requirements.txt
├── frontend/
│   └── index.html           # Full jobninjas.live UI
└── README.md
```

---

## 48‑Hour Expiry Logic

- Each scraped job gets `expires_at = datetime.utcnow() + timedelta(hours=48)` when created.
- Jobs are **never** renewed/extended on re‑scrape — we check for existing `Job(id)` and skip if found.
- A background job (`run_scrape_cycle`) runs every **5 minutes** via APScheduler:
  - Scrapes all sources/queries concurrently
  - Inserts only new jobs
  - Calls `purge_expired_jobs` to `DELETE` where `expires_at < NOW()`
- API queries always filter by `Job.expires_at > now` and `Job.is_active == True`.

---

## Backend Setup

```bash
# 1. Create project
mkdir jobninjas-live && cd jobninjas-live

# 2. Backend
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Scrapling requires a one‑time Playwright install:
scrapling install
```

Environment variables (optional, via `.env` or shell) — sensible defaults are baked in:

```bash
DATABASE_URL=sqlite+aiosqlite:///./jobninjas.db
JOBNINJAS_AI_URL=https://jobninjas.ai
SCRAPE_INTERVAL_MINUTES=5
JOB_EXPIRY_HOURS=48
MAX_PAGES_PER_SOURCE=3
HEADLESS=true
```

Start the backend:

```bash
cd backend
uvicorn main:app --reload --port 8000

# Docs:  http://localhost:8000/docs
# Jobs:  http://localhost:8000/jobs
# Stats: http://localhost:8000/stats
```

On startup, the lifespan handler:

1. Initializes the DB schema
2. Starts the APScheduler
3. Triggers an immediate scrape cycle

---

## Frontend Setup

The backend mounts the SPA at `/`, but you can also serve it standalone.

```bash
cd frontend
python -m http.server 3000
# Open: http://localhost:3000
```

Key frontend behaviors in `index.html`:

- Fetches jobs from `/jobs` with search, location, work‑mode & source filters
- Renders live counts, pagination, and **expiry badges** (`Expires in XXh`)
- Auto‑refreshes jobs + stats every **5 minutes**
- Shows multiple **“Tailor Resume FREE”** CTAs that link to `https://jobninjas.ai`:
  - Nav link
  - Top dismissible banner
  - Sidebar sticky card
  - Every 6th card in the job feed
  - Job detail modal (above Apply)

---

## Production Notes

- Swap SQLite → Postgres by changing `DATABASE_URL` (e.g. `postgresql+asyncpg://...`).
- Deploy FastAPI on Railway, Render, Fly.io, etc.
- Tighten CORS in `main.py` to:

```python
allow_origins=["https://jobninjas.live"]
```

- For higher scale and fewer blocks:
  - Add small randomized `asyncio.sleep` delays in scrapers
  - Use rotating proxies for LinkedIn / Indeed / Glassdoor

