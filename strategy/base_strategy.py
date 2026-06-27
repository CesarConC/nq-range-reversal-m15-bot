"""
Clase base que toda estrategia debe implementar.

IMPORTANTE: este modulo no debe importar nada de tradovate/ws_client ni
rest_client. La estrategia solo conoce objetos Candle ya cerrados
(tradovate/models.py) y emite TradeSignal. Asi el mismo codigo sirve para
backtest y para vivo.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional

from tradovate.models import Candle, TradeSignal


class BaseStrategy(ABC):
    # Cada subclase DEBE declarar estos cuatro atributos de clase.
    risk_pct: float    # fraccion del balance inicial a arriesgar por trade (ej. 0.01 = 1%)
    rr_ratio: float    # multiplicador TP/riesgo (ej. 1.0 -> TP = 1 * riesgo; 0.33 -> TP = 0.33 * riesgo)
    symbol: str        # simbolo del contrato a operar (ej. "MNQ")
    point_value: float # USD por punto del contrato (MNQ=2.0, NQ=20.0)

    async def seed_bars(self, engine: Any, rest_client: Any, symbol: str) -> None:
        """Pre-carga el estado historico en el engine antes de conectar el WebSocket.

        Estrategias que usan aggregators con estado (M15, M5...) deben
        sobreescribir este metodo para obtener la vela parcial en curso via
        REST e inyectarla en engine.seed_m15_bar / seed_m5_bar.
        Por defecto no hace nada (valido para estrategias stateless).
        """

    def on_m15_close(self, candle: Candle) -> None:
        """Opcional: se llama cada vez que cierra una vela de M15."""
        pass

    @abstractmethod
    def on_m1_close(self, candle: Candle) -> Optional[TradeSignal]:
        """Se llama cada vez que cierra una vela de M1. Devuelve una
        TradeSignal si se cumple la entrada, o None."""
        raise NotImplementedError

    def on_m5_close(self, candle: Candle) -> Optional[TradeSignal]:
        """Opcional: se llama cada vez que cierra una vela de M5.
        Devuelve TradeSignal si la estrategia opera en M5, o None."""
        return None

    def on_fill(self, fill: dict) -> None:
        """Opcional: reaccionar a la confirmacion de una ejecucion propia."""
        pass
