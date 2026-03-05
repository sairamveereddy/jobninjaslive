"""
Basic certification seeder for jobninjas.live

For v1 we use a curated list of high‑quality certs across AI/ML,
software, cloud, security and healthcare. These are treated like
scraped data and refreshed every 48h so we can evolve the list
without schema changes.
"""

from datetime import datetime, timedelta
import json
import logging
from typing import List, Dict

from database import AsyncSessionLocal
from models import Certification

log = logging.getLogger("jobninjas.certs")


CURATED_CERTS: List[Dict] = [
    # AI / ML
    {
        "id": "google-ml-specialization",
        "title": "Google Advanced Data Analytics / Machine Learning",
        "provider": "Google Career Certificates",
        "category": "AI / Machine Learning",
        "level": "Intermediate",
        "price_type": "subscription",
        "price_text": "Free to audit · Paid certificate",
        "mode": "Online",
        "duration": "6–8 months (part‑time)",
        "url": "https://www.coursera.org/professional-certificates/google-advanced-data-analytics",
        "source": "Coursera",
        "tags": ["ai", "ml", "python", "sql"],
    },
    {
        "id": "deeplearning-ai-ml-engineering",
        "title": "Machine Learning Engineering for Production (MLOps)",
        "provider": "DeepLearning.AI",
        "category": "AI / Machine Learning",
        "level": "Advanced",
        "price_type": "subscription",
        "price_text": "Free to audit · Paid certificate",
        "mode": "Online",
        "duration": "4 months (part‑time)",
        "url": "https://www.coursera.org/specializations/machine-learning-engineering-for-production-mlops",
        "source": "Coursera",
        "tags": ["mlops", "ml", "python"],
    },
    # Software / Cloud
    {
        "id": "aws-cloud-practitioner",
        "title": "AWS Certified Cloud Practitioner",
        "provider": "Amazon Web Services",
        "category": "Cloud",
        "level": "Beginner",
        "price_type": "paid",
        "price_text": "Exam ~$100 · Free digital training",
        "mode": "Online / Testing center",
        "duration": "10–20 hours prep",
        "url": "https://aws.amazon.com/certification/certified-cloud-practitioner/",
        "source": "AWS",
        "tags": ["aws", "cloud", "foundations"],
    },
    {
        "id": "gcp-professional-cloud-architect",
        "title": "Google Professional Cloud Architect",
        "provider": "Google Cloud",
        "category": "Cloud",
        "level": "Advanced",
        "price_type": "paid",
        "price_text": "Exam ~$200 · many free courses",
        "mode": "Online / Testing center",
        "duration": "1–3 months prep",
        "url": "https://cloud.google.com/learn/certification/cloud-architect",
        "source": "Google Cloud",
        "tags": ["gcp", "cloud", "architecture"],
    },
    # Security
    {
        "id": "google-cybersecurity-cert",
        "title": "Google Cybersecurity Professional Certificate",
        "provider": "Google Career Certificates",
        "category": "Cybersecurity",
        "level": "Beginner",
        "price_type": "subscription",
        "price_text": "Free to audit · Paid certificate",
        "mode": "Online",
        "duration": "6 months (part‑time)",
        "url": "https://www.coursera.org/professional-certificates/google-cybersecurity",
        "source": "Coursera",
        "tags": ["security", "soc", "blue team"],
    },
    # Data
    {
        "id": "ibm-data-science-cert",
        "title": "IBM Data Science Professional Certificate",
        "provider": "IBM",
        "category": "Data / Analytics",
        "level": "Beginner",
        "price_type": "subscription",
        "price_text": "Free to audit · Paid certificate",
        "mode": "Online",
        "duration": "3–6 months (part‑time)",
        "url": "https://www.coursera.org/professional-certificates/ibm-data-science",
        "source": "Coursera",
        "tags": ["data science", "python", "sql"],
    },
    # Healthcare / Medical
    {
        "id": "coursera-public-health",
        "title": "Foundations of Public Health Practice",
        "provider": "University of Michigan",
        "category": "Public Health",
        "level": "Beginner",
        "price_type": "subscription",
        "price_text": "Free to audit · Paid certificate",
        "mode": "Online",
        "duration": "4 weeks",
        "url": "https://www.coursera.org/learn/foundations-of-public-health-practice",
        "source": "Coursera",
        "tags": ["public health", "epidemiology"],
    },
    {
        "id": "physiotherapy-coursera",
        "title": "Managing Your Health: The Role of Physical Therapy",
        "provider": "University of Toronto",
        "category": "Physiotherapy",
        "level": "Beginner",
        "price_type": "subscription",
        "price_text": "Free to audit · Paid certificate",
        "mode": "Online",
        "duration": "10 hours",
        "url": "https://www.coursera.org/learn/physical-therapy",
        "source": "Coursera",
        "tags": ["physiotherapy", "rehab"],
    },
]


async def run_cert_scrape_cycle() -> int:
    """Seed / refresh curated certifications with 48h expiry."""
    now = datetime.utcnow()
    expires = now + timedelta(hours=48)
    new_count = updated = purged = 0

    async with AsyncSessionLocal() as db:
        # Purge expired
        from sqlalchemy import delete

        res = await db.execute(delete(Certification).where(Certification.expires_at < now))
        purged = res.rowcount or 0

        # Upsert curated certs
        for c in CURATED_CERTS:
            existing = await db.get(Certification, c["id"])
            tags = json.dumps(c.get("tags") or [])
            if existing:
                existing.title = c["title"]
                existing.provider = c["provider"]
                existing.category = c.get("category")
                existing.level = c.get("level")
                existing.price_type = c.get("price_type")
                existing.price_text = c.get("price_text")
                existing.mode = c.get("mode")
                existing.duration = c.get("duration")
                existing.url = c["url"]
                existing.source = c.get("source")
                existing.tags = tags
                existing.scraped_at = now
                existing.expires_at = expires
                updated += 1
            else:
                db.add(
                    Certification(
                        id=c["id"],
                        title=c["title"],
                        provider=c["provider"],
                        category=c.get("category"),
                        level=c.get("level"),
                        price_type=c.get("price_type"),
                        price_text=c.get("price_text"),
                        mode=c.get("mode"),
                        duration=c.get("duration"),
                        url=c["url"],
                        source=c.get("source"),
                        tags=tags,
                        scraped_at=now,
                        expires_at=expires,
                    )
                )
                new_count += 1

        await db.commit()

    log.info(f"[Certs] +{new_count} new, ~{updated} updated, -{purged} expired")
    return new_count
