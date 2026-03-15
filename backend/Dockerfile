# Use Playwright image for system deps; Scrapling uses patchright (Playwright fork) for LinkedIn, Indeed, Dice, ZipRecruiter, Monster, Glassdoor.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install patchright's Chromium (Scrapling/StealthyFetcher uses patchright under the hood). --with-deps ensures libs match.
RUN patchright install --with-deps --no-shell chromium

COPY . .

EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
