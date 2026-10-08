"""Einfacher Login: eine Kennung aus Umgebungsvariablen, signiertes Session-Cookie.

APP_USER / APP_PASSWORD (Default admin@admin.com / admin), SECRET_KEY (sonst zufällig und in
data/.secret abgelegt), COOKIE_SECURE=1 hinter HTTPS. AUTH_DISABLED=1 schaltet den Login ab
(nur für Tests/Entwicklung).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import config

COOKIE = "gf_session"
MAX_AGE = 30 * 24 * 3600
PUBLIC = ("/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me")

router = APIRouter(prefix="/auth", tags=["auth"])


def enabled() -> bool:
    return os.environ.get("AUTH_DISABLED", "") not in ("1", "true", "yes")


def _user() -> str:
    return os.environ.get("APP_USER", "admin@admin.com").strip().lower()


def _password() -> str:
    return os.environ.get("APP_PASSWORD", "admin")


_secret: bytes | None = None


def _key() -> bytes:
    global _secret
    if _secret is None:
        env = os.environ.get("SECRET_KEY")
        if env:
            _secret = env.encode()
        else:
            f = config.DATA_DIR / ".secret"
            f.parent.mkdir(parents=True, exist_ok=True)
            if not f.exists():
                f.write_text(secrets.token_hex(32), encoding="ascii")
            _secret = f.read_text(encoding="ascii").strip().encode()
    return _secret


def make_token(user: str, now: float | None = None) -> str:
    exp = int((time.time() if now is None else now) + MAX_AGE)
    payload = base64.urlsafe_b64encode(f"{user}|{exp}".encode()).decode().rstrip("=")
    sig = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def check_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    good = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    try:
        user, exp = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode().split("|")
        if int(exp) < time.time() or user != _user():
            return None
    except Exception:  # noqa: BLE001
        return None
    return user


# ---- Schutz gegen Durchprobieren: max. 10 Fehlversuche je IP in 10 Minuten ----
_fails: dict[str, list[float]] = {}
_lock = threading.Lock()
WINDOW, LIMIT = 600.0, 10


def _too_many(ip: str) -> bool:
    now = time.time()
    with _lock:
        lst = [t for t in _fails.get(ip, []) if now - t < WINDOW]
        _fails[ip] = lst
        return len(lst) >= LIMIT


def _fail(ip: str) -> None:
    with _lock:
        _fails.setdefault(ip, []).append(time.time())


def client_ip(request: Request) -> str:
    # Header nur hinter einem eigenen Proxy/Tunnel auswerten (TRUST_PROXY=1), sonst fälschbar
    if os.environ.get("TRUST_PROXY", "") in ("1", "true"):
        fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
        if fwd.strip():
            return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "?")[:64]


class LoginBody(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    if _too_many(ip):
        raise HTTPException(429, "Zu viele Fehlversuche. Bitte in ein paar Minuten erneut versuchen.")
    ok_user = hmac.compare_digest(body.email.strip().lower().encode(), _user().encode())
    ok_pw = hmac.compare_digest(body.password.encode(), _password().encode())
    if not (ok_user and ok_pw):
        _fail(ip)
        time.sleep(0.5)
        raise HTTPException(401, "E-Mail oder Passwort falsch")
    response.set_cookie(COOKIE, make_token(_user()), max_age=MAX_AGE, httponly=True, samesite="strict",
                        secure=os.environ.get("COOKIE_SECURE", "") in ("1", "true"), path="/")
    return {"user": _user()}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    if not enabled():
        return {"user": _user(), "auth": False}
    user = check_token(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Nicht angemeldet")
    return {"user": user, "auth": True}
