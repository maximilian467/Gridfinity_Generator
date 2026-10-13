"""Google-Login (OpenID Connect über Authlib).

GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET aus der Google Cloud Console. Redirect-URI ist
PUBLIC_BASE_URL + /api/auth/google/callback (ohne PUBLIC_BASE_URL: aus der Anfrage, nur für Dev).
state, nonce und PKCE-Verifier liegen solange in einem signierten Cookie (gf_oauth, 10 Minuten).

Neue Konten warten auf Freischaltung (status 'pending'); Adressen aus ADMIN_EMAILS werden sofort
aktive Admins. Erkannt wird ein Konto an Googles 'sub', nicht an der E-Mail.
"""
from __future__ import annotations

import os
from datetime import timedelta

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from starlette.concurrency import run_in_threadpool

from . import auth, db
from .models import AuditLog, User, utcnow

META_URL = "https://accounts.google.com/.well-known/openid-configuration"
STATE_COOKIE = "gf_oauth"
MAX_PENDING = 50                 # mehr wartende Konten nimmt die App nicht an (Schutz vor Spam)
PENDING_DAYS = 30                # nicht freigeschaltete Konten verfallen danach

router = APIRouter(prefix="/auth/google", tags=["auth"])

_oauth: OAuth | None = None


def configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def _client():
    global _oauth
    if _oauth is None:
        _oauth = OAuth()
        _oauth.register("google", client_id=os.environ["GOOGLE_CLIENT_ID"],
                        client_secret=os.environ["GOOGLE_CLIENT_SECRET"], server_metadata_url=META_URL,
                        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"})
    return _oauth.google


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def _redirect_uri(request: Request) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/api/auth/google/callback" if base else str(request.url_for("google_callback"))


def _back(status: str) -> RedirectResponse:
    return RedirectResponse(f"/?login={status}", status_code=303)


def upsert_user(info: dict, ip: str = "") -> tuple[str, int | None]:
    """Konto zu den Google-Angaben finden oder anlegen. -> (Ergebnis, user_id bei 'active')."""
    sub = str(info.get("sub") or "")
    email = str(info.get("email") or "").strip().lower()
    if not sub or not email or info.get("email_verified") is not True or len(email) > 200 or len(sub) > 100:
        return "error", None
    name = str(info.get("name") or "")[:200]
    is_admin = email in admin_emails()
    now = utcnow()
    with db.session() as s:
        s.execute(delete(User).where(User.status == "pending",
                                     User.created_at < now - timedelta(days=PENDING_DAYS)))
        u = s.scalar(select(User).where(User.google_sub == sub))
        if u is None:
            u = s.scalar(select(User).where(User.email == email))
            if u is not None and u.google_sub not in (None, sub):
                return "error", None                     # Adresse gehört schon zu einem anderen Google-Konto
            if u is not None:
                u.google_sub = sub                       # vorhandenes Konto (z. B. Notfall-Admin) verknüpfen
        if u is None:
            if not is_admin:
                pending = s.scalar(select(func.count()).select_from(User).where(User.status == "pending"))
                if pending >= MAX_PENDING:
                    return "full", None
            u = User(email=email, name=name, google_sub=sub, role="admin" if is_admin else "user",
                     status="active" if is_admin else "pending", created_at=now,
                     approved_at=now if is_admin else None)
            s.add(u)
            s.flush()
            action = "signup_admin" if is_admin else "signup_pending"
            s.add(AuditLog(action=action, target=email, actor_id=u.id, ip=ip))
        else:
            if u.email != email and s.scalar(select(User.id).where(User.email == email)) is None:
                u.email = email                          # Google-Adresse geändert
            u.name = name or u.name
            if is_admin:
                u.role, u.status = "admin", "active"
                u.approved_at = u.approved_at or now
        return u.status, (u.id if u.status == "active" else None)


@router.get("/login")
async def google_login(request: Request):
    if not configured():
        raise HTTPException(404, "Google-Login ist nicht eingerichtet")
    if auth._too_many(auth.client_ip(request)):
        return _back("error")
    return await _client().authorize_redirect(request, _redirect_uri(request), prompt="select_account")


@router.get("/callback", name="google_callback")
async def google_callback(request: Request):
    if not configured():
        raise HTTPException(404, "Google-Login ist nicht eingerichtet")
    ip = auth.client_ip(request)
    if auth._too_many(ip):
        return _back("error")
    try:
        token = await _client().authorize_access_token(request)
    except Exception:  # noqa: BLE001  # falscher state/nonce, abgebrochen, ungültiges Token, Google nicht erreichbar
        auth._fail(ip)
        return _back("error")
    finally:
        request.session.clear()
    status, uid = await run_in_threadpool(upsert_user, token.get("userinfo") or {}, ip)
    if status != "active" or uid is None:
        if status == "error":
            auth._fail(ip)
        return _back(status)
    resp = _back("ok")
    resp.headers["location"] = "/"
    auth.set_cookie(resp, await run_in_threadpool(auth.create_session, uid, request))
    await run_in_threadpool(auth.audit, "login_google", "", uid, ip)
    return resp
