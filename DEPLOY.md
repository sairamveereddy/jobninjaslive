# Deploy after payments integration

## Jobs from every source (LinkedIn, Indeed, Monster, Dice, Glassdoor, ZipRecruiter, etc.)

To get jobs from **all 12 sources** (including LinkedIn, Indeed, Dice, ZipRecruiter, Monster, Glassdoor):

1. **Backend must build with Docker** so Chromium (Playwright) is available. We use `railway.toml` in repo root and in `backend/` to set `builder = "DOCKERFILE"`.
2. **Root Directory in Railway**: If your backend service uses **repo root**, the root `Dockerfile` (which uses the Playwright image) is used. If it uses **`backend`** as root, `backend/Dockerfile` (also Playwright) is used. Both include Chromium.
3. **Check build logs**: In Railway → your backend service → Deployments → latest build. You should see a **Docker** build (e.g. "Building Dockerfile"), not Nixpacks/Railpack. If you see Nixpacks, set **Settings → Build → Builder** to **Dockerfile** (or ensure no other builder overrides the `railway.toml` in your code).
4. **After deploy**: Browser scrapers run in the first full cycle (in background, up to ~10 min) and then every 5 minutes. Give it 5–10 minutes after deploy, then refresh the job board; LinkedIn, Indeed, Dice, ZipRecruiter, Monster, and Glassdoor counts should start appearing.

**FindWork** still requires `FINDWORK_API_KEY` (get one at findwork.dev/developers) to show jobs from that source.

## Summary
- **Payments**: Dodo integrated; runs **without** `DODO_WEBHOOK_SECRET` (webhook still processes `payment.succeeded` when secret is unset).
- **.env** is in `.gitignore` — never commit it. Set vars in **Railway** (and Netlify if needed).

## Push to Git (run in your terminal)

```bash
cd c:\Users\vsair\OneDrive\Documents\jobninjas.live

# If index.lock exists, remove it first:
# del .git\index.lock

# Latest: fix 0 jobs on deploy
git add backend/database.py backend/main.py backend/requirements.txt backend/scraper/scheduler.py DEPLOY.md
git status
git commit -m "Fix 0 jobs on deploy: Postgres async driver, 180s initial scrape, relax location filter"
git push origin main
```

**Do not** `git add .env` — it contains your Dodo API key.

## After push
- **Railway** (backend): Redeploys from `main`. Ensure env vars are set: `DODO_API_KEY`, `DODO_PRODUCT_ID`, `ADMIN_EMAIL`, etc. `DODO_WEBHOOK_SECRET` is optional.
  - **All job sources (incl. LinkedIn, Indeed, etc.)**: Railway must build with **Docker**. If your service root is the **repo root**, the root `Dockerfile` (Playwright/Chromium image) is used. If root is `backend`, use `backend/Dockerfile`. Without Docker, only API sources run; browser sources need Chromium.
- **FindWork source**: FindWork.dev API requires a key. Set `FINDWORK_API_KEY` in Railway (get one at findwork.dev/developers) to enable FindWork jobs. If unset, FindWork is skipped.
- **Netlify** (frontend): If connected to this repo, it will deploy. Proxies for `/api/*`, `/auth/*`, `/payments/*` are in `frontend/netlify.toml`.

## Optional: add README
If you want to commit README changes too:
```bash
git add README.md
git commit --amend --no-edit
git push origin main
```
