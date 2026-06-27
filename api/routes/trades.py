from typing import Optional

from fastapi import APIRouter, Query

from api.deps import ControllerDep, SessionDep

router = APIRouter()


def _trade_to_dict(trade) -> dict:
    pnl = trade.pnl or 0.0
    if pnl > 0:
        result = "win"
    elif pnl < 0:
        result = "loss"
    else:
        result = "breakeven"

    return {
        "id": trade.uid,
        "symbol": trade.symbol,
        "side": trade.direction.lower(),
        "contracts": trade.qty,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price or 0.0,
        "pnl": pnl,
        "result": result,
        "opened_at": trade.entry_ts.isoformat() if trade.entry_ts else "",
        "closed_at": trade.exit_ts.isoformat() if trade.exit_ts else "",
    }


@router.get("/trades")
def get_trades(
    ctrl: ControllerDep,
    db: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200, alias="page_size"),
    side: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    from datetime import datetime, timezone

    df = None
    dt = None
    if date_from:
        try:
            df = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    direction = side.upper() if side and side.lower() in ("long", "short") else None
    if direction == "LONG":
        direction = "LONG"
    elif direction == "SHORT":
        direction = "SHORT"
    else:
        direction = None

    rows, total = ctrl.trade_repo.get_trades_paged(
        account_id=ctrl.account_id,
        db=db,
        page=page,
        page_size=page_size,
        direction=direction,
        date_from=df,
        date_to=dt,
    )

    return {
        "items": [_trade_to_dict(t) for t in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }