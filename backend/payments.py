"""
Dodo Payments — $4.99 one-time, valid 1 year.

POST /payments/checkout  -> { checkout_url }
GET  /payments/status    -> { is_paid }
POST /payments/webhook   -> Dodo Payments calls this when paid

Env: DODO_API_KEY, DODO_WEBHOOK_SECRET, DODO_PRODUCT_ID (create $4.99 product in Dodo dashboard).
Optional: DODO_PRICE_CENTS=499, APP_URL (for return_url), DODO_API_BASE (default https://api.dodopayments.com).

If users table already exists, add column: ALTER TABLE users ADD COLUMN paid_until DATETIME NULL;
"""
import hashlib, hmac, json, logging, os, uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException
import httpx
from auth import get_current_user

log = logging.getLogger("jobninjas.payments")
router = APIRouter(prefix="/payments", tags=["payments"])

DODO_API_KEY        = os.getenv("DODO_API_KEY", "")
DODO_WEBHOOK_SECRET = os.getenv("DODO_WEBHOOK_SECRET", "")
DODO_PRODUCT_ID     = os.getenv("DODO_PRODUCT_ID", "")
DODO_PRICE_CENTS    = int(os.getenv("DODO_PRICE_CENTS", "499"))  # $4.99
APP_URL             = os.getenv("APP_URL", "http://localhost:8000").rstrip("/")
DODO_API_BASE       = os.getenv("DODO_API_BASE", "https://api.dodopayments.com").rstrip("/")

@router.post("/checkout")
async def create_checkout(request: Request):
    user_jwt = get_current_user(request)
    if not user_jwt:
        raise HTTPException(401, "Sign in with Google first")

    from database import AsyncSessionLocal
    from models import User, Payment

    async with AsyncSessionLocal() as db:
        db_user = await db.get(User, user_jwt["sub"])
        if db_user and _is_active_paid(db_user):
            return {"already_paid": True}

    if not DODO_API_KEY:
        raise HTTPException(503, "DODO_API_KEY not configured in .env")
    if not DODO_PRODUCT_ID:
        raise HTTPException(503, "DODO_PRODUCT_ID not configured in .env")

    payment_uuid = str(uuid.uuid4())
    return_url = f"{APP_URL}/?payment=success"
    payload = {
        "product_cart": [{"product_id": DODO_PRODUCT_ID, "quantity": 1}],
        "customer": {"email": user_jwt.get("email") or "", "name": (user_jwt.get("name") or "").strip() or None},
        "return_url": return_url,
        "metadata": {"user_id": user_jwt["sub"], "payment_id": payment_uuid},
    }
    # Remove None values so Dodo API doesn't complain
    if payload["customer"].get("name") is None:
        del payload["customer"]["name"]

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{DODO_API_BASE}/checkouts",
                json=payload,
                headers={"Authorization": f"Bearer {DODO_API_KEY}", "Content-Type": "application/json"},
                timeout=20,
            )
            r.raise_for_status()
            dodo = r.json()

        session_id = dodo.get("session_id") or dodo.get("id") or ""
        checkout_url = dodo.get("checkout_url") or dodo.get("url") or ""

        async with AsyncSessionLocal() as db:
            db.add(Payment(
                id=payment_uuid, user_id=user_jwt["sub"],
                dodo_payment_id=session_id,
                amount_cents=DODO_PRICE_CENTS, status="pending",
                product_id=DODO_PRODUCT_ID,
            ))
            await db.commit()

        if not checkout_url:
            log.warning("Dodo checkout response missing checkout_url: %s", dodo)
        return {"checkout_url": checkout_url}

    except httpx.HTTPStatusError as e:
        err_msg = (e.response.text or str(e))[:300]
        log.warning("Dodo checkout error: %s %s", e.response.status_code, err_msg)
        raise HTTPException(502, f"Payment provider error: {err_msg}")
    except httpx.RequestError as e:
        log.warning("Dodo request failed: %s", e)
        raise HTTPException(502, "Payment provider unreachable. Try again in a moment.")
    except Exception as e:
        log.exception("Checkout failed: %s", e)
        raise HTTPException(502, f"Checkout failed: {str(e)[:200]}")

def _verify_sig(body: bytes, sig_header: str) -> bool:
    # Optional: run without DODO_WEBHOOK_SECRET; webhook still processes payment.succeeded
    if not DODO_WEBHOOK_SECRET:
        return True
    try:
        expected = hmac.new(DODO_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig_header.split("=")[-1])
    except Exception:
        return False

def _payment_data_id(data: dict) -> str:
    return data.get("id") or data.get("payment_id") or ""

def _payment_data_user_id(data: dict) -> str:
    meta = data.get("metadata") or {}
    if isinstance(meta, dict):
        return meta.get("user_id") or ""
    return ""

@router.post("/webhook")
async def dodo_webhook(request: Request):
    body = await request.body()
    sig  = request.headers.get("webhook-signature") or request.headers.get("dodo-signature") or request.headers.get("x-dodo-signature", "")
    if not _verify_sig(body, sig):
        raise HTTPException(400, "Invalid signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    etype = event.get("type", "")
    data  = event.get("data", {}) or {}

    from database import AsyncSessionLocal
    from models import User, Payment
    from sqlalchemy import select

    if etype == "payment.succeeded":
        now = datetime.utcnow()
        paid_until = now + timedelta(days=365)  # 1 year access
        dodo_payment_id = _payment_data_id(data)
        user_id = _payment_data_user_id(data)

        async with AsyncSessionLocal() as db:
            # Match by dodo_payment_id (session_id we stored) or by pending payment for this user
            if dodo_payment_id:
                res = await db.execute(select(Payment).where(Payment.dodo_payment_id == dodo_payment_id))
                p = res.scalar_one_or_none()
            else:
                p = None
            if not p and user_id:
                res = await db.execute(
                    select(Payment).where(Payment.user_id == user_id, Payment.status == "pending").order_by(Payment.created_at.desc()).limit(1)
                )
                p = res.scalar_one_or_none()
            if p:
                p.status = "paid"
                p.completed_at = now
                if dodo_payment_id and not p.dodo_payment_id:
                    p.dodo_payment_id = dodo_payment_id
                p.raw_webhook = json.dumps(data)[:4000]

            if user_id:
                u = await db.get(User, user_id)
                if u:
                    u.is_paid = True
                    u.paid_at = now
                    u.paid_until = paid_until
                    u.payment_id = dodo_payment_id or (p.dodo_payment_id if p else None)
            await db.commit()

    elif etype in ("payment.failed", "payment.refunded", "payment.cancelled"):
        dodo_payment_id = _payment_data_id(data)
        user_id = _payment_data_user_id(data)
        status_suffix = etype.split(".")[-1]
        async with AsyncSessionLocal() as db:
            if dodo_payment_id:
                res = await db.execute(select(Payment).where(Payment.dodo_payment_id == dodo_payment_id))
                p = res.scalar_one_or_none()
            elif user_id:
                res = await db.execute(
                    select(Payment).where(Payment.user_id == user_id, Payment.status == "pending").order_by(Payment.created_at.desc()).limit(1)
                )
                p = res.scalar_one_or_none()
            else:
                p = None
            if p:
                p.status = status_suffix
                await db.commit()

    return {"received": True}

def _is_active_paid(u):
    """True if user has paid and access not expired (1 year)."""
    if not u:
        return False
    if getattr(u, "paid_until", None) and u.paid_until:
        return u.paid_until > datetime.utcnow()
    return bool(u.is_paid)  # legacy: no paid_until

@router.get("/status")
async def payment_status(request: Request):
    user_jwt = get_current_user(request)
    if not user_jwt:
        return {"is_paid": False}
    from database import AsyncSessionLocal
    from models import User
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_jwt["sub"])
        is_paid = _is_active_paid(u)
        return {"is_paid": is_paid,
                "paid_at": u.paid_at.isoformat() if u and u.paid_at else None,
                "paid_until": u.paid_until.isoformat() if u and getattr(u, "paid_until", None) else None}
