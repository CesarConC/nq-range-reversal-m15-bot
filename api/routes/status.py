from datetime import datetime, timezone

from fastapi import APIRouter

from api.deps import ControllerDep

router = APIRouter()


@router.get("/status")
def get_status(ctrl: ControllerDep):
    uptime = 0
    if ctrl.started_at and ctrl.status == "running":
        uptime = int((datetime.now(timezone.utc) - ctrl.started_at).total_seconds())
    return {
        "status": ctrl.status,
        "connected": ctrl.status == "running",
        "uptime_seconds": uptime,
    }