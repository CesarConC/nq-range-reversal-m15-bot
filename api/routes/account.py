from fastapi import APIRouter

from api.deps import ControllerDep, SessionDep

router = APIRouter()


@router.get("/account")
def get_account(ctrl: ControllerDep, db: SessionDep):
    cfg = ctrl.account_cfg
    engine = ctrl.engine
    risk_mgr = ctrl.risk_manager

    # PnL realizado total (todos los trades cerrados en DB)
    total_realized = ctrl.trade_repo.get_total_pnl(cfg.account_id, db)

    # PnL del dia: desde el engine si esta corriendo, si no desde DB
    if engine is not None:
        daily_pnl = engine.state.daily_realized_pnl
    else:
        daily_pnl = ctrl.trade_repo.get_daily_pnl(cfg.account_id, db)

    balance = cfg.initial_balance + total_realized

    # PnL no realizado de la posicion abierta (si hay engine y precio disponible)
    unrealized = 0.0
    if engine is not None and engine.state.position_qty != 0 and engine.last_price > 0:
        pos_qty = engine.state.position_qty      # positivo=long, negativo=short
        avg_entry = engine.state.avg_entry_price
        unrealized = (engine.last_price - avg_entry) * pos_qty * cfg.point_value

    equity = balance + unrealized

    # Drawdown: cuanto hemos caido desde el maximo EOD
    max_eod = risk_mgr.max_eod_balance if risk_mgr is not None else balance
    drawdown = max(0.0, max_eod - balance)
    drawdown_pct = (drawdown / cfg.max_drawdown * 100) if cfg.max_drawdown > 0 else 0.0

    return {
        "balance": balance,
        "equity": equity,
        "daily_pnl": daily_pnl,
        "total_pnl": total_realized,
        "drawdown": drawdown,
        "drawdown_pct": drawdown_pct,
        "max_drawdown": cfg.max_drawdown,
        "profit_target": cfg.profit_target,
    }