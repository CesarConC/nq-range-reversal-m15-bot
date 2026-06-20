"""Estructuras de datos compartidas entre las capas del bot."""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


@dataclass
class AuthSession:
    access_token: str
    md_access_token: Optional[str]
    expiration_time: str
    user_id: int
    has_market_data: bool
    has_funded: bool = False


@dataclass
class Quote:
    """Quote normalizado, ya independiente del formato crudo de Tradovate."""
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    raw: Optional[dict] = None


@dataclass
class Candle:
    """Vela OHLC ya cerrada, de un timeframe fijo (ej. 'M1', 'M15')."""
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open


@dataclass
class TradeSignal:
    """Señal de entrada ya con entry/TP/SL calculados, lista para risk_manager."""
    direction: Literal["LONG", "SHORT"]
    entry_price: float
    take_profit: float
    stop_loss: float
    reason: str = ""
