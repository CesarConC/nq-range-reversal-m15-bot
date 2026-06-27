"""
Estrategia M5 Range Breakout.

Logica:
  1. Cada vela M5 que cierra define un rango (su high y su low).
  2. Tras esa vela, se observan las velas M1 siguientes buscando
     este patron:
       - 2 velas M1 consecutivas cierran DENTRO del rango M5.
       - La siguiente vela M1 cierra FUERA del rango (rotura).
  3. La rotura define la direccion:
       - Close > range_high -> LONG
       - Close < range_low  -> SHORT
  4. Entrada a mercado (el order_manager usa Market order siempre).
     El entry_price de la señal es el cierre de la vela de rotura
     y se usa solo para calcular el tamano de la posicion.
  5. SL: minimo de la 1a vela M1 de la secuencia (LONG)
          o maximo (SHORT).
  6. TP: entry +/- riesgo * RR_RATIO (controlado por la variable RR_RATIO).

Ventana deslizante: si mas de 2 M1 cierran dentro del rango antes de
la rotura, se mantienen siempre las 2 ultimas como referencia para el SL.
El rango se reinicia con cada nuevo cierre de M5.
"""
import logging
from typing import Optional

from strategy.base_strategy import BaseStrategy
from tradovate.models import Candle, TradeSignal

logger = logging.getLogger(__name__)


class M5RangeBreakout(BaseStrategy):
    risk_pct: float = 0.01    # 1% del balance inicial por operacion
    rr_ratio: float = 1.0     # TP = 1 * distancia_SL (ratio 1:1)
    symbol: str = 'MNQ'
    point_value: float = 2.0

    def __init__(self):
        self._range_high: Optional[float] = None
        self._range_low: Optional[float] = None
        # Ventana deslizante: las 2 ultimas M1 que cerraron dentro del rango
        self._m1_seq: list[Candle] = []

    # ------------------------------------------------------------------ #
    # M5: fija el rango y reinicia el seguimiento de M1
    # ------------------------------------------------------------------ #
    def on_m5_close(self, candle: Candle) -> Optional[TradeSignal]:
        self._range_high = candle.high
        self._range_low = candle.low
        self._m1_seq = []
        logger.info(
            "Rango M5 actualizado: H=%.2f L=%.2f [%s]",
            candle.high, candle.low, candle.open_time.strftime("%H:%M"),
        )
        return None

    # ------------------------------------------------------------------ #
    # M1: detecta el patron 2-dentro + 1-fuera
    # ------------------------------------------------------------------ #
    def on_m1_close(self, candle: Candle) -> Optional[TradeSignal]:
        if self._range_high is None or self._range_low is None:
            return None  # todavia no hay rango M5

        closes_inside = self._range_low <= candle.close <= self._range_high

        if closes_inside:
            # Ventana deslizante: maximo 2 velas
            if len(self._m1_seq) < 2:
                self._m1_seq.append(candle)
            else:
                self._m1_seq.pop(0)
                self._m1_seq.append(candle)
            logger.debug("M1 dentro del rango (%d/2) close=%.2f", len(self._m1_seq), candle.close)
            return None

        # La vela cierra fuera del rango
        if len(self._m1_seq) < 2:
            logger.debug(
                "M1 fuera del rango con solo %d vela(s) dentro. Reiniciando secuencia.",
                len(self._m1_seq),
            )
            self._m1_seq = []
            return None

        # Patron completo: 2 dentro + esta rompe el rango
        signal = self._build_signal(candle)
        self._m1_seq = []
        return signal

    # ------------------------------------------------------------------ #
    # Construccion de la señal
    # ------------------------------------------------------------------ #
    def _build_signal(self, breakout: Candle) -> Optional[TradeSignal]:
        seq_first = self._m1_seq[0]  # 1a vela de la secuencia -> referencia del SL

        if breakout.close > self._range_high:
            direction = "LONG"
            entry = breakout.close
            sl = seq_first.low
            if sl >= entry:
                logger.warning("LONG descartado: SL (%.2f) >= entry (%.2f)", sl, entry)
                return None
            risk = entry - sl
            tp = entry + risk * self.rr_ratio

        else:  # close < range_low
            direction = "SHORT"
            entry = breakout.close
            sl = seq_first.high
            if sl <= entry:
                logger.warning("SHORT descartado: SL (%.2f) <= entry (%.2f)", sl, entry)
                return None
            risk = sl - entry
            tp = entry - risk * self.rr_ratio

        logger.info(
            "Señal M5 breakout: %s entry=%.2f sl=%.2f tp=%.2f riesgo=%.2f pts",
            direction, entry, sl, tp, risk,
        )
        return TradeSignal(
            direction=direction,
            entry_price=entry,
            take_profit=tp,
            stop_loss=sl,
            reason=f"M5 rango rotura {direction}",
        )
