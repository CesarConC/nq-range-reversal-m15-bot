from datetime import datetime, timezone

from market_data.candle_aggregator import CandleAggregator
from tradovate.models import Quote


def q(last):
    return Quote(symbol="MNQ", last=last)


def test_aggregates_into_m1_candles():
    closed = []
    agg = CandleAggregator(1, on_candle_close=closed.append)

    base = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    agg.on_quote(q(100), base)
    agg.on_quote(q(105), base.replace(second=20))
    agg.on_quote(q(95), base.replace(second=40))
    agg.on_quote(q(102), base.replace(minute=1, second=0))  # dispara el cierre de la vela anterior

    assert len(closed) == 1
    c = closed[0]
    assert (c.open, c.high, c.low, c.close) == (100, 105, 95, 95)


def test_m15_bucket_alignment():
    closed = []
    agg = CandleAggregator(15, on_candle_close=closed.append)

    t1 = datetime(2026, 1, 1, 10, 7, 0, tzinfo=timezone.utc)   # cae en el bucket 10:00-10:15
    t2 = datetime(2026, 1, 1, 10, 16, 0, tzinfo=timezone.utc)  # ya es el siguiente bucket

    agg.on_quote(q(100), t1)
    agg.on_quote(q(110), t2)

    assert len(closed) == 1
    assert closed[0].open_time == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
