import asyncio

from fastapi import APIRouter, HTTPException

from api.deps import ControllerDep, SessionDep
from persistence.models import Account

router = APIRouter()


@router.post("/bot/stop")
async def stop_bot(ctrl: ControllerDep):
    if ctrl.task is None or ctrl.task.done():
        raise HTTPException(status_code=400, detail="Bot is not running")
    ctrl.task.cancel()
    return {"status": "stopping"}


@router.post("/bot/start")
async def start_bot(ctrl: ControllerDep, db: SessionDep):
    task_alive = ctrl.task is not None and not ctrl.task.done()

    # Rechazar solo si el bot está realmente corriendo o conectando.
    if task_alive and ctrl.status in ("running", "connecting"):
        raise HTTPException(status_code=409, detail="Bot is already running")

    # Si hay un task vivo pero en estado error, cancelarlo antes de reiniciar.
    if task_alive:
        ctrl.task.cancel()

    if ctrl.run_fn is None:
        raise HTTPException(status_code=503, detail="Bot runner not initialized")

    # Si la cuenta estaba inactiva en DB, activarla antes de arrancar el task.
    account = db.get(Account, ctrl.account_id)
    if account is not None and not account.is_active:
        account.is_active = True
        db.add(account)
        db.commit()
        db.refresh(account)
        ctrl.account_cfg = account

    loop = asyncio.get_event_loop()
    ctrl.task = loop.create_task(
        ctrl.run_fn(ctrl.account_cfg, ctrl.trade_repo),
        name=f"bot-{ctrl.account_id}",
    )
    return {"status": "starting"}