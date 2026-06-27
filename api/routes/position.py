from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.deps import ControllerDep

router = APIRouter()


@router.get("/position")
def get_position(ctrl: ControllerDep):
    engine = ctrl.engine

    if engine is None or engine.state.position_qty == 0:
        return JSONResponse(content=None)

    state = engine.state
    pos_qty = state.position_qty       # positivo=long, negativo=short
    avg_entry = state.avg_entry_price
    last_price = engine.last_price
    point_value = ctrl.account_cfg.point_value

    unrealized = (last_price - avg_entry) * pos_qty * point_value if last_price > 0 else 0.0

    # Timestamp de apertura: primera orden abierta en open_orders, o ahora
    opened_at: str
    if state.open_orders:
        # open_orders no guarda timestamp; usamos started_at del controller como aproximacion
        opened_at = (ctrl.started_at or datetime.now(timezone.utc)).isoformat()
    else:
        opened_at = datetime.now(timezone.utc).isoformat()

    return {
        "symbol": engine.symbol,
        "side": "long" if pos_qty > 0 else "short",
        "contracts": abs(pos_qty),
        "entry_price": avg_entry,
        "current_price": last_price,
        "unrealized_pnl": unrealized,
        "opened_at": opened_at,
    }