"""Job-Verwaltung: CAD-Builds laufen in einem Prozesspool, Status per Polling."""
from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path

from . import config

_pool: ProcessPoolExecutor | None = None
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=2)
    return _pool


def _job_file(out_dir: Path) -> Path:
    return out_dir / "job.json"


def submit(kind: str, fn, out_dir: Path, *args) -> str:
    """fn(out_dir_str, *args) -> dict(outputs, checks). Gibt die job_id zurück."""
    job_id = uuid.uuid4().hex[:10]
    out_dir = out_dir / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    job = {"id": job_id, "kind": kind, "status": "running", "progress": 0.05, "outputs": {},
           "checks": {}, "warnings": [], "error": None, "started": time.time(), "dir": str(out_dir)}
    with _lock:
        _jobs[job_id] = job
    fut: Future = _get_pool().submit(fn, str(out_dir), *args)

    def done(f: Future) -> None:
        try:
            res = f.result()
            job.update(status="done", progress=1.0, outputs=res["outputs"], checks=res.get("checks", {}),
                       warnings=res.get("warnings", []))
        except Exception as e:  # noqa: BLE001
            job.update(status="error", error=f"{type(e).__name__}: {e}")
        _job_file(out_dir).write_text(json.dumps(job, default=str), encoding="utf-8")

    fut.add_done_callback(done)
    return job_id


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
    if job is not None:
        if job["status"] == "running":                 # weicher Fortschritt für die Anzeige
            job["progress"] = min(0.9, 0.05 + (time.time() - job["started"]) / 60.0)
        return job
    for f in config.DATA_DIR.glob(f"**/{job_id}/job.json"):
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
