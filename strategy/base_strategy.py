"""
Clase base que toda estrategia debe implementar.

IMPORTANTE: este modulo no debe importar nada de tradovate/ws_client ni
rest_client. La estrategia solo conoce objetos Candle ya cerrados
(tradovate/models.py) y emite TradeSignal. Asi el mismo codigo sirve para
backtest y para vivo.
"""
from abc import ABC, abstractmethod
from typing import Optional

from tradovate.models import Candle, TradeSignal


class BaseStrategy(ABC):
    @abstractmethod
    def on_m15_close(self, candle: Candle) -> None:
        """Se llama cada vez que cierra una vela de M15. No devuelve señal;
        solo actualiza el estado interno (ej. el rango activo)."""
        raise NotImplementedError

    @abstractmethod
    def on_m1_close(self, candle: Candle) -> Optional[TradeSignal]:
        """Se llama cada vez que cierra una vela de M1. Devuelve una
        TradeSignal si se cumple la entrada, o None."""
        raise NotImplementedError

    def on_fill(self, fill: dict) -> None:
        """Opcional: reaccionar a la confirmacion de una ejecucion propia."""
        pass
