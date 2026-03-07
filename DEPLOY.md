# Deploy after payments integration

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
- **Netlify** (frontend): If connected to this repo, it will deploy. Proxies for `/api/*`, `/auth/*`, `/payments/*` are in `frontend/netlify.toml`.

## Optional: add README
If you want to commit README changes too:
```bash
git add README.md
git commit --amend --no-edit
git push origin main
```
