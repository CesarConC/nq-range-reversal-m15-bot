"""
Engine principal: conecta market data -> velas -> estrategia -> riesgo -> ejecucion.

Flujo de datos (entrada):

    MarketDataFeed (quotes tick a tick)
            |
            v
    Engine.on_quote()
            |
            +--> CandleAggregator(M1)  --on_candle_close--> strategy.on_m1_close()  -> TradeSignal?
            +--> CandleAggregator(M5)  --on_candle_close--> strategy.on_m5_close()  -> TradeSignal?
            +--> CandleAggregator(M15) --on_candle_close--> strategy.on_m15_close()

Flujo de datos (vuelta, fills reales):

    UserDataSocket.on_fill --> Engine.on_fill() --> state.apply_fill() --> risk_manager.register_fill()
                                                                       --> trade_repo (si configurado)

Cuando la estrategia devuelve una TradeSignal, el engine:
  1. Siempre la loguea (y la pasa a on_signal si se proporciono, util para tests/debug).
  2. Si hay risk_manager, le pregunta si la señal se puede ejecutar.
  3. Si risk_manager aprueba y hay order_manager, se programa como tarea
     async la entrada real (bracket TP/SL) contra Tradovate.

Si risk_manager u order_manager son None, el engine se queda en modo
"solo observacion": corre la estrategia en vivo contra datos reales y
muestra que haria, pero no manda ninguna orden.

Si trade_repo esta configurado, el engine persiste cada señal aprobada y el
ciclo completo de cada operacion (apertura y cierre) en la base de datos.
Cada operacion de persistencia abre su propia sesion con get_session().
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from market_data.candle_aggregator import CandleAggregator
from strategy.base_strategy import BaseStrategy
from core.state import AccountState
from persistence.session import get_session
from tradovate.models import Quote, TradeSignal

logger = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        strategy: BaseStrategy,
        symbol: str = "",
        account_id: str = "default",
        risk_manager=None,
        order_manager=None,
        trade_repo=None,
        on_signal: Optional[Callable[[TradeSignal], None]] = None,
        contract_multiplier: float = 2.0,  # MNQ = 2.0 USD por punto
    ):
        self.strategy = strategy
        self.symbol = symbol
        self.account_id = account_id
        self.risk_manager = risk_manager
        self.order_manager = order_manager
        self.trade_repo = trade_repo
        self.on_signal = on_signal
        self.contract_multiplier = contract_multiplier

        self.state = AccountState()
        self.last_price: float = 0.0

        # Estado interno para enlazar señal -> trade en DB
        self._pending_signal_uid: Optional[str] = None
        self._pending_tp: Optional[float] = None
        self._pending_sl: Optional[float] = None
        self._open_trade_uid: Optional[str] = None

        self._m1_agg = CandleAggregator(1, on_candle_close=self._on_m1_close)
        self._m5_agg = CandleAggregator(5, on_candle_close=self._on_m5_close)
        self._m15_agg = CandleAggregator(15, on_candle_close=self._on_m15_close)

    def seed_m15_bar(self, candle) -> None:
        """Pre-carga la vela M15 parcial actual en el aggregator.

        Llamar una vez al arrancar, despues de obtener el bar historico del broker
        via REST y antes de conectar el WebSocket de market data.
        """
        self._m15_agg.seed(candle)

    def seed_m5_bar(self, candle) -> None:
        """Pre-carga la vela M5 parcial actual en el aggregator."""
        self._m5_agg.seed(candle)

    # ------------------------------------------------------------------ #
    # Entrada: quotes -> velas -> estrategia
    # ------------------------------------------------------------------ #
    def on_quote(self, quote: Quote, timestamp: Optional[datetime] = None) -> None:
        """Pasar como callback directo a MarketDataFeed(on_quote=engine.on_quote)."""
        if quote.last is not None:
            self.last_price = quote.last
        self._m1_agg.on_quote(quote, timestamp)
        self._m5_agg.on_quote(quote, timestamp)
        self._m15_agg.on_quote(quote, timestamp)

    def _on_m15_close(self, candle) -> None:
        logger.info(
            "[%s] Vela M15 cerrada: O=%.2f H=%.2f L=%.2f C=%.2f",
            self.symbol, candle.open, candle.high, candle.low, candle.close,
        )
        self.strategy.on_m15_close(candle)

    def _on_m5_close(self, candle) -> None:
        logger.info(
            "[%s] Vela M5 cerrada: O=%.2f H=%.2f L=%.2f C=%.2f",
            self.symbol, candle.open, candle.high, candle.low, candle.close,
        )
        signal = self.strategy.on_m5_close(candle)
        if signal is not None:
            self._handle_signal(signal)

    def _on_m1_close(self, candle) -> None:
        signal = self.strategy.on_m1_close(candle)
        if signal is not None:
            self._handle_signal(signal)

    # ------------------------------------------------------------------ #
    # Señales generadas por la estrategia -> riesgo -> ejecucion
    # ------------------------------------------------------------------ #
    def _handle_signal(self, signal: TradeSignal) -> None:
        logger.info(
            "Señal generada [%s] -> %s entry=%.2f tp=%.2f sl=%.2f | %s",
            self.symbol, signal.direction, signal.entry_price,
            signal.take_profit, signal.stop_loss, signal.reason,
        )

        if self.on_signal:
            self.on_signal(signal)

        if self.risk_manager is None:
            logger.warning("risk_manager no configurado -- señal NO se ejecuta (solo observacion)")
            return

        qty = self.risk_manager.calculate_contracts(signal.entry_price, signal.stop_loss)
        if qty == 0:
            logger.warning(
                "Señal descartada: SL demasiado lejos para el presupuesto de riesgo "
                "(entry=%.2f sl=%.2f)", signal.entry_price, signal.stop_loss,
            )
            return

        allowed, reason = self.risk_manager.can_open_position(qty, signal.direction)
        if not allowed:
            logger.warning("Señal bloqueada por risk_manager: %s", reason)
            return

        if self.order_manager is None:
            logger.warning(
                "order_manager no configurado -- señal aprobada por riesgo "
                "pero NO se envia orden real todavia"
            )
            return

        # Guardar la señal en DB antes de enviar la orden
        signal_uid: Optional[str] = None
        if self.trade_repo is not None:
            with get_session() as db:
                signal_uid = self.trade_repo.save_signal(
                    self.symbol, signal, datetime.now(timezone.utc), db
                )
            self._pending_signal_uid = signal_uid
            self._pending_tp = signal.take_profit
            self._pending_sl = signal.stop_loss

        # _handle_signal es sincrono (lo llaman los callbacks del agregador
        # de velas), pero order_manager.enter_from_signal es async. Se
        # programa como tarea del event loop que ya esta corriendo.
        asyncio.create_task(self._send_order(signal, qty, signal_uid=signal_uid))

    async def _send_order(
        self, signal: TradeSignal, qty: int, signal_uid: Optional[str] = None
    ) -> None:
        try:
            response = await self.order_manager.enter_from_signal(self.symbol, signal, qty)
            logger.info("Orden enviada correctamente: %s", response)
            if self.trade_repo is not None and signal_uid is not None:
                with get_session() as db:
                    self.trade_repo.mark_signal_executed(signal_uid, db)
        except Exception:
            logger.exception("Fallo al enviar la orden real para la señal %s", signal)

    # ------------------------------------------------------------------ #
    # Vuelta: fills reales -> estado de cuenta -> riesgo -> persistencia
    # ------------------------------------------------------------------ #
    def on_fill(self, fill: dict) -> None:
        """Pasar como callback directo a UserDataSocket(on_fill=engine.on_fill)."""
        action = fill.get("action")
        qty = fill.get("qty")
        price = fill.get("price")

        if action is None or qty is None or price is None:
            logger.warning("Fill incompleto, no se puede actualizar el estado: %s", fill)
            return

        pnl_before = self.state.daily_realized_pnl
        position_before = self.state.position_qty

        self.state.apply_fill(action, qty, price, multiplier=self.contract_multiplier)

        pnl_delta = self.state.daily_realized_pnl - pnl_before
        contracts_delta = self.state.position_qty - position_before

        if self.risk_manager is not None:
            self.risk_manager.register_fill(pnl_delta, contracts_delta)

        self._persist_fill(position_before, price, pnl_delta)

        logger.info(
            "Estado actualizado tras fill: posicion=%s avg_entry=%.2f pnl_dia=%.2f",
            self.state.position_qty, self.state.avg_entry_price, self.state.daily_realized_pnl,
        )

    def _persist_fill(self, position_before: int, price: float, pnl_delta: float) -> None:
        """Actualiza la DB segun si el fill abre o cierra una operacion."""
        if self.trade_repo is None:
            return

        now = datetime.now(timezone.utc)
        position_after = self.state.position_qty

        if position_before == 0 and position_after != 0:
            # Fill de apertura: nueva operacion
            direction = "LONG" if position_after > 0 else "SHORT"
            with get_session() as db:
                self._open_trade_uid = self.trade_repo.open_trade(
                    account_id=self.account_id,
                    symbol=self.symbol,
                    direction=direction,
                    qty=abs(position_after),
                    entry_price=price,
                    db=db,
                    entry_ts=now,
                    tp=self._pending_tp,
                    sl=self._pending_sl,
                    signal_uid=self._pending_signal_uid,
                )
            self._pending_signal_uid = None
            self._pending_tp = None
            self._pending_sl = None

        elif position_before != 0 and position_after == 0 and self._open_trade_uid is not None:
            # Fill de cierre: la operacion se ha cerrado por completo
            with get_session() as db:
                self.trade_repo.close_trade(
                    trade_uid=self._open_trade_uid,
                    exit_price=price,
                    db=db,
                    exit_ts=now,
                    pnl=pnl_delta,
                )
            self._open_trade_uid = None
