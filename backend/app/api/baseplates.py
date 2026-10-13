from fastapi import APIRouter, Depends, HTTPException

from .. import build_tasks, jobs
from ..auth import Principal, current_user
from ..geometry.baseplate import plan_tiles
from ..schemas import BaseplateSpec
from ..storage import _root

router = APIRouter(prefix="/baseplates", tags=["baseplates"])


@router.post("/build")
def build(spec: BaseplateSpec, user: Principal = Depends(current_user)) -> dict:
    try:
        plan_tiles(spec)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    job_id = jobs.submit("baseplate", build_tasks.build_baseplate_job, _root("baseplates"), spec.model_dump_json(),
                         owner=user)
    return {"job_id": job_id}
