"""
Endpoints de administracion: listar y crear cuentas en la base de datos.
No requieren un bot en ejecucion — solo acceso a la DB.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.deps import SessionDep
from persistence.models import Account

router = APIRouter()


def _register_controller(account: Account) -> None:
    """Registra el controlador en memoria para que el dashboard pueda arrancarlo.

    Usa imports diferidos para evitar importacion circular:
    admin → run_paper → api.server → admin.
    """
    from core.registry import BotController, controllers
    from persistence.repository import TradeRepository
    from scripts.run_paper import run_account

    if account.account_id not in controllers:
        controllers[account.account_id] = BotController(
            account_id=account.account_id,
            account_cfg=account,
            trade_repo=TradeRepository(),
            run_fn=run_account,
            status='stopped',
        )


class AccountCreate(BaseModel):
    account_id: str
    label: str
    prop_firm: str = ''
    account_type: str = 'evaluation'
    environment: str = 'demo'
    username: str
    password: str
    system_name: str = ''
    app_id: str = 'MyTradingBot'
    app_version: str = '1.0'
    device_id: str = 'bot-device-001'
    strategy: str
    symbol: str
    point_value: float
    initial_balance: float
    max_drawdown: float
    daily_drawdown: float = 0.0
    profit_target: float
    consistency_pct: float
    max_contracts: int
    account_cost: float = 0.0
    withdrawn_amount: float = 0.0
    is_active: bool = True


def _to_public(acc: Account) -> dict:
    d = acc.model_dump()
    d.pop('password', None)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


@router.get('/accounts')
def list_accounts(db: SessionDep) -> list[dict]:
    accounts = db.exec(select(Account).order_by(Account.created_at)).all()
    return [_to_public(a) for a in accounts]


@router.post('/accounts', status_code=201)
def create_account(payload: AccountCreate, db: SessionDep) -> dict:
    existing = db.get(Account, payload.account_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Ya existe una cuenta con id '{payload.account_id}'")

    account = Account(**payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    _register_controller(account)
    return _to_public(account)