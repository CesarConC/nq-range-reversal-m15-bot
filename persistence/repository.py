"""
Repositorio de operaciones.

Cada metodo recibe una sesion activa (db: Session) desde el llamante.
El llamante es responsable de abrir y cerrar la sesion:

    from persistence.session import get_session

    with get_session() as db:
        trade_repo.save_signal(symbol, signal, ts, db)
"""
import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from persistence.common import TradeStatus, now_utc
from persistence.models import Signal, Trade
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
            "Trade abierto [uid=%s]: %s %s x%d @ %.2f tp=%s sl=%s",
            record.uid, symbol, direction, qty, entry_price,
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

    def get_open_trades(self, db: Session) -> list[dict]:
        """Devuelve todas las operaciones con status OPEN."""
        statement = select(Trade).where(Trade.status == TradeStatus.OPEN)
        rows = db.exec(statement).all()
        return [r.model_dump() for r in rows]

    def get_trades(
        self,
        db: Session,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Devuelve las ultimas operaciones, opcionalmente filtradas por simbolo."""
        statement = select(Trade).order_by(Trade.uid.desc()).limit(limit)
        if symbol:
            statement = statement.where(Trade.symbol == symbol)
        rows = db.exec(statement).all()
        return [r.model_dump() for r in rows]
