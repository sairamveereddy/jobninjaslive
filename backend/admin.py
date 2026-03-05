from datetime import datetime, timedelta
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import select, func, and_, desc
from auth import require_admin
from database import AsyncSessionLocal
from models import User, Payment, Job

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/stats")
async def admin_stats():
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        total_users  = (await db.execute(select(func.count(User.id)))).scalar() or 0
        paid_count   = (await db.execute(select(func.count(User.id)).where(User.is_paid==True))).scalar() or 0
        total_rev    = (await db.execute(select(func.sum(Payment.amount_cents)).where(Payment.status=="paid"))).scalar() or 0
        rev_30d      = (await db.execute(select(func.sum(Payment.amount_cents)).where(and_(Payment.status=="paid", Payment.completed_at > now-timedelta(days=30))))).scalar() or 0
        with_resume  = (await db.execute(select(func.count(User.id)).where(User.resume_text.isnot(None)))).scalar() or 0
        live_jobs    = (await db.execute(select(func.count(Job.id)).where(Job.expires_at > now))).scalar() or 0
        new_7d       = (await db.execute(select(func.count(User.id)).where(User.created_at > now-timedelta(days=7)))).scalar() or 0
        src_rows     = (await db.execute(select(Job.source, func.count(Job.id)).where(Job.expires_at > now).group_by(Job.source).order_by(func.count(Job.id).desc()))).all()
    return {
        "users": {"total": total_users, "paid": paid_count, "free": total_users-paid_count,
                  "with_resume": with_resume, "new_7d": new_7d,
                  "conversion": round(paid_count/total_users*100,1) if total_users else 0},
        "revenue": {"total_usd": round(total_rev/100,2), "last_30d_usd": round(rev_30d/100,2)},
        "jobs": {"live": live_jobs, "by_source": [{"source": r[0], "count": r[1]} for r in src_rows]},
    }

@router.get("/users")
async def list_users(page: int = Query(1,ge=1), per: int = Query(50),
                     search: str = Query(""), filter: str = Query("all")):
    async with AsyncSessionLocal() as db:
        stmt = select(User)
        if search:
            stmt = stmt.where(User.email.ilike(f"%{search}%") | User.name.ilike(f"%{search}%"))
        if filter == "paid":    stmt = stmt.where(User.is_paid == True)
        elif filter == "free":  stmt = stmt.where(User.is_paid == False)
        elif filter == "resume":stmt = stmt.where(User.resume_text.isnot(None))
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        rows  = (await db.execute(stmt.order_by(desc(User.created_at)).offset((page-1)*per).limit(per))).scalars().all()
    return {"total": total, "users": [{"id": u.id, "email": u.email, "name": u.name,
        "avatar_url": u.avatar_url, "is_paid": u.is_paid, "is_admin": u.is_admin,
        "has_resume": bool(u.resume_text), "resume_title": u.resume_title,
        "paid_at": u.paid_at.isoformat() if u.paid_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_seen": u.last_seen.isoformat() if u.last_seen else None} for u in rows]}

@router.get("/payments")
async def list_payments(page: int = Query(1,ge=1), per: int = Query(50), status: str = Query("all")):
    async with AsyncSessionLocal() as db:
        stmt = select(Payment, User).join(User, Payment.user_id == User.id, isouter=True)
        if status != "all": stmt = stmt.where(Payment.status == status)
        total_stmt = select(func.count(Payment.id))
        if status != "all": total_stmt = total_stmt.where(Payment.status == status)
        total = (await db.execute(total_stmt)).scalar() or 0
        rows  = (await db.execute(stmt.order_by(desc(Payment.created_at)).offset((page-1)*per).limit(per))).all()
    return {"total": total, "payments": [{"id": p.id, "user_email": u.email if u else "\u2014",
        "user_name": u.name if u else "\u2014", "user_avatar": u.avatar_url if u else "",
        "dodo_id": p.dodo_payment_id or "\u2014", "amount_usd": round(p.amount_cents/100,2),
        "status": p.status, "created_at": p.created_at.isoformat() if p.created_at else None,
        "completed_at": p.completed_at.isoformat() if p.completed_at else None} for p,u in rows]}

@router.post("/users/{user_id}/grant")
async def grant_access(user_id: str):
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_id)
        if not u: raise HTTPException(404)
        u.is_paid = True
        u.paid_at = datetime.utcnow()
        await db.commit()
    return {"ok": True}

@router.post("/users/{user_id}/revoke")
async def revoke_access(user_id: str):
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_id)
        if not u: raise HTTPException(404)
        u.is_paid = False
        await db.commit()
    return {"ok": True}

@router.delete("/users/{user_id}")
async def delete_user(user_id: str):
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_id)
        if u:
            await db.delete(u)
            await db.commit()
    return {"deleted": True}

@router.post("/scrape")
async def trigger_scrape():
    from scraper.scheduler import run_scrape_cycle
    n = await run_scrape_cycle()
    return {"ok": True, "new_jobs": n}
