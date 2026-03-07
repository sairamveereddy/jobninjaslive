# Deploy after payments integration

## Jobs from every source (LinkedIn, Indeed, Monster, Dice, Glassdoor, ZipRecruiter, etc.)

To get jobs from **all 12 sources** (including LinkedIn, Indeed, Dice, ZipRecruiter, Monster, Glassdoor):

### Force Chromium: Railway must use Docker (not Railpack/Nixpacks)

The repo has **railway.toml** and **railway.json** in both the repo root and **backend/** with `builder = "DOCKERFILE"`. If browser sources are still 0, do this in the Railway dashboard:

1. Open your **backend service** → **Settings**.
2. Under **Build**, set **Builder** to **Dockerfile** (not Railpack or NixPacks). Save.
3. Under **Build**, if there is **Root Directory**, either:
   - Leave it **empty** so the repo root is used and the root **Dockerfile** (Playwright image) is built, or
   - Set it to **backend** so **backend/Dockerfile** (also Playwright) is built.
4. (Optional) Under **Variables**, add **RAILWAY_DOCKERFILE_PATH** = **Dockerfile** so the Dockerfile is explicitly used.
5. **Redeploy**: Deployments → ⋮ on latest → **Redeploy**, or push a small commit to trigger a new build.
6. After the new build, open the **build logs**. You must see a **Docker** build (e.g. "Building Dockerfile", "FROM mcr.microsoft.com/playwright/python"), **not** "Nixpacks" or "Railpack".
7. Wait **5–10 minutes** after a successful Docker deploy. Browser scrapers run in the background; then refresh the job board. LinkedIn, Indeed, Dice, ZipRecruiter, Monster, and Glassdoor counts should start appearing.

- **FindWork**: Set **FINDWORK_API_KEY** in Railway (get one at [findwork.dev/developers](https://findwork.dev/developers)). If unset, FindWork is skipped and shows 0.
- **Arbeitnow**: Includes USA locations plus all **remote** jobs (API is EU-heavy; remote jobs are shown regardless of location).

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
