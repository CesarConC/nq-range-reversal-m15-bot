"""
Estrategia de reversion sobre rangos de M15, confirmada con velas
envolventes de M1.

Resumen de la logica (confirmada con el usuario antes de programar):

1. Cada vez que cierra una vela de M15, esa vela define el "rango" activo
   [low, high]. Esto SIEMPRE rota: el rango anterior se descarta sin
   importar si dio operacion o no.

2. Durante el periodo de M15 siguiente, en cada cierre de M1 se revisa:
   a) Si se toca (con mecha, no hace falta cierre) el extremo CONTRARIO
      al ya bloqueado -> se descarta el rango entero, no se opera.
   b) Si esta vela hace un extremo MAS profundo que el actual -> esta
      vela pasa a ser la "vela_extremo" objetivo a envolver, se resetea
      la bandera de envolvente (el objetivo se movio). Una vela que se
      convierte en vela_extremo NO puede, en el mismo cierre, ser tambien
      la que envuelve a la vela_extremo anterior.
   c) Si el cuerpo de esta vela envuelve al cuerpo de la vela_extremo
      actual -> se marca engullida=True (se queda "guardado" aunque el
      precio siga fuera del rango).
   d) Si esta vela cierra dentro del rango Y engullida=True -> ENTRADA,
      a mercado, en el cierre de esta vela.

3. TP = el extremo opuesto del rango M15 (fijo, estructural).
   SL = se calcula para que el ratio riesgo:beneficio sea 1:0,33
        (es decir, reward = 0,33 * risk -> risk = reward / 0,33).

4. Solo una operacion por rango, y solo en la direccion del primer
   extremo tomado (no se puede abrir long y short en el mismo rango).
"""
import logging
from dataclasses import dataclass
from typing import Optional

from strategy.base_strategy import BaseStrategy
from tradovate.models import Candle, TradeSignal

logger = logging.getLogger(__name__)

RR_RATIO = 0.33  # gano 0.33R, pierdo 1R


@dataclass
class _RangeState:
    range_candle: Candle
    range_low: float
    range_high: float
    locked_direction: Optional[str] = None  # "LONG" o "SHORT", o None si aun no se toma ningun extremo
    extreme_candle: Optional[Candle] = None
    engulfed: bool = False
    resolved: bool = False  # ya disparo operacion o ya se descarto


class MyStrategy(BaseStrategy):
    def __init__(self):
        self._range: Optional[_RangeState] = None

    # ------------------------------------------------------------------ #
    # M15: define/rota el rango activo
    # ------------------------------------------------------------------ #
    def on_m15_close(self, candle: Candle) -> None:
        self._range = _RangeState(
            range_candle=candle,
            range_low=candle.low,
            range_high=candle.high,
        )
        logger.info(
            "Nuevo rango M15 activo: low=%.2f high=%.2f (%s)",
            candle.low, candle.high, candle.close_time,
        )

    # ------------------------------------------------------------------ #
    # M1: corre el state machine de sweep + retorno + envolvente
    # ------------------------------------------------------------------ #
    def on_m1_close(self, candle: Candle) -> Optional[TradeSignal]:
        r = self._range
        if r is None or r.resolved:
            return None

        low_taken = candle.low < r.range_low
        high_taken = candle.high > r.range_high

        # (a) ambos extremos tomados simultaneamente sin direccion bloqueada
        #     -> descartar rango entero sin operar
        if low_taken and high_taken and r.locked_direction is None:
            logger.info("Rango descartado: una sola vela M1 tomo ambos extremos a la vez")
            r.resolved = True
            return None

        # (a') extremo contrario al ya bloqueado -> descartar rango entero
        if r.locked_direction == "LONG" and high_taken:
            logger.info("Rango descartado: se tomo el HIGH mientras esperabamos LONG")
            r.resolved = True
            return None
        if r.locked_direction == "SHORT" and low_taken:
            logger.info("Rango descartado: se tomo el LOW mientras esperabamos SHORT")
            r.resolved = True
            return None

        # (b) ¿esta vela actualiza el extremo objetivo? (mas profunda que la actual)
        is_new_extreme = False

        if low_taken and r.locked_direction in (None, "LONG"):
            if r.extreme_candle is None or candle.low < r.extreme_candle.low:
                r.extreme_candle = candle
                r.engulfed = False
                r.locked_direction = "LONG"
                is_new_extreme = True

        if high_taken and r.locked_direction in (None, "SHORT"):
            if r.extreme_candle is None or candle.high > r.extreme_candle.high:
                r.extreme_candle = candle
                r.engulfed = False
                r.locked_direction = "SHORT"
                is_new_extreme = True

        if is_new_extreme:
            # esta vela ES la vela_extremo; no puede ser a la vez su propia envolvente
            return None

        if r.extreme_candle is None:
            return None  # todavia no se ha tomado ningun extremo

        # (c) ¿esta vela envuelve (en cuerpo) a la vela_extremo actual?
        if self._engulfs(candle, r.extreme_candle, r.locked_direction):
            r.engulfed = True
            logger.info(
                "Vela M1 (%s) envuelve a la vela_extremo (%s). engullida=True",
                candle.close_time, r.extreme_candle.close_time,
            )

        # (d) ¿cierra dentro del rango y ya tenemos envolvente guardada?
        closes_inside = r.range_low <= candle.close <= r.range_high
        if closes_inside and r.engulfed:
            signal = self._build_signal(r, candle)
            r.resolved = True
            return signal

        return None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _engulfs(engulfing: Candle, engulfed: Candle, direction: str) -> bool:
        """Envolvente por CUERPOS unicamente (open/close), las mechas no
        se tienen en cuenta. Ademas se exige que el color de la vela
        envolvente sea coherente con la direccion esperada de reversion
        (alcista si esperamos LONG, bajista si esperamos SHORT) -- esto es
        un supuesto razonable no explicitado, confirmar si no es lo que
        se busca."""
        body_covers = (
            engulfing.body_low <= engulfed.body_low
            and engulfing.body_high >= engulfed.body_high
        )
        if not body_covers:
            return False

        if direction == "LONG":
            return engulfing.is_bullish
        return not engulfing.is_bullish

    @staticmethod
    def _build_signal(r: _RangeState, trigger_candle: Candle) -> Optional[TradeSignal]:
        entry = trigger_candle.close

        if r.locked_direction == "LONG":
            tp = r.range_high
            reward = tp - entry
        else:
            tp = r.range_low
            reward = entry - tp

        if reward <= 0:
            # el precio ya gapeo mas alla del TP antes de poder calcular el
            # SL; el setup quedo invalidado, no se opera.
            logger.warning(
                "Reward <= 0 al construir la señal (entry=%.2f tp=%.2f), se descarta",
                entry, tp,
            )
            return None

        risk = reward / RR_RATIO
        sl = entry - risk if r.locked_direction == "LONG" else entry + risk

        return TradeSignal(
            direction=r.locked_direction,
            entry_price=entry,
            take_profit=tp,
            stop_loss=sl,
            reason=(
                f"Sweep+retorno+envolvente sobre rango "
                f"[{r.range_low:.2f}, {r.range_high:.2f}]"
            ),
        )
