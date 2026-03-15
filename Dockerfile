# Backend with Chromium for all job sources (LinkedIn, Indeed, Dice, ZipRecruiter, Monster, Glassdoor).
# Use this when Railway service root is repo root; otherwise backend/Dockerfile is used.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Scrapling uses patchright; install its Chromium so browser scrapers work in production.
RUN patchright install --with-deps --no-shell chromium

COPY backend/ .

EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
