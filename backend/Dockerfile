# Use Playwright image so Chromium is available for LinkedIn, Indeed, Dice, ZipRecruiter, Monster, Glassdoor
# Match the Playwright runtime version (v1.56.0) that Scrapling/patchright expects.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
