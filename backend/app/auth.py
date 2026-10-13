"""Anmeldung: Nutzer und Sitzungen in der Datenbank, Cookie mit zufälligem Sitzungs-Token.

- Google-Login (OIDC) in google_auth.py; neue Konten warten auf Freischaltung durch einen Admin.
- Notfall-Admin: APP_USER / APP_PASSWORD (POST /api/auth/login). In Produktion nur aktiv, wenn
  das Passwort mindestens 16 Zeichen hat; LOCAL_LOGIN=0 schaltet ihn ganz ab.
- In der DB steht nur der SHA-256 des Tokens; Abmelden/Sperren widerruft Sitzungen sofort.
- SECRET_KEY (sonst zufällig in data/.secret) signiert nur das kurzlebige OAuth-Cookie.
- COOKIE_SECURE=1 hinter HTTPS. AUTH_DISABLED=1 schaltet den Login ab (Tests/Entwicklung):
  dann ist jede Anfrage ein lokaler Admin.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from starlette.concurrency import run_in_threadpool

from . import config, db
from .models import AuditLog, Session, User, utcnow

COOKIE = "gf_sid"
MAX_AGE = 30 * 24 * 3600
REFRESH_AFTER = 3600            # gleitende Verlängerung höchstens einmal pro Stunde (spart Schreibzugriffe)
PUBLIC = ("/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/auth/config",
          "/api/auth/google/")
DEV_ADMIN = "admin@local"

router = APIRouter(prefix="/auth", tags=["auth"])


def enabled() -> bool:
    # in Produktion nie abschaltbar (Schutz gegen ein versehentliches AUTH_DISABLED in der .env)
    return not dev_mode() or os.environ.get("AUTH_DISABLED", "") not in ("1", "true", "yes")


def dev_mode() -> bool:
    return os.environ.get("APP_ENV", "dev") == "dev"


def _user() -> str:
    return os.environ.get("APP_USER", "admin@admin.com").strip().lower()


def _password() -> str:
    return os.environ.get("APP_PASSWORD", "admin")


def local_login_enabled() -> bool:
    if os.environ.get("LOCAL_LOGIN", "1").lower() in ("0", "false", "no"):
        return False
    return dev_mode() or len(_password()) >= 16


def source_url() -> str:
    """Link zum Quellcode (AGPL-3.0: Nutzer des Dienstes müssen an den Quellcode kommen)."""
    return os.environ.get("SOURCE_URL", "https://github.com/maximilian467/Gridfinity_Generator")


def secure_cookies() -> bool:
    return os.environ.get("COOKIE_SECURE", "") in ("1", "true")


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
            f.chmod(0o600)                           # nur für den Besitzer lesbar (auch bei älteren Dateien)
            _secret = f.read_text(encoding="ascii").strip().encode()
    return _secret


# ---- Nutzer ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Principal:
    """Angemeldeter Nutzer (unabhängig von der DB-Sitzung weiterreichbar)."""
    id: int
    email: str
    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @classmethod
    def of(cls, u: User) -> Principal:
        return cls(u.id, u.email, u.name, u.role)


def audit(action: str, target: str = "", actor: int | None = None, ip: str = "") -> None:
    with db.session() as s:
        s.add(AuditLog(action=action, target=target[:200], actor_id=actor, ip=ip[:64]))


def _dev_admin() -> Principal:
    with db.session() as s:
        u = s.scalar(select(User).where(User.email == DEV_ADMIN))
        if u is None:
            u = User(email=DEV_ADMIN, name="Admin (lokal)", role="admin", status="active")
            s.add(u)
            s.flush()
        return Principal.of(u)


def current_user(request: Request) -> Principal:
    if not enabled():
        return _dev_admin()
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "Nicht angemeldet")
    return user


def require_admin(user: Principal = Depends(current_user)) -> Principal:
    if not user.is_admin:
        raise HTTPException(403, "Nur für Admins")
    return user


# ---- Sitzungen ---------------------------------------------------------------------------
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    with db.session() as s:
        s.execute(delete(Session).where(Session.expires_at < now))           # Aufräumen nebenbei
        s.add(Session(token_hash=_hash(token), user_id=user_id, created_at=now, last_seen_at=now,
                      expires_at=now + timedelta(seconds=MAX_AGE), ip=client_ip(request),
                      user_agent=request.headers.get("user-agent", "")[:300]))
        u = s.get(User, user_id)
        if u is not None:
            u.last_login_at = now
    return token


def user_for_token(token: str | None) -> tuple[Principal | None, bool]:
    """(Nutzer, verlängert). Nur aktive Konten mit gültiger Sitzung zählen."""
    if not token or len(token) > 200:
        return None, False
    now = utcnow()
    with db.session() as s:
        sess = s.get(Session, _hash(token))
        if sess is None or sess.expires_at < now:
            return None, False
        u = s.get(User, sess.user_id)
        if u is None or u.status != "active":
            return None, False
        refreshed = (now - sess.last_seen_at).total_seconds() > REFRESH_AFTER
        if refreshed:
            sess.last_seen_at = now
            sess.expires_at = now + timedelta(seconds=MAX_AGE)
        return Principal.of(u), refreshed


def revoke(token: str | None) -> None:
    if token:
        with db.session() as s:
            s.execute(delete(Session).where(Session.token_hash == _hash(token)))


def revoke_all(user_id: int) -> None:
    with db.session() as s:
        s.execute(delete(Session).where(Session.user_id == user_id))


def set_cookie(response: Response, token: str) -> None:
    # Lax statt Strict: der Rücksprung von Google ist eine seitenübergreifende Navigation.
    # Gegen CSRF prüft die Middleware zusätzlich den Origin-Header (origin_ok).
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=secure_cookies(), path="/")


def origin_ok(request: Request) -> bool:
    """Ändernde Anfragen nur von der eigenen Seite. Browser senden Origin bei POST/PUT/DELETE immer;
    fehlt er, kommt die Anfrage nicht aus einem Browser (kein CSRF möglich)."""
    origin = request.headers.get("origin")
    if origin is None:
        return True
    netloc = urlsplit(origin).netloc.lower()
    if not netloc:
        return False                       # z. B. "null" aus Sandbox-Frames
    allowed = {request.headers.get("host", "").lower()}
    base = os.environ.get("PUBLIC_BASE_URL", "")
    if base:
        allowed.add(urlsplit(base).netloc.lower())
    if dev_mode():
        allowed |= {"localhost:5173", "127.0.0.1:5173", "localhost:5183"}
    return netloc in allowed


# ---- Schutz gegen Durchprobieren: max. 10 Fehlversuche je IP in 10 Minuten ----
_fails: dict[str, list[float]] = {}
_lock = threading.Lock()
WINDOW, LIMIT = 600.0, 10


def _too_many(ip: str) -> bool:
    now = time.time()
    with _lock:
        if len(_fails) > 5000:                      # Speicher begrenzen: abgelaufene Einträge entfernen
            for k in [k for k, v in _fails.items() if not v or now - v[-1] >= WINDOW]:
                del _fails[k]
        lst = [t for t in _fails.get(ip, []) if now - t < WINDOW]
        if lst:
            _fails[ip] = lst
        else:
            _fails.pop(ip, None)
        return len(lst) >= LIMIT


def _fail(ip: str) -> None:
    with _lock:
        _fails.setdefault(ip, []).append(time.time())


def client_ip(request: Request) -> str:
    """IP des Besuchers. X-Forwarded-For nur hinter dem eigenen Proxy (TRUST_PROXY=1) und dann nur den
    letzten Eintrag: den hängt der Proxy (Tailscale) selbst an, alles davor kann der Besucher fälschen."""
    if os.environ.get("TRUST_PROXY", "") in ("1", "true"):
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd.strip():
            return fwd.split(",")[-1].strip()[:64]
    return (request.client.host if request.client else "?")[:64]


# ---- Routen ------------------------------------------------------------------------------
class LoginBody(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@router.get("/config")
def auth_config() -> dict:
    from . import google_auth
    return {"auth": enabled(), "google": google_auth.configured(), "local": local_login_enabled(),
            "source": source_url()}


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response) -> dict:
    """Notfall-Admin aus APP_USER / APP_PASSWORD."""
    if not local_login_enabled():
        raise HTTPException(403, "Die Anmeldung mit Passwort ist abgeschaltet")
    ip = client_ip(request)
    if _too_many(ip):
        raise HTTPException(429, "Zu viele Fehlversuche. Bitte in ein paar Minuten erneut versuchen.")
    ok_user = hmac.compare_digest(body.email.strip().lower().encode(), _user().encode())
    ok_pw = hmac.compare_digest(body.password.encode(), _password().encode())
    if not (ok_user and ok_pw):
        _fail(ip)
        await asyncio.sleep(0.5)        # bremst, ohne einen Arbeits-Thread zu blockieren
        raise HTTPException(401, "E-Mail oder Passwort falsch")
    uid = await run_in_threadpool(_local_admin_id)
    set_cookie(response, await run_in_threadpool(create_session, uid, request))
    await run_in_threadpool(audit, "login_local", _user(), uid, ip)
    return {"user": _user()}


def _local_admin_id() -> int:
    with db.session() as s:
        u = s.scalar(select(User).where(User.email == _user()))
        if u is None:
            u = User(email=_user(), name="Admin", role="admin", status="active", approved_at=utcnow())
            s.add(u)
            s.flush()
        if u.status == "disabled":
            raise HTTPException(403, "Dieses Konto ist gesperrt")
        u.role, u.status = "admin", "active"
        return u.id


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    revoke(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, user: Principal = Depends(current_user)) -> dict:
    revoke_all(user.id)
    response.delete_cookie(COOKIE, path="/")
    audit("logout_all", user.email, user.id, client_ip(request))
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    if not enabled():
        u = _dev_admin()
        return {"user": u.email, "id": u.id, "name": u.name, "role": u.role, "auth": False}
    u = getattr(request.state, "user", None)
    if u is None:
        raise HTTPException(401, "Nicht angemeldet")
    return {"user": u.email, "id": u.id, "name": u.name, "role": u.role, "auth": True}
