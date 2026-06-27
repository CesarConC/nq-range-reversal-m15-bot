"""
Repositorio de operaciones.

Cada metodo recibe una sesion activa (db: Session) desde el llamante.
El llamante es responsable de abrir y cerrar la sesion:

    from persistence.session import get_session

    with get_session() as db:
        trade_repo.save_signal(account_id, symbol, signal, ts, db)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
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

    def get_daily_pnl(self, account_id: str, db: Session) -> float:
        """Suma del PnL de las operaciones cerradas desde medianoche UTC de hoy.

        Usada al reiniciar el bot para restaurar daily_pnl en RiskManager.
        Devuelve 0.0 si no hay trades cerrados hoy.
        """
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        statement = select(Trade).where(
            Trade.account_id == account_id,
            Trade.status == TradeStatus.CLOSED,
            Trade.exit_ts >= today_start,
        )
        trades = db.exec(statement).all()
        pnl = sum(t.pnl for t in trades if t.pnl is not None)
        logger.info(
            "PnL del dia restaurado: account=%s daily_pnl=%.2f (%d trade(s) cerrado(s) hoy)",
            account_id, pnl, len(trades),
        )
        return pnl

    def get_total_pnl(self, account_id: str, db: Session) -> float:
        """Suma del PnL de todos los trades cerrados de la cuenta (historico completo)."""
        statement = select(Trade).where(
            Trade.account_id == account_id,
            Trade.status == TradeStatus.CLOSED,
        )
        trades = db.exec(statement).all()
        return sum(t.pnl for t in trades if t.pnl is not None)

    def get_trades_paged(
        self,
        account_id: str,
        db: Session,
        page: int = 1,
        page_size: int = 20,
        direction: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> tuple[list[Trade], int]:
        """Trades cerrados paginados con filtros opcionales. Devuelve (rows, total)."""
        conditions = [
            Trade.account_id == account_id,
            Trade.status == TradeStatus.CLOSED,
        ]
        if direction:
            conditions.append(Trade.direction == direction)
        if date_from:
            conditions.append(Trade.exit_ts >= date_from)
        if date_to:
            conditions.append(Trade.exit_ts <= date_to)

        total = db.exec(
            select(func.count(Trade.uid)).where(*conditions)
        ).one()

        rows = db.exec(
            select(Trade)
            .where(*conditions)
            .order_by(Trade.exit_ts.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        return list(rows), total

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
