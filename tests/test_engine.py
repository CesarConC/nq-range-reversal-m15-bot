from datetime import datetime, timedelta, timezone

from core.engine import Engine
from strategy.my_strategy import MyStrategy
from tradovate.models import Quote


def q(price):
    return Quote(symbol="MNQ", last=price)


def test_pipeline_completo_quotes_a_senal():
    """Alimenta quotes tick a tick (como llegarian de Tradovate en vivo) y
    verifica que el engine arme las velas M15/M1 solo y dispare la señal,
    sin que el test tenga que construir ninguna Candle a mano.

    Timeline:
      10:00-10:15 (M15 #1) -> define el rango [21300, 21350]
      10:15-10:16 (M1)      -> toma el high (21355) -> vela_extremo
      10:16-10:17 (M1)      -> envuelve esa vela y cierra DENTRO del rango (21320) -> entra SHORT
    """
    signals = []
    engine = Engine(strategy=MyStrategy(), symbol="MNQ", on_signal=signals.append)

    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def tick(price, seconds):
        engine.on_quote(q(price), t0 + timedelta(seconds=seconds))

    # --- Forma el rango M15 #1: open=21320 high=21350 low=21300 close=21330 ---
    tick(21320, 0)      # 10:00:00 (open)
    tick(21350, 300)    # 10:05:00 (high)
    tick(21300, 600)    # 10:10:00 (low)
    tick(21330, 840)    # 10:14:00 (ultimo precio antes de cerrar)

    # --- Tick que cruza a la M15 #2 y a la vez cierra el rango M15 #1 ---
    tick(21355, 900)    # 10:15:00 -> cierra M15 #1 (rango fijado) y abre M1 "extremo"

    assert engine.strategy._range is not None
    assert engine.strategy._range.range_low == 21300
    assert engine.strategy._range.range_high == 21350

    # --- Cierra la vela M1 "extremo" (O=H=L=C=21355, toma el high) ---
    tick(21355, 960)    # 10:16:00 -> cierra esa M1 y abre la vela "confirmacion" (open=21355)

    # --- Construye la vela de confirmacion: abre en 21355, cierra en 21320 ---
    tick(21320, 990)    # 10:16:30 -> mismo minuto, fija el close de la vela de confirmacion

    # --- Tick que cierra la vela de confirmacion -> aqui deberia disparar la señal ---
    tick(21310, 1020)   # 10:17:00

    assert len(signals) == 1
    signal = signals[0]
    assert signal.direction == "SHORT"
    assert signal.entry_price == 21320
    assert signal.take_profit == 21300
