"""
Capa de market data: conecta al socket de market data de Tradovate, se
suscribe a quotes de un simbolo y emite objetos Quote ya normalizados.

La estrategia (strategy/) nunca deberia ver el JSON crudo de Tradovate,
solo objetos Quote de tradovate/models.py. Esto es lo que permite
reusar la misma estrategia en backtest y en vivo.
"""
import logging
from typing import Callable

from tradovate.ws_client import TradovateWebSocket
from tradovate.models import Quote

logger = logging.getLogger(__name__)


class MarketDataFeed:
    def __init__(self, md_ws_url: str, md_access_token: str, on_quote: Callable[[Quote], None]):
        self.on_quote = on_quote
        self.ws = TradovateWebSocket(md_ws_url, md_access_token, on_event=self._handle_event)

    async def connect(self):
        await self.ws.connect()

    async def subscribe(self, symbol: str):
        """symbol debe ser el contrato especifico, ej. 'MNQU6', no 'MNQ' generico."""
        await self.ws.request("md/subscribequote", body={"symbol": symbol})
        logger.info("Suscrito a quotes de %s", symbol)

    def _handle_event(self, msg: dict):
        if msg.get("e") != "md":
            return

        data = msg.get("d", {})
        for q in data.get("quotes", []):
            entries = q.get("entries", {})
            quote = Quote(
                symbol=q.get("contractId"),
                bid=_entry_price(entries, "Bid"),
                ask=_entry_price(entries, "Offer"),
                last=_entry_price(entries, "Trade"),
                raw=q,
            )
            self.on_quote(quote)


def _entry_price(entries: dict, key: str):
    entry = entries.get(key)
    return entry.get("price") if entry else None
