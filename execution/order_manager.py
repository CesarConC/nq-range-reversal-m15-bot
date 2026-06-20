"""
Traduce señales de la estrategia (entry + TP + SL) en ordenes reales
contra Tradovate.

IMPORTANTE - nivel de confianza de cada pieza:

  - account discovery (/account/list) y place_market_order
    (/order/placeorder): confirmado contra documentacion oficial y
    ejemplos del foro de Tradovate.

  - place_bracket_order (/order/placeoso) y place_oco_exit
    (/order/placeoco): el endpoint existe y la idea (entrada + TP/SL
    adjuntos) es correcta, pero el foro oficial de Tradovate tiene
    MULTIPLES reportes de desarrolladores con errores 404 o
    comportamiento inconsistente en estos endpoints segun el tipo de
    cuenta. Los nombres exactos de los campos del body que uso aqui
    (bracket1/bracket2, order1/order2) son mi mejor estimacion en base
    a esos hilos, NO estan 100% verificados. PRUEBA ESTO A FONDO EN
    DEMO antes de confiar en que el TP/SL se coloca de verdad.

  - Si placeoso/placeoco fallan para tu cuenta, el plan B (mas lento
    pero mas fiable y bien documentado) es:
      1. place_market_order() para la entrada
      2. esperar la confirmacion del fill (requiere el websocket de
         datos de usuario, que todavia no existe en este proyecto)
      3. place_oco_exit() para mandar TP/SL ya con la posicion abierta
"""
import logging
from typing import Optional

from tradovate.rest_client import TradovateRestClient

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(self, rest_client: TradovateRestClient, device_id: str):
        self.rest_client = rest_client
        self.device_id = device_id
        self.account_id: Optional[int] = None
        self.account_spec: Optional[str] = None

    async def initialize(self) -> None:
        """Descubre automaticamente la cuenta de trading asociada al usuario
        autenticado. Hay que llamarlo una vez, antes de mandar cualquier orden."""
        accounts = await self.rest_client.list_accounts()
        if not accounts:
            raise RuntimeError(
                "El usuario autenticado no tiene ninguna cuenta de trading asociada."
            )

        # TODO: si tienes varias cuentas (ej. varias cuentas fondeadas a la
        # vez), aqui hay que elegir la correcta en vez de tomar la primera.
        account = accounts[0]
        self.account_id = account["id"]
        self.account_spec = account["name"]
        logger.info(
            "OrderManager inicializado. Cuenta=%s (accountId=%s)",
            self.account_spec, self.account_id,
        )

    def _ensure_ready(self) -> None:
        if self.account_id is None:
            raise RuntimeError("OrderManager no inicializado. Llama a initialize() primero.")

    # ------------------------------------------------------------------ #
    # Entrada simple
    # ------------------------------------------------------------------ #
    async def place_market_order(self, symbol: str, action: str, qty: int) -> dict:
        """action: 'Buy' o 'Sell'. No lleva TP/SL adjunto."""
        self._ensure_ready()
        body = {
            "accountSpec": self.account_spec,
            "accountId": self.account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": qty,
            "orderType": "Market",
            "isAutomated": True,
            "deviceId": self.device_id,
        }
        response = await self.rest_client.post("/order/placeorder", body)
        logger.info("Orden de entrada enviada: action=%s qty=%s -> %s", action, qty, response)
        return response

    # ------------------------------------------------------------------ #
    # Entrada + TP/SL adjuntos (bracket OSO) -- ver caveats arriba
    # ------------------------------------------------------------------ #
    async def enter_from_signal(self, symbol: str, signal, qty: int) -> dict:
        """Conveniencia para el engine: traduce una TradeSignal
        (direction/take_profit/stop_loss) directo a place_bracket_order."""
        action = "Buy" if signal.direction == "LONG" else "Sell"
        return await self.place_bracket_order(
            symbol=symbol,
            action=action,
            qty=qty,
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss,
        )

    async def place_bracket_order(
        self, symbol: str, action: str, qty: int, take_profit: float, stop_loss: float
    ) -> dict:
        self._ensure_ready()
        exit_action = "Sell" if action == "Buy" else "Buy"

        body = {
            "accountSpec": self.account_spec,
            "accountId": self.account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": qty,
            "orderType": "Market",
            "isAutomated": True,
            "deviceId": self.device_id,
            "bracket1": {"action": exit_action, "orderType": "Limit", "price": take_profit},
            "bracket2": {"action": exit_action, "orderType": "Stop", "stopPrice": stop_loss},
        }
        response = await self.rest_client.post("/order/placeoso", body)
        logger.info(
            "Bracket OSO enviado: %s qty=%s tp=%.2f sl=%.2f -> %s",
            action, qty, take_profit, stop_loss, response,
        )
        return response

    # ------------------------------------------------------------------ #
    # Plan B: TP/SL como OCO independiente sobre una posicion ya abierta
    # ------------------------------------------------------------------ #
    async def place_oco_exit(
        self, symbol: str, exit_action: str, qty: int, take_profit: float, stop_loss: float
    ) -> dict:
        self._ensure_ready()
        body = {
            "accountSpec": self.account_spec,
            "accountId": self.account_id,
            "action": exit_action,
            "symbol": symbol,
            "orderQty": qty,
            "isAutomated": True,
            "deviceId": self.device_id,
            "order1": {"orderType": "Limit", "price": take_profit},
            "order2": {"orderType": "Stop", "stopPrice": stop_loss},
        }
        response = await self.rest_client.post("/order/placeoco", body)
        logger.info("OCO de salida enviado: %s qty=%s -> %s", exit_action, qty, response)
        return response

    # ------------------------------------------------------------------ #
    # Gestion de ordenes existentes
    # ------------------------------------------------------------------ #
    async def cancel_order(self, order_id: int) -> dict:
        self._ensure_ready()
        return await self.rest_client.post("/order/cancelorder", {"orderId": order_id})

    async def list_open_orders(self) -> list[dict]:
        """Polling REST de ordenes abiertas. Es un fallback -- lo ideal
        es trackear fills en tiempo real via el websocket de usuario
        (todavia no implementado en este proyecto)."""
        self._ensure_ready()
        orders = await self.rest_client.get("/order/list")
        return [o for o in orders if o.get("accountId") == self.account_id]
