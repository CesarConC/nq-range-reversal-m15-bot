"""
Repositorio de operaciones.

Cada metodo recibe una sesion activa (db: Session) desde el llamante.
El llamante es responsable de abrir y cerrar la sesion:

    from persistence.session import get_session

    with get_session() as db:
        trade_repo.save_signal(account_id, symbol, signal, ts, db)
"""
import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from persistence.common import TradeStatus, now_utc
from persistence.models import Account, RiskState, Signal, Trade
from tradovate.models import TradeSignal

logger = logging.getLogger(__name__)


class TradeRepository:

    # ------------------------------------------------------------------ #
    # Señales
    # ------------------------------------------------------------------ #

    def save_signal(
        self,
        symbol: str,
        signal: TradeSignal,
        ts: Optional[datetime],
        db: Session,
    ) -> str:
        """Persiste la señal y devuelve su uid."""
        record = Signal(
            ts=ts or now_utc(),
            symbol=symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.debug(
            "Signal guardada: uid=%s %s %s @ %.2f",
            record.uid, symbol, signal.direction, signal.entry_price,
        )
        return record.uid

    def mark_signal_executed(self, signal_uid: str, db: Session) -> None:
        """Marca la señal como ejecutada (orden enviada al broker sin error)."""
        record = db.get(Signal, signal_uid)
        if record is not None:
            record.executed = True
            db.add(record)
            db.commit()

    # ------------------------------------------------------------------ #
    # Trades
    # ------------------------------------------------------------------ #

    def open_trade(
        self,
        account_id: str,
        symbol: str,
        direction: str,
        qty: int,
        entry_price: float,
        db: Session,
        entry_ts: Optional[datetime] = None,
        tp: Optional[float] = None,
        sl: Optional[float] = None,
        signal_uid: Optional[str] = None,
    ) -> str:
        """Registra la apertura de una operacion y devuelve su uid."""
        record = Trade(
            account_id=account_id,
            signal_uid=signal_uid,
            symbol=symbol,
            direction=direction,
            qty=qty,
            entry_price=entry_price,
            entry_ts=entry_ts or now_utc(),
            tp=tp,
            sl=sl,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.info(
            "Trade abierto [uid=%s] account=%s: %s %s x%d @ %.2f tp=%s sl=%s",
            record.uid, account_id, symbol, direction, qty, entry_price,
            f"{tp:.2f}" if tp else "—", f"{sl:.2f}" if sl else "—",
        )
        return record.uid

    def close_trade(
        self,
        trade_uid: str,
        exit_price: float,
        db: Session,
        exit_ts: Optional[datetime] = None,
        pnl: float = 0.0,
        exit_reason: Optional[str] = None,
    ) -> None:
        """Actualiza el trade con los datos de cierre."""
        record = db.get(Trade, trade_uid)
        if record is None:
            logger.warning("close_trade: trade uid=%s no encontrado en DB", trade_uid)
            return
        record.exit_price = exit_price
        record.exit_ts = exit_ts or now_utc()
        record.pnl = pnl
        record.exit_reason = exit_reason
        record.status = TradeStatus.CLOSED
        db.add(record)
        db.commit()
        logger.info(
            "Trade cerrado [uid=%s]: @ %.2f  pnl=%.2f  razon=%s",
            trade_uid, exit_price, pnl, exit_reason or "—",
        )

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #

    def get_open_trades(self, account_id: str, db: Session) -> list[dict]:
        """Devuelve todas las operaciones abiertas de la cuenta."""
        statement = (
            select(Trade)
            .where(Trade.account_id == account_id, Trade.status == TradeStatus.OPEN)
        )
        rows = db.exec(statement).all()
        return [r.model_dump() for r in rows]

    def get_trades(
        self,
        account_id: str,
        db: Session,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Devuelve las ultimas operaciones de la cuenta, opcionalmente filtradas por simbolo."""
        statement = (
            select(Trade)
            .where(Trade.account_id == account_id)
            .order_by(Trade.uid.desc())
            .limit(limit)
        )
        if symbol:
            statement = statement.where(Trade.symbol == symbol)
        rows = db.exec(statement).all()
        return [r.model_dump() for r in rows]

    # ------------------------------------------------------------------ #
    # Estado de riesgo (sustituye a risk_state.json)
    # ------------------------------------------------------------------ #

    def load_risk_state(
        self,
        account_id: str,
        initial_balance: float,
        db: Session,
    ) -> float:
        """Devuelve max_eod_balance de la cuenta. Si no existe registro, devuelve initial_balance."""
        record = db.get(RiskState, account_id)
        if record is None:
            logger.info(
                "Sin estado de riesgo previo para account=%s. max_eod_balance=%.2f (balance inicial)",
                account_id, initial_balance,
            )
            return initial_balance
        logger.info(
            "Estado de riesgo cargado: account=%s max_eod_balance=%.2f",
            account_id, record.max_eod_balance,
        )
        return record.max_eod_balance

    # ------------------------------------------------------------------ #
    # Cuentas
    # ------------------------------------------------------------------ #

    def get_active_accounts(self, db: Session) -> list[Account]:
        """Devuelve todas las cuentas con is_active=True, ordenadas por account_id."""
        statement = select(Account).where(Account.is_active == True).order_by(Account.account_id)  # noqa: E712
        return list(db.exec(statement).all())

    def save_risk_state(
        self,
        account_id: str,
        max_eod_balance: float,
        db: Session,
    ) -> None:
        """Upsert de max_eod_balance para la cuenta. Llamar tras end_of_day()."""
        record = db.get(RiskState, account_id)
        if record is None:
            record = RiskState(account_id=account_id, max_eod_balance=max_eod_balance)
        else:
            record.max_eod_balance = max_eod_balance
            record.updated_at = now_utc()
        db.add(record)
        db.commit()
        logger.info(
            "Estado de riesgo guardado: account=%s max_eod_balance=%.2f",
            account_id, max_eod_balance,
        )
