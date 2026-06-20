"""
Engine principal: conecta market data -> velas -> estrategia -> riesgo -> ejecucion.

Flujo de datos (entrada):

    MarketDataFeed (quotes tick a tick)
            |
            v
    Engine.on_quote()
            |
            +--> CandleAggregator(M1)  --on_candle_close--> strategy.on_m1_close()  -> TradeSignal?
            +--> CandleAggregator(M15) --on_candle_close--> strategy.on_m15_close()

Flujo de datos (vuelta, fills reales):

    UserDataSocket.on_fill --> Engine.on_fill() --> state.apply_fill() --> risk_manager.register_fill()

Cuando la estrategia devuelve una TradeSignal, el engine:
  1. Siempre la loguea (y la pasa a on_signal si se proporciono, util para tests/debug).
  2. Si hay risk_manager, le pregunta si la señal se puede ejecutar.
  3. Si risk_manager aprueba y hay order_manager, se programa como tarea
     async la entrada real (bracket TP/SL) contra Tradovate.

Si risk_manager u order_manager son None, el engine se queda en modo
"solo observacion": corre la estrategia en vivo contra datos reales y
muestra que haria, pero no manda ninguna orden.
"""
import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

from market_data.candle_aggregator import CandleAggregator
from strategy.base_strategy import BaseStrategy
from core.state import AccountState
from tradovate.models import Quote, TradeSignal

logger = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        strategy: BaseStrategy,
        symbol: str = "",
        risk_manager=None,
        order_manager=None,
        on_signal: Optional[Callable[[TradeSignal], None]] = None,
        contract_multiplier: float = 2.0,  # MNQ = 2.0 USD por punto
    ):
        self.strategy = strategy
        self.symbol = symbol
        self.risk_manager = risk_manager
        self.order_manager = order_manager
        self.on_signal = on_signal
        self.contract_multiplier = contract_multiplier

        self.state = AccountState()

        self._m1_agg = CandleAggregator(1, on_candle_close=self._on_m1_close)
        self._m15_agg = CandleAggregator(15, on_candle_close=self._on_m15_close)

    # ------------------------------------------------------------------ #
    # Entrada: quotes -> velas -> estrategia
    # ------------------------------------------------------------------ #
    def on_quote(self, quote: Quote, timestamp: Optional[datetime] = None) -> None:
        """Pasar como callback directo a MarketDataFeed(on_quote=engine.on_quote)."""
        self._m1_agg.on_quote(quote, timestamp)
        self._m15_agg.on_quote(quote, timestamp)

    def _on_m15_close(self, candle) -> None:
        logger.info(
            "[%s] Vela M15 cerrada: O=%.2f H=%.2f L=%.2f C=%.2f",
            self.symbol, candle.open, candle.high, candle.low, candle.close,
        )
        self.strategy.on_m15_close(candle)

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

        allowed, reason = self.risk_manager.can_open_position(qty)
        if not allowed:
            logger.warning("Señal bloqueada por risk_manager: %s", reason)
            return

        if self.order_manager is None:
            logger.warning(
                "order_manager no configurado -- señal aprobada por riesgo "
                "pero NO se envia orden real todavia"
            )
            return

        # _handle_signal es sincrono (lo llaman los callbacks del agregador
        # de velas), pero order_manager.enter_from_signal es async. Se
        # programa como tarea del event loop que ya esta corriendo (el del
        # script run_paper.py/run_live.py).
        asyncio.create_task(self._send_order(signal, qty))

    async def _send_order(self, signal: TradeSignal, qty: int) -> None:
        try:
            response = await self.order_manager.enter_from_signal(self.symbol, signal, qty)
            logger.info("Orden enviada correctamente: %s", response)
        except Exception:
            logger.exception("Fallo al enviar la orden real para la señal %s", signal)

    # ------------------------------------------------------------------ #
    # Vuelta: fills reales -> estado de cuenta -> riesgo
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

        logger.info(
            "Estado actualizado tras fill: posicion=%s avg_entry=%.2f pnl_dia=%.2f",
            self.state.position_qty, self.state.avg_entry_price, self.state.daily_realized_pnl,
        )
