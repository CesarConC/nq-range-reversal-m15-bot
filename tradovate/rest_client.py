"""
Cliente REST generico para llamadas autenticadas a Tradovate.

La capa de ejecucion (execution/order_manager.py) debe usar esta clase
para hablar con la API; nada mas en el proyecto deberia llamar a httpx
directamente contra Tradovate.
"""
import logging

import httpx

from config.settings import TradovateConfig
from tradovate.auth import TradovateAuth

logger = logging.getLogger(__name__)


class TradovateRestClient:
    def __init__(self, config: TradovateConfig, auth: TradovateAuth):
        self.config = config
        self.auth = auth

    def _headers(self) -> dict:
        if not self.auth.session:
            raise RuntimeError("No hay sesion activa. Llama a auth.login() primero.")
        return {"Authorization": f"Bearer {self.auth.session.access_token}"}

    async def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.config.rest_base_url}{path}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, body: dict) -> dict:
        url = f"{self.config.rest_base_url}{path}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()

    async def find_contract_id(self, symbol: str) -> int:
        """Busca el contractId activo para un simbolo de contrato especifico,
        ej. 'MNQU6' (no sirve pasar solo 'MNQ', hay que indicar el mes/anio
        del contrato frontal vigente)."""
        results = await self.get("/contract/find", params={"name": symbol})
        if not results:
            raise ValueError(f"No se encontro contrato para {symbol}")
        if isinstance(results, list):
            return results[0]["id"]
        return results["id"]

    async def list_accounts(self) -> list[dict]:
        """Devuelve las cuentas asociadas al usuario autenticado (necesario
        para saber el accountId/accountSpec a usar al mandar ordenes)."""
        return await self.get("/account/list")

    async def get_chart_bars(self, symbol: str, timeframe_minutes: int, n_bars: int = 2) -> list[dict]:
        """Obtiene los ultimos n_bars de velas del timeframe indicado.

        Pide 2 barras por defecto porque algunos brokers incluyen la barra
        actual (incompleta) como ultimo elemento junto a la ultima completa.
        Devuelve la lista de bars tal como la devuelve Tradovate; cada elemento
        contiene al menos: timestamp, open, high, low, close.
        """
        body = {
            "symbol": symbol,
            "chartDescription": {
                "underlyingType": "MinuteBar",
                "elementSize": timeframe_minutes,
                "elementSizeUnit": "UnderlyingUnits",
                "withHistogram": False,
            },
            "timeRange": {
                "asMuchAsElements": n_bars,
            },
        }
        response = await self.post("/md/getChart", body)
        return response.get("bars", [])

    async def get_positions(self) -> list[dict]:
        """Devuelve todas las posiciones abiertas del usuario autenticado.

        Cada elemento incluye al menos:
          contractId  — ID numerico del contrato
          netPos      — contratos netos: positivo=LONG, negativo=SHORT, 0=plano
          netPrice    — precio medio de la posicion abierta
        """
        return await self.get("/position/list")

    async def get_fills(self) -> list[dict]:
        """Devuelve el historial de fills del usuario autenticado.

        Util para buscar el fill de cierre de un trade que se cerro en el
        broker sin que el bot recibiese el evento por WebSocket.
        Cada elemento incluye: orderId, contractId, price, qty, side, timestamp.
        """
        return await self.get("/fill/list")
