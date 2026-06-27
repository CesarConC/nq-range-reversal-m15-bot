import asyncio

from fastapi import APIRouter, HTTPException

from api.deps import ControllerDep

router = APIRouter()


@router.post("/bot/stop")
async def stop_bot(ctrl: ControllerDep):
    if ctrl.task is None or ctrl.task.done():
        raise HTTPException(status_code=400, detail="Bot is not running")
    ctrl.task.cancel()
    return {"status": "stopping"}


@router.post("/bot/start")
async def start_bot(ctrl: ControllerDep):
    if ctrl.task is not None and not ctrl.task.done():
        raise HTTPException(status_code=409, detail="Bot is already running")
    if ctrl.run_fn is None:
        raise HTTPException(status_code=503, detail="Bot runner not initialized")
    loop = asyncio.get_event_loop()
    ctrl.task = loop.create_task(
        ctrl.run_fn(ctrl.account_cfg, ctrl.trade_repo),
        name=f"bot-{ctrl.account_id}",
    )
    return {"status": "starting"}