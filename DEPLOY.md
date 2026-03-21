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

## Dodo Payments

- **Required env (Railway)**: `DODO_API_KEY`, `DODO_PRODUCT_ID`. Create a $4.99 one-time product in the [Dodo dashboard](https://dashboard.dodopayments.com) and set its ID as `DODO_PRODUCT_ID`.
- **Optional**: `DODO_WEBHOOK_SECRET` — if set, webhook requests are signature-verified; if unset, webhooks still process `payment.succeeded`.
- **Optional**: `APP_URL` — base URL for success redirect (e.g. `https://jobninjas.live`). Defaults to `http://localhost:8000`. Used as `return_url` so after payment users land on `APP_URL/?payment=success`.
- **Optional**: `DODO_API_BASE` — API base URL. Default `https://api.dodopayments.com`. For test mode use `https://test.dodopayments.com`.
- **Webhook URL** (set in Dodo dashboard): `https://your-backend.up.railway.app/payments/webhook` (or your live backend URL + `/payments/webhook`). Subscribe to `payment.succeeded` (and optionally `payment.failed`, `payment.cancelled`).

## Summary
- **Payments**: Dodo integrated; checkout uses Dodo’s `/checkouts` API; webhook matches by `metadata.user_id` or payment id.
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

## Vercel + GitLab (frontend)

Your HTML/CSS/JS lives under **`frontend/`**, not the repo root. If **Root Directory** is wrong, Vercel shows **404** because there is no `index.html` at the repository root.

### One-time Vercel project settings

1. Open the project on Vercel → **Settings** → **General**.
2. **Root Directory** → **Edit** → set to **`frontend`** → Save.
3. **Build & Deployment**:
   - **Framework Preset**: **Other** (or “Other” / no framework).
   - **Build Command**: leave **empty** (static files only).
   - **Output Directory**: leave **default** / empty (not needed when root is `frontend`).
4. **Git** → confirm the repo is your **GitLab** repo and branch is **`main`**.
5. Redeploy: **Deployments** → latest deployment → **⋯** → **Redeploy** (or push a commit).

### What’s in the repo

- **`frontend/vercel.json`** — rewrites `/api/*`, `/auth/*`, `/payments/*`, `/admin/*` to your **Railway** backend (same idea as `frontend/netlify.toml`). If you move the API to AWS later, update the destination URLs in that file.

### After changing Root Directory

Commit and push `frontend/vercel.json`, then redeploy so Vercel picks up the rewrites.

## Optional: add README
If you want to commit README changes too:
```bash
git add README.md
git commit --amend --no-edit
git push origin main
```
