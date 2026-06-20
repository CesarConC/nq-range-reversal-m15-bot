"""
Agrega quotes tick a tick en velas OHLC de un timeframe fijo.

Usa el precio "last" del quote; si no hay trade reciente, usa el midpoint
de bid/ask como aproximacion. Emite una Candle ya cerrada via el callback
on_candle_close cada vez que se completa un periodo (M1 o M15).

LIMITACION CONOCIDA: el cierre de una vela solo se detecta al llegar el
primer tick del periodo siguiente. Si el mercado esta muy tranquilo y no
llega ningun tick justo despues del cierre del periodo, la deteccion del
cierre se retrasa hasta el siguiente tick real. Para MNQ en horario activo
esto no suele ser un problema, pero si se necesita precision exacta al
segundo habria que añadir un timer en paralelo que fuerce el cierre.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from tradovate.models import Candle, Quote

logger = logging.getLogger(__name__)


class CandleAggregator:
    def __init__(self, timeframe_minutes: int, on_candle_close: Callable[[Candle], None]):
        self.timeframe_minutes = timeframe_minutes
        self.timeframe = timedelta(minutes=timeframe_minutes)
        self.on_candle_close = on_candle_close
        self._label = f"M{timeframe_minutes}"

        self._bucket_start: Optional[datetime] = None
        self._open: Optional[float] = None
        self._high: Optional[float] = None
        self._low: Optional[float] = None
        self._close: Optional[float] = None

    def on_quote(self, quote: Quote, timestamp: Optional[datetime] = None) -> None:
        price = quote.last
        if price is None and quote.bid is not None and quote.ask is not None:
            price = (quote.bid + quote.ask) / 2
        if price is None:
            return

        ts = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
        bucket_start = self._bucket_start_for(ts)

        if self._bucket_start is None:
            self._start_bucket(bucket_start, price)
            return

        if bucket_start != self._bucket_start:
            self._close_bucket()
            self._start_bucket(bucket_start, price)
            return

        self._high = max(self._high, price)
        self._low = min(self._low, price)
        self._close = price

    def _bucket_start_for(self, ts: datetime) -> datetime:
        minutes = self.timeframe_minutes
        epoch_minutes = ts.timestamp() / 60
        bucket_index = int(epoch_minutes // minutes)
        return datetime.fromtimestamp(bucket_index * minutes * 60, tz=timezone.utc)

    def _start_bucket(self, bucket_start: datetime, price: float) -> None:
        self._bucket_start = bucket_start
        self._open = self._high = self._low = self._close = price

    def _close_bucket(self) -> None:
        candle = Candle(
            timeframe=self._label,
            open_time=self._bucket_start,
            close_time=self._bucket_start + self.timeframe,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
        )
        logger.debug(
            "Vela %s cerrada: O=%s H=%s L=%s C=%s",
            self._label, candle.open, candle.high, candle.low, candle.close,
        )
        self.on_candle_close(candle)
