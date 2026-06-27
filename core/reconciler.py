"""
Reconciliacion de estado entre la DB y el broker al arrancar el bot.

Compara las posiciones reales en Tradovate con los trades OPEN en la DB
y corrige las discrepancias que pueden ocurrir si el bot se reinicia
en medio de una operacion (SIGTERM, crash, perdida de conexion).

Tres casos posibles:

  A) Posicion en broker, NO en DB
     El fill de entrada llego al broker pero el bot no pudo guardarlo.
     Accion: insertar el trade en DB usando los datos del broker y
             actualizar open_contracts en RiskManager.

  B) Trade OPEN en DB, posicion plana en broker
     El broker cerro la posicion (TP, SL o manual) pero el fill de
     salida no llego al bot. Se busca en el historial de fills el
     precio de cierre; si no se encuentra, se cierra con precio 0
     y pnl 0 para mantener la DB consistente (requiere revision manual).

  C) Tamanios distintos (broker != DB)
     Situacion inesperada. Se loguea para revision manual sin modificar
     nada automaticamente.
"""
import logging
from datetime import datetime, timezone

from persistence.common import ExitReason
from persistence.models import Account
from persistence.repository import TradeRepository
from persistence.session import get_session
from risk.risk_manager import RiskManager
from strategy.base_strategy import BaseStrategy
from tradovate.rest_client import TradovateRestClient

logger = logging.getLogger(__name__)


async def reconcile(
    account: Account,
    strategy: BaseStrategy,
    rest_client: TradovateRestClient,
    trade_repo: TradeRepository,
    risk_manager: RiskManager,
) -> None:
    """
    Punto de entrada del reconciliador. Llamar una vez al arrancar,
    despues de crear RiskManager y antes de suscribirse a los feeds.
    """
    log = logging.getLogger(f"reconciler.{account.account_id}")

    # --- Posicion en el broker ----------------------------------------
    contract_id = await rest_client.find_contract_id(strategy.symbol)
    all_positions = await rest_client.get_positions()
    broker_pos = next(
        (p for p in all_positions if p.get("contractId") == contract_id),
        None,
    )
    broker_net_pos: int = int(broker_pos["netPos"]) if broker_pos else 0
    broker_net_price: float = float(broker_pos.get("netPrice", 0.0)) if broker_pos else 0.0

    # --- Posicion en la DB -------------------------------------------
    with get_session() as db:
        open_trades = trade_repo.get_open_trades(account.account_id, db)

    db_net_pos = sum(
        t["qty"] if t["direction"] == "LONG" else -t["qty"]
        for t in open_trades
    )

    log.info(
        "Reconciliacion: broker netPos=%d | DB open_contracts=%d",
        broker_net_pos, db_net_pos,
    )

    # --- Sin discrepancia ---------------------------------------------
    if broker_net_pos == db_net_pos:
        log.info("Estado consistente. No se requiere accion.")
        return

    log.warning(
        "DISCREPANCIA detectada entre broker (netPos=%d) y DB (open_contracts=%d).",
        broker_net_pos, db_net_pos,
    )

    # --- Caso A: fill perdido en entrada ------------------------------
    if broker_net_pos != 0 and db_net_pos == 0:
        await _handle_missed_entry(
            account, trade_repo, risk_manager,
            broker_net_pos, broker_net_price, log,
        )

    # --- Caso B: cierre sin fill event --------------------------------
    elif broker_net_pos == 0 and db_net_pos != 0:
        await _handle_missed_exit(
            account, trade_repo, risk_manager,
            rest_client, contract_id, open_trades, log,
        )

    # --- Caso C: tamanios distintos -----------------------------------
    else:
        log.error(
            "Caso C — tamanios no coinciden (broker=%d, DB=%d). "
            "Revisar manualmente en Tradovate antes de continuar.",
            broker_net_pos, db_net_pos,
        )


async def _handle_missed_entry(
    account: Account,
    trade_repo: TradeRepository,
    risk_manager: RiskManager,
    broker_net_pos: int,
    broker_net_price: float,
    log: logging.Logger,
) -> None:
    """Caso A: el broker tiene posicion pero la DB no la conoce."""
    direction = "LONG" if broker_net_pos > 0 else "SHORT"
    qty = abs(broker_net_pos)
    log.warning(
        "Caso A — fill de entrada perdido. "
        "Registrando %s x%d @ %.2f en DB.",
        direction, qty, broker_net_price,
    )
    with get_session() as db:
        uid = trade_repo.open_trade(
            account_id=account.account_id,
            symbol=strategy.symbol,
            direction=direction,
            qty=qty,
            entry_price=broker_net_price,
            db=db,
            entry_ts=datetime.now(timezone.utc),
        )
    risk_manager.open_contracts = broker_net_pos
    log.warning(
        "Trade insertado: uid=%s. Verificar que el precio de entrada (%.2f) "
        "sea correcto en Tradovate.",
        uid, broker_net_price,
    )


async def _handle_missed_exit(
    account: Account,
    trade_repo: TradeRepository,
    risk_manager: RiskManager,
    rest_client: TradovateRestClient,
    contract_id: int,
    open_trades: list[dict],
    log: logging.Logger,
) -> None:
    """Caso B: la DB tiene trades OPEN pero el broker esta plano."""
    log.warning(
        "Caso B — %d trade(s) OPEN en DB pero posicion plana en broker. "
        "Buscando fill de cierre en historial...",
        len(open_trades),
    )

    all_fills = await rest_client.get_fills()
    fills_del_contrato = [
        f for f in all_fills if f.get("contractId") == contract_id
    ]

    for trade in open_trades:
        trade_uid = trade["uid"]
        entry_ts_raw = trade.get("entry_ts")
        entry_ts = (
            entry_ts_raw if isinstance(entry_ts_raw, datetime)
            else datetime.fromisoformat(str(entry_ts_raw))
        )

        closing_fill = _find_closing_fill(fills_del_contrato, trade, entry_ts)

        with get_session() as db:
            if closing_fill:
                exit_price = float(closing_fill["price"])
                exit_ts = datetime.fromisoformat(
                    closing_fill["timestamp"].replace("Z", "+00:00")
                )
                entry_price = trade["entry_price"]
                qty = trade["qty"]
                direction = trade["direction"]
                point_value = strategy.point_value
                pnl = (
                    (exit_price - entry_price) * qty * point_value
                    if direction == "LONG"
                    else (entry_price - exit_price) * qty * point_value
                )
                trade_repo.close_trade(
                    trade_uid, exit_price, db,
                    exit_ts=exit_ts,
                    pnl=pnl,
                    exit_reason=ExitReason.MANUAL,
                )
                risk_manager.register_fill(pnl_delta=pnl, contracts_delta=-qty if direction == "LONG" else qty)
                log.warning(
                    "Trade %s cerrado via fill recuperado: exit=%.2f pnl=%.2f.",
                    trade_uid, exit_price, pnl,
                )
            else:
                trade_repo.close_trade(
                    trade_uid, exit_price=0.0, db=db,
                    pnl=0.0,
                    exit_reason=ExitReason.MANUAL,
                )
                log.error(
                    "Trade %s: no se encontro fill de cierre. "
                    "Cerrado con pnl=0 para limpiar la DB. "
                    "Revisar manualmente en Tradovate y corregir el PnL si es necesario.",
                    trade_uid,
                )

    risk_manager.open_contracts = 0


def _find_closing_fill(
    fills: list[dict],
    trade: dict,
    entry_ts: datetime,
) -> dict | None:
    """Busca el fill de cierre de un trade en el historial de fills del broker.

    Considera que el fill de cierre es el primero posterior a entry_ts cuya
    direccion es la contraria al trade (venta para un LONG, compra para un SHORT).
    """
    closing_side = "Sell" if trade["direction"] == "LONG" else "Buy"
    candidates = [
        f for f in fills
        if f.get("action", "") == closing_side
        and datetime.fromisoformat(
            f["timestamp"].replace("Z", "+00:00")
        ) > entry_ts
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda f: f["timestamp"])