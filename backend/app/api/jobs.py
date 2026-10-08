from fastapi import APIRouter, HTTPException

from .. import jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job nicht gefunden")
    return {k: job[k] for k in ("id", "kind", "status", "progress", "outputs", "checks", "warnings", "error")}
