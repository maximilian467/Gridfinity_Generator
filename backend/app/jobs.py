"""Job-Verwaltung: CAD-Builds und Stapel-Scans laufen in einem Prozesspool, Status per Polling.

Ein Worker kann mit report() Zwischenstände schreiben (progress, items je Werkzeug); get() liest sie."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from .auth import Principal

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


def submit(kind: str, fn, out_dir: Path, *args, owner: Principal) -> str:
    """fn(out_dir_str, *args) -> dict(outputs, checks). Gibt die job_id zurück."""
    if busy():
        raise Busy("Es laufen bereits mehrere Berechnungen. Bitte kurz warten.")
    if not owner.is_admin and running_for(owner.id) >= MAX_PER_USER:
        raise Busy("Deine vorige Berechnung läuft noch. Bitte warten, bis sie fertig ist.")
    job_id = uuid.uuid4().hex[:10]
    out_dir = out_dir / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    job = {"id": job_id, "kind": kind, "status": "running", "progress": 0.05, "outputs": {},
           "checks": {}, "warnings": [], "items": None, "error": None, "started": time.time(), "dir": str(out_dir),
           "owner_id": owner.id}
    # sofort schreiben: der Besitz der Ausgabedateien steht damit von Anfang an fest
    _job_file(out_dir).write_text(json.dumps(job, default=str), encoding="utf-8")
    with _lock:
        _jobs[job_id] = job
    fut: Future = _get_pool().submit(fn, str(out_dir), *args)

    def done(f: Future) -> None:
        try:
            res = f.result()
            job.update(status="done", progress=1.0, outputs=res["outputs"], checks=res.get("checks", {}),
                       warnings=res.get("warnings", []), items=res.get("items", job.get("items")))
        except Exception as e:  # noqa: BLE001
            job.update(status="error", error=f"{type(e).__name__}: {e}")
        _job_file(out_dir).write_text(json.dumps(job, default=str), encoding="utf-8")

    fut.add_done_callback(done)
    return job_id


MAX_RUNNING = 4
MAX_PER_USER = 1         # laufende Berechnungen je Nutzer (Admins ausgenommen)


class Busy(RuntimeError):
    pass


def busy() -> bool:
    with _lock:
        return sum(1 for j in _jobs.values() if j["status"] == "running") >= MAX_RUNNING


def running_for(user_id: int) -> int:
    with _lock:
        return sum(1 for j in _jobs.values() if j["status"] == "running" and j.get("owner_id") == user_id)


def get(job_id: str) -> dict | None:
    if not job_id.isalnum() or len(job_id) > 40:      # wird in einem Glob-Muster verwendet
        return None
    with _lock:
        job = _jobs.get(job_id)
    if job is not None:
        if job["status"] == "running":
            info = _read_progress(Path(job["dir"]))
            if info is not None:                       # Zwischenstand des Workers
                job["progress"] = min(0.95, float(info.get("progress", job["progress"])))
                job["items"] = info.get("items", job.get("items"))
            else:                                      # weicher Fortschritt für die Anzeige
                job["progress"] = min(0.9, 0.05 + (time.time() - job["started"]) / 60.0)
        return job
    for f in config.DATA_DIR.glob(f"**/{job_id}/job.json"):
        job = json.loads(f.read_text(encoding="utf-8"))
        if job.get("status") == "running":           # nicht mehr im Speicher: Server wurde neu gestartet
            job.update(status="error", error="Abgebrochen (Server-Neustart). Bitte erneut starten.")
        return job
    return None


def report(out_dir: str | Path, **info) -> None:
    """Vom Worker aus: Zwischenstand für die Anzeige (z. B. progress=0.4, items=[...])."""
    f = Path(out_dir) / "progress.json"
    tmp = f.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(info, default=str), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:          # Windows: der Leser hält die Datei gerade offen, der nächste Bericht kommt gleich
        pass


def _read_progress(out_dir: Path) -> dict | None:
    try:
        return json.loads((out_dir / "progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
