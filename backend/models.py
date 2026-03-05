from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, timedelta
import json

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id              = Column(String(36), primary_key=True)
    email           = Column(String(300), unique=True, nullable=False, index=True)
    name            = Column(String(200), default="")
    avatar_url      = Column(String(500), default="")
    google_id       = Column(String(100), unique=True, nullable=True, index=True)

    is_paid         = Column(Boolean, default=False)
    paid_at         = Column(DateTime, nullable=True)
    payment_id      = Column(String(200), nullable=True)

    resume_filename = Column(String(300), nullable=True)
    resume_text     = Column(Text, nullable=True)
    resume_skills   = Column(Text, default="[]")
    resume_title    = Column(String(200), nullable=True)
    resume_uploaded = Column(DateTime, nullable=True)

    created_at      = Column(DateTime, default=datetime.utcnow)
    last_seen       = Column(DateTime, default=datetime.utcnow)
    is_admin        = Column(Boolean, default=False)

    payments        = relationship("Payment", back_populates="user", cascade="all, delete-orphan")

    def skills_list(self):
        try:
            return json.loads(self.resume_skills or "[]")
        except Exception:
            return []

class Payment(Base):
    __tablename__ = "payments"

    id              = Column(String(36), primary_key=True)
    user_id         = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dodo_payment_id = Column(String(200), unique=True, nullable=True, index=True)
    amount_cents    = Column(Integer, default=0)
    currency        = Column(String(10), default="USD")
    status          = Column(String(50), default="pending")
    product_id      = Column(String(200), default="")
    created_at      = Column(DateTime, default=datetime.utcnow)
    completed_at    = Column(DateTime, nullable=True)
    raw_webhook     = Column(Text, default="{}")

    user            = relationship("User", back_populates="payments")

class Job(Base):
    __tablename__ = "jobs"

    id           = Column(String(20), primary_key=True)
    title        = Column(String(300), nullable=False, default="")
    company      = Column(String(200), default="")
    company_logo = Column(String(500), default="")
    location     = Column(String(300), default="")
    salary       = Column(String(200), default="")
    job_type     = Column(String(80),  default="Full-time")
    work_mode    = Column(String(50),  default="Remote")
    description  = Column(Text,        default="")
    url          = Column(String(1000),default="")
    source       = Column(String(80),  default="")
    source_color = Column(String(10),  default="#7C3AED")
    tags         = Column(Text,        default="[]")
    easy_apply   = Column(Boolean,     default=False)
    scraped_at   = Column(DateTime,    default=datetime.utcnow)
    expires_at   = Column(DateTime,    nullable=False)
    is_featured  = Column(Boolean,     default=False)

    def hours_remaining(self):
        return max(0.0, (self.expires_at - datetime.utcnow()).total_seconds() / 3600)

    def tags_list(self):
        try:
            return json.loads(self.tags or "[]")
        except Exception:
            return []


class Certification(Base):
    __tablename__ = "certifications"

    id          = Column(String(64), primary_key=True)
    title       = Column(String(300), nullable=False)
    provider    = Column(String(150), nullable=False)
    category    = Column(String(100), nullable=True)
    level       = Column(String(50), nullable=True)
    price_type  = Column(String(20), nullable=True)   # free, paid, subscription, mixed
    price_text  = Column(String(150), nullable=True)
    mode        = Column(String(50), nullable=True)   # Online, On-site, Hybrid
    duration    = Column(String(100), nullable=True)
    url         = Column(String(1000), nullable=False)
    source      = Column(String(80), nullable=True)
    tags        = Column(Text, nullable=True, default="[]")
    scraped_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at  = Column(DateTime, nullable=False)

    def hours_remaining(self) -> float:
        return max(0.0, (self.expires_at - datetime.utcnow()).total_seconds() / 3600.0)

    def tags_list(self):
        try:
            return json.loads(self.tags or "[]")
        except Exception:
            return []
