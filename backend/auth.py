"""
Google OAuth2 — raw API, no Firebase.

GET  /auth/google          -> redirect to Google
GET  /auth/google/callback -> exchange code, upsert User, set JWT cookie
GET  /auth/me              -> current user from cookie
POST /auth/logout          -> clear cookie
"""
import os, uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
JWT_SECRET           = os.getenv("JWT_SECRET", "dev_secret_CHANGE_IN_PRODUCTION")
JWT_EXPIRE_HOURS     = int(os.getenv("JWT_EXPIRE_HOURS", "720"))

def create_jwt(user_id, email, is_paid, is_admin):
    return pyjwt.encode({
        "sub": user_id, "email": email,
        "is_paid": is_paid, "is_admin": is_admin,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }, JWT_SECRET, algorithm="HS256")

def decode_jwt(token: str) -> Optional[dict]:
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None

def get_current_user(request: Request) -> Optional[dict]:
    token = (request.cookies.get("jn_token") or
             request.headers.get("Authorization", "").replace("Bearer ", ""))
    return decode_jwt(token) if token else None

def require_auth(request: Request) -> dict:
    u = get_current_user(request)
    if not u:
        raise HTTPException(401, "Sign in required")
    return u

def require_admin(request: Request) -> dict:
    u = require_auth(request)
    if not u.get("is_admin"):
        raise HTTPException(403, "Admin only")
    return u

@router.get("/google")
async def google_login():
    params = {
        "client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code", "scope": "openid email profile",
        "access_type": "offline", "prompt": "select_account",
    }
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")

@router.get("/google/callback")
async def google_callback(code: str):
    from database import AsyncSessionLocal
    from models import User
    from sqlalchemy import select

    async with httpx.AsyncClient() as client:
        tok = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
        }, timeout=15)
        tokens = tok.json()
        if "error" in tokens:
            raise HTTPException(400, tokens.get("error_description", tokens["error"]))

        prof = await client.get("https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=15)
        g = prof.json()

    admin_email = os.getenv("ADMIN_EMAIL", "")
    async with AsyncSessionLocal() as db:
        res  = await db.execute(select(User).where(User.google_id == g["sub"]))
        user = res.scalar_one_or_none()
        if not user:
            res2 = await db.execute(select(User).where(User.email == g.get("email","")))
            user = res2.scalar_one_or_none()
        if not user:
            user = User(id=str(uuid.uuid4()), email=g.get("email",""),
                        name=g.get("name",""), avatar_url=g.get("picture",""),
                        google_id=g["sub"],
                        is_admin=bool(admin_email and g.get("email","").lower()==admin_email.lower()))
            db.add(user)
        else:
            user.google_id = g["sub"]
            user.name = g.get("name", user.name)
            user.avatar_url = g.get("picture", user.avatar_url)
            user.last_seen = datetime.utcnow()
            if admin_email and g.get("email","").lower() == admin_email.lower():
                user.is_admin = True
        await db.commit()
        await db.refresh(user)
        token = create_jwt(user.id, user.email, user.is_paid, user.is_admin)

    resp = RedirectResponse(url="/?auth=success")
    resp.set_cookie("jn_token", token, max_age=JWT_EXPIRE_HOURS*3600,
                    httponly=True, samesite="lax", secure=False)
    return resp

@router.get("/me")
async def get_me(request: Request):
    u = get_current_user(request)
    if not u:
        return {"authenticated": False}
    from database import AsyncSessionLocal
    from models import User
    async with AsyncSessionLocal() as db:
        user = await db.get(User, u["sub"])
        if not user:
            return {"authenticated": False}
        user.last_seen = datetime.utcnow()
        await db.commit()
        return {
            "authenticated": True, "id": user.id,
            "email": user.email, "name": user.name,
            "avatar_url": user.avatar_url, "is_paid": user.is_paid,
            "is_admin": user.is_admin, "has_resume": bool(user.resume_text),
            "resume_skills": user.skills_list(), "resume_title": user.resume_title or "",
            "paid_at": user.paid_at.isoformat() if user.paid_at else None,
        }


@router.get("/token")
async def get_token(request: Request):
    """
    Helper for browser extensions:
    - If the user is already logged in via Google (jn_token cookie),
      return a fresh JWT the extension can store and send as
      `Authorization: Bearer <token>` on API calls.
    """
    u = get_current_user(request)
    if not u:
        raise HTTPException(401, "Sign in with Google first")
    from database import AsyncSessionLocal
    from models import User
    async with AsyncSessionLocal() as db:
        user = await db.get(User, u["sub"])
        if not user:
            raise HTTPException(401, "User not found")
        # Issue a new token in case roles/payment changed
        token = create_jwt(user.id, user.email, user.is_paid, user.is_admin)
        return {"token": token, "is_paid": user.is_paid, "is_admin": user.is_admin}

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("jn_token")
    return {"ok": True}
