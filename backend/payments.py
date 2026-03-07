"""
DodoPayments — $2.99 one-time lifetime access.

POST /payments/checkout  -> { checkout_url }
GET  /payments/status    -> { is_paid }
POST /payments/webhook   -> DodoPayments calls this when paid
"""
import hashlib, hmac, json, os, uuid
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
import httpx
from auth import get_current_user

router = APIRouter(prefix="/payments", tags=["payments"])

DODO_API_KEY        = os.getenv("DODO_API_KEY", "")
DODO_WEBHOOK_SECRET = os.getenv("DODO_WEBHOOK_SECRET", "")
DODO_PRODUCT_ID     = os.getenv("DODO_PRODUCT_ID", "")
DODO_PRICE_CENTS    = int(os.getenv("DODO_PRICE_CENTS", "299"))
APP_URL             = os.getenv("APP_URL", "http://localhost:8000")

@router.post("/checkout")
async def create_checkout(request: Request):
    user_jwt = get_current_user(request)
    if not user_jwt:
        raise HTTPException(401, "Sign in with Google first")

    from database import AsyncSessionLocal
    from models import User, Payment

    async with AsyncSessionLocal() as db:
        db_user = await db.get(User, user_jwt["sub"])
        if db_user and db_user.is_paid:
            return {"already_paid": True}

    if not DODO_API_KEY:
        raise HTTPException(503, "DODO_API_KEY not configured in .env")

    payment_uuid = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.dodopayments.com/v1/checkout/sessions",
                json={
                    "product_id": DODO_PRODUCT_ID, "quantity": 1,
                    "customer": {"email": user_jwt["email"]},
                    "success_url": f"{APP_URL}/?payment=success",
                    "cancel_url":  f"{APP_URL}/?payment=cancelled",
                    "metadata": {"user_id": user_jwt["sub"], "payment_id": payment_uuid},
                },
                headers={"Authorization": f"Bearer {DODO_API_KEY}"},
                timeout=20,
            )
            r.raise_for_status()
            dodo = r.json()

        async with AsyncSessionLocal() as db:
            db.add(Payment(
                id=payment_uuid, user_id=user_jwt["sub"],
                dodo_payment_id=dodo.get("id", payment_uuid),
                amount_cents=DODO_PRICE_CENTS, status="pending",
                product_id=DODO_PRODUCT_ID,
            ))
            await db.commit()

        return {"checkout_url": dodo.get("url") or dodo.get("checkout_url", "")}

    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"DodoPayments error: {e.response.text}")

def _verify_sig(body: bytes, sig_header: str) -> bool:
    # Optional: run without DODO_WEBHOOK_SECRET; webhook still processes payment.succeeded
    if not DODO_WEBHOOK_SECRET:
        return True
    try:
        expected = hmac.new(DODO_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig_header.split("=")[-1])
    except Exception:
        return False

@router.post("/webhook")
async def dodo_webhook(request: Request):
    body = await request.body()
    sig  = request.headers.get("webhook-signature") or request.headers.get("dodo-signature","")
    if not _verify_sig(body, sig):
        raise HTTPException(400, "Invalid signature")

    event = json.loads(body)
    etype = event.get("type","")
    data  = event.get("data",{})

    from database import AsyncSessionLocal
    from models import User, Payment
    from sqlalchemy import select

    if etype == "payment.succeeded":
        dodo_id = data.get("id","")
        user_id = data.get("metadata",{}).get("user_id","")
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Payment).where(Payment.dodo_payment_id == dodo_id))
            p   = res.scalar_one_or_none()
            if p:
                p.status = "paid"
                p.completed_at = datetime.utcnow()
                p.raw_webhook  = json.dumps(data)
            if user_id:
                u = await db.get(User, user_id)
                if u:
                    u.is_paid    = True
                    u.paid_at    = datetime.utcnow()
                    u.payment_id = dodo_id
            await db.commit()

    elif etype in ("payment.failed", "payment.refunded"):
        dodo_id = data.get("id","")
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Payment).where(Payment.dodo_payment_id == dodo_id))
            p   = res.scalar_one_or_none()
            if p:
                p.status = etype.split(".")[1]
                await db.commit()

    return {"received": True}

@router.get("/status")
async def payment_status(request: Request):
    user_jwt = get_current_user(request)
    if not user_jwt:
        return {"is_paid": False}
    from database import AsyncSessionLocal
    from models import User
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_jwt["sub"])
        return {"is_paid": u.is_paid if u else False,
                "paid_at": u.paid_at.isoformat() if u and u.paid_at else None}
