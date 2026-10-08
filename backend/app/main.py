import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth
from .api import baseplates as baseplates_api
from .api import inserts as inserts_api
from .api import jobs as jobs_api
from .api import objects as objects_api
from .config import DATA_DIR, FRONTEND_DIST

DEV = os.environ.get("APP_ENV", "dev") == "dev"

# Nur diese Bereiche und Dateitypen aus data/ ausliefern (kein .secret, kein Modell, keine JSONs)
FILE_DIRS = {"objects", "inserts", "baseplates"}
FILE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".glb", ".3mf", ".stl", ".step", ".zip", ".svg"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self' blob: data:; font-src 'self' data:; worker-src 'self' blob:; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


@asynccontextmanager
async def lifespan(_app):
    yield
    from . import jobs
    jobs.shutdown()          # Prozesspool nicht blockierend beenden (sonst hängt --reload)


app = FastAPI(title="Gridfinity-Einlagen-Generator", lifespan=lifespan,
              docs_url="/api/docs" if DEV else None, redoc_url=None,
              openapi_url="/api/openapi.json" if DEV else None)
if DEV:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5183"],
        allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
    )


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if (auth.enabled() and path.startswith("/api/") and not path.startswith(auth.PUBLIC)
            and not auth.check_token(request.cookies.get(auth.COOKIE))):
        resp = JSONResponse({"detail": "Nicht angemeldet"}, status_code=401)
    else:
        resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    if not path.startswith("/api/"):
        resp.headers.setdefault("Content-Security-Policy", CSP)
    if request.headers.get("x-forwarded-proto") == "https" or os.environ.get("COOKIE_SECURE") == "1":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


@app.exception_handler(KeyError)
async def not_found(_request: Request, _exc: KeyError):
    # ungültige oder unbekannte IDs (u. a. storage.InvalidId)
    return JSONResponse({"detail": "Nicht gefunden"}, status_code=404)


@app.exception_handler(RuntimeError)
async def runtime_error(_request: Request, exc: RuntimeError):
    from .jobs import Busy
    if isinstance(exc, Busy):
        return JSONResponse({"detail": str(exc)}, status_code=429)
    return JSONResponse({"detail": "Interner Fehler"}, status_code=500)


api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/files/{path:path}")
def files(path: str) -> FileResponse:
    root = DATA_DIR.resolve()
    f = (root / path).resolve()
    parts = f.relative_to(root).parts if root in f.parents else ()
    if (not parts or parts[0] not in FILE_DIRS or any(p.startswith(".") for p in parts)
            or f.suffix.lower() not in FILE_TYPES or not f.is_file()):
        raise HTTPException(404, "Datei nicht gefunden")
    # sandbox: falls je aktive Inhalte (SVG) dabei sind, laufen sie nicht im Kontext der App
    return FileResponse(f, headers={"Cache-Control": "no-cache", "Content-Security-Policy": "sandbox"})


api.include_router(auth.router)
api.include_router(objects_api.router)
api.include_router(inserts_api.router)
api.include_router(jobs_api.router)
api.include_router(baseplates_api.router)
app.include_router(api)


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        root = FRONTEND_DIST.resolve()
        f = (root / path).resolve()
        ok = path and root in f.parents and f.is_file()
        return FileResponse(f if ok else root / "index.html")
