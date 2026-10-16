from fastapi import APIRouter, Depends, HTTPException

from .. import jobs, storage
from ..auth import Principal, current_user

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get(job_id: str, user: Principal = Depends(current_user)) -> dict:
    job = jobs.get(job_id)
    if job is None or not storage.can_access(job.get("owner_id"), user):
        raise HTTPException(404, "Job nicht gefunden")
    out = {k: job[k] for k in ("id", "kind", "status", "progress", "outputs", "checks", "warnings", "error")}
    out["items"] = job.get("items")        # Stapel-Scan: Stand je Werkzeug
    return out
