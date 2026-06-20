"""
Backtester: corre la misma clase de estrategia (strategy/my_strategy.py)
contra datos historicos en vez de datos en vivo.

Como la estrategia solo recibe objetos Quote (no sabe nada de Tradovate
ni de websockets), este modulo solo necesita generar esos Quotes desde
un CSV/historico y llamar a strategy.on_quote() en loop.

TODO: implementar el loop principal y el calculo de metricas
(win rate, drawdown maximo, expectativa por trade, etc.)
"""
from tradovate.models import Quote


class Backtester:
    def __init__(self, strategy):
        self.strategy = strategy
        self.trades: list[dict] = []

    def run(self, quotes: list[Quote]):
        for quote in quotes:
            signal = self.strategy.on_quote(quote)
            if signal in ("BUY", "SELL", "CLOSE"):
                # TODO: simular la ejecucion y registrar el trade
                self.trades.append({"quote": quote, "signal": signal})
        return self.trades
