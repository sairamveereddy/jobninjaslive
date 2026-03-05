"""
Score each job against user's resume skills.
HIGH >= 60 pts | MEDIUM 30-59 | LOW < 30
"""
import re
from resume_parser import SKILLS_DB, SKILL_WEIGHTS

TIER_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}

def score_job(job: dict, user_skills: list, user_title: str) -> dict:
    if not user_skills:
        return {"score": 0, "tier": "none", "matched_skills": []}

    job_text = f"{job.get('title','')} {job.get('description','')} {' '.join(job.get('tags',[]) if isinstance(job.get('tags'), list) else [])}".lower()
    user_set = {s.lower() for s in user_skills}
    score, matched = 0, []

    for cat, skills in SKILLS_DB.items():
        w = SKILL_WEIGHTS.get(cat, 5)
        for s in skills:
            if s.lower() in user_set and re.search(r"\b" + re.escape(s.lower()) + r"\b", job_text):
                score += w
                matched.append(s)

    if user_title:
        overlap = set(user_title.lower().split()) & set(job.get("title","").lower().split())
        score += 25 if len(overlap) >= 2 else (10 if overlap else 0)

    if job.get("work_mode","").lower() == "remote":
        score += 5
    if job.get("salary","").strip():
        score += 3

    score = min(score, 100)
    tier  = "high" if score >= 60 else ("medium" if score >= 30 else "low")
    return {"score": score, "tier": tier, "matched_skills": matched[:8]}

def rank_jobs(jobs: list, user_skills: list, user_title: str) -> list:
    for j in jobs:
        r = score_job(j, user_skills, user_title)
        j["match_score"]    = r["score"]
        j["match_tier"]     = r["tier"]
        j["matched_skills"] = r["matched_skills"]
    jobs.sort(key=lambda x: (TIER_ORDER.get(x.get("match_tier","none"), 3), -x.get("match_score", 0)))
    return jobs
