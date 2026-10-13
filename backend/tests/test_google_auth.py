"""Google-Login: Konten anlegen/verknüpfen, Freischaltung, Admin-Adressen, Fehlerfälle (ohne Netzwerk)."""
import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import auth, db, google_auth
from app.main import app
from app.models import User


class FakeGoogle:
    """Ersetzt den Authlib-Client: state im Session-Cookie wie beim echten Ablauf."""

    def __init__(self):
        self.info: dict = {}
        self.redirect_uri = None

    async def authorize_redirect(self, request, redirect_uri, **kw):
        self.redirect_uri = redirect_uri
        request.session["state"] = "s1"
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?state=s1", status_code=302)

    async def authorize_access_token(self, request):
        if request.query_params.get("state") != request.session.get("state"):
            raise ValueError("state")
        return {"userinfo": self.info}


@pytest.fixture
def g(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ADMIN_EMAILS", "Chef@Example.com, zweite@example.com")
    auth._fails.clear()
    fake = FakeGoogle()
    monkeypatch.setattr(google_auth, "_client", lambda: fake)
    with db.session() as s:
        s.execute(delete(User).where(User.email.like("%@example.com")))
    c = TestClient(app, follow_redirects=False)
    c.fake = fake
    return c


def sign_in(c, sub, email, verified=True, name="Test"):
    c.fake.info = {"sub": sub, "email": email, "email_verified": verified, "name": name}
    r = c.get("/api/auth/google/login")
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com/")
    return c.get("/api/auth/google/callback?state=s1&code=x")


def status_of(email):
    with db.session() as s:
        u = s.scalar(select(User).where(User.email == email))
        return u and (u.status, u.role)


def test_config_reports_google(g):
    assert g.get("/api/auth/config").json()["google"] is True


def test_new_account_waits_for_approval(g):
    r = sign_in(g, "100", "neu@example.com")
    assert r.status_code == 303 and r.headers["location"] == "/?login=pending"
    assert auth.COOKIE not in r.headers.get("set-cookie", "")
    assert g.get("/api/objects").status_code == 401
    assert status_of("neu@example.com") == ("pending", "user")
    with db.session() as s:
        s.scalar(select(User).where(User.email == "neu@example.com")).status = "active"
    r = sign_in(g, "100", "neu@example.com")
    assert r.headers["location"] == "/" and auth.COOKIE in r.headers["set-cookie"]
    assert g.get("/api/auth/me").json()["role"] == "user"


def test_admin_email_is_active_admin(g):
    r = sign_in(g, "200", "chef@example.com")
    assert r.headers["location"] == "/"
    assert status_of("chef@example.com") == ("active", "admin")
    me = g.get("/api/auth/me").json()
    assert me["user"] == "chef@example.com" and me["role"] == "admin"


def test_unverified_email_rejected(g):
    r = sign_in(g, "300", "unbestaetigt@example.com", verified=False)
    assert r.headers["location"] == "/?login=error"
    assert status_of("unbestaetigt@example.com") is None


def test_disabled_account_gets_no_session(g):
    sign_in(g, "400", "gesperrt@example.com")
    with db.session() as s:
        s.scalar(select(User).where(User.email == "gesperrt@example.com")).status = "disabled"
    r = sign_in(g, "400", "gesperrt@example.com")
    assert r.headers["location"] == "/?login=disabled" and auth.COOKIE not in r.headers.get("set-cookie", "")


def test_account_recognized_by_sub_not_email(g):
    sign_in(g, "500", "alt@example.com")
    sign_in(g, "500", "neu-adresse@example.com")          # gleiche Google-ID, neue Adresse
    assert status_of("alt@example.com") is None and status_of("neu-adresse@example.com") == ("pending", "user")
    r = sign_in(g, "501", "neu-adresse@example.com")       # andere Google-ID mit fremder Adresse
    assert r.headers["location"] == "/?login=error"


def test_links_existing_local_admin_listed_in_admin_emails(g):
    with db.session() as s:
        s.add(User(email="zweite@example.com", role="admin", status="active"))
    r = sign_in(g, "600", "zweite@example.com")
    assert r.headers["location"] == "/"
    with db.session() as s:
        assert s.scalar(select(User).where(User.email == "zweite@example.com")).google_sub == "600"


def test_cannot_take_over_local_admin(g):
    """Google-Konto mit der Adresse des Notfall-Admins (nicht in ADMIN_EMAILS) darf ihn nicht übernehmen."""
    with db.session() as s:
        s.add(User(email="notfall@example.com", role="admin", status="active"))
    r = sign_in(g, "650", "notfall@example.com")
    assert r.headers["location"] == "/?login=error" and auth.COOKIE not in r.headers.get("set-cookie", "")
    with db.session() as s:
        assert s.scalar(select(User).where(User.email == "notfall@example.com")).google_sub is None


def test_wrong_state_rejected(g):
    g.fake.info = {"sub": "700", "email": "x@example.com", "email_verified": True}
    g.get("/api/auth/google/login")
    r = g.get("/api/auth/google/callback?state=falsch&code=x")
    assert r.headers["location"] == "/?login=error" and status_of("x@example.com") is None


def test_real_client_rejects_missing_state(monkeypatch):
    """Echter Authlib-Client: ohne passenden state im Cookie kein Token-Abruf (kein Netzwerk nötig)."""
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(google_auth, "_oauth", None)
    auth._fails.clear()
    c = TestClient(app, follow_redirects=False)
    r = c.get("/api/auth/google/callback?state=abc&code=x")
    assert r.status_code == 303 and r.headers["location"] == "/?login=error"


def test_pending_limit(g, monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_PENDING", 0)
    r = sign_in(g, "800", "zuviel@example.com")
    assert r.headers["location"] == "/?login=full"
    assert sign_in(g, "801", "zweite@example.com").headers["location"] == "/"     # Admins kommen trotzdem rein


def test_redirect_uri_from_public_base_url(g, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://buntu-1.example.ts.net/")
    g.get("/api/auth/google/login")
    assert g.fake.redirect_uri == "https://buntu-1.example.ts.net/api/auth/google/callback"


def test_google_off_without_config(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    c = TestClient(app, follow_redirects=False)
    assert c.get("/api/auth/google/login").status_code == 404
    assert c.get("/api/auth/config").json()["google"] is False
