from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import inserts as inserts_api
from .api import jobs as jobs_api
from .api import objects as objects_api
from .config import DATA_DIR, FRONTEND_DIST

app = FastAPI(title="Gridfinity-Einlagen-Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/files/{path:path}")
def files(path: str) -> FileResponse:
    root = DATA_DIR.resolve()
    f = (root / path).resolve()
    if root not in f.parents or not f.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


api.include_router(objects_api.router)
api.include_router(inserts_api.router)
api.include_router(jobs_api.router)
app.include_router(api)


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        root = FRONTEND_DIST.resolve()
        f = (root / path).resolve()
        ok = path and root in f.parents and f.is_file()
        return FileResponse(f if ok else root / "index.html")
