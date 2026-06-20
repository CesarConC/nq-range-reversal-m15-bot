"""
Socket de datos de USUARIO en tiempo real: ordenes, posiciones y fills.

Esto es distinto del socket de market data (market_data/feed.py):
  - Se conecta a config.user_ws_url (wss://demo|live.tradovateapi.com/...),
    NO a md.tradovateapi.com.
  - Se autoriza con el accessToken normal, NO con el mdAccessToken.

Flujo:
  1. Al conectar, se manda 'user/syncrequest'. La RESPUESTA a ese request
     trae una foto inicial completa: arrays de ordenes, posiciones y
     fills existentes en la cuenta.
  2. A partir de ahi, cada cambio (orden nueva, fill, cancelacion, cambio
     de estado de una orden, etc.) llega como un evento PUSH separado,
     con forma {"e": "props", "d": {"entityType": ..., "entity": {...},
     "eventType": "Created"|"Updated"|"Deleted"}}.

NIVEL DE CONFIANZA: este formato (snapshot inicial por arrays + eventos
incrementales "props" con entityType/entity/eventType) coincide con lo
documentado y discutido en la comunidad oficial de Tradovate, pero no lo
he podido verificar contra una cuenta real. Corre esto en demo con
logging.DEBUG activado la primera vez y compara los mensajes crudos
contra lo que se espera aqui -- si algun nombre de campo no calza, es
facil ajustar _handle_event().
"""
import logging
from typing import Callable, Optional

from tradovate.ws_client import TradovateWebSocket

logger = logging.getLogger(__name__)


class UserDataSocket:
    def __init__(
        self,
        user_ws_url: str,
        access_token: str,
        on_order_update: Optional[Callable[[dict], None]] = None,
        on_fill: Optional[Callable[[dict], None]] = None,
        on_position_update: Optional[Callable[[dict], None]] = None,
    ):
        self.on_order_update = on_order_update
        self.on_fill = on_fill
        self.on_position_update = on_position_update

        self.ws = TradovateWebSocket(user_ws_url, access_token, on_event=self._handle_event)

        # Estado en memoria: id -> entidad cruda de Tradovate. Se llena con
        # la foto inicial de sync() y se mantiene al dia con cada evento push.
        self.orders: dict[int, dict] = {}
        self.positions: dict[int, dict] = {}
        self.fills: dict[int, dict] = {}

    async def connect(self) -> None:
        await self.ws.connect()

    async def sync(self) -> dict:
        """Manda user/syncrequest, guarda la foto inicial en memoria y la
        devuelve. Llamar una vez justo despues de connect()."""
        snapshot = await self.ws.request("user/syncrequest")

        for order in snapshot.get("orders", []):
            self.orders[order["id"]] = order
        for position in snapshot.get("positions", []):
            self.positions[position["id"]] = position
        for fill in snapshot.get("fills", []):
            self.fills[fill["id"]] = fill

        logger.info(
            "Sync inicial de usuario: %d ordenes, %d posiciones, %d fills",
            len(self.orders), len(self.positions), len(self.fills),
        )
        return snapshot

    # ------------------------------------------------------------------ #
    # Eventos push (incrementales)
    # ------------------------------------------------------------------ #
    def _handle_event(self, msg: dict) -> None:
        if msg.get("e") != "props":
            logger.debug("Evento de usuario no reconocido (se ignora): %s", msg)
            return

        data = msg.get("d", {})
        entity_type = data.get("entityType")
        entity = data.get("entity")
        event_type = data.get("eventType")

        if entity is None or entity_type is None or "id" not in entity:
            logger.debug("Evento 'props' con forma inesperada: %s", data)
            return

        if entity_type == "order":
            self.orders[entity["id"]] = entity
            logger.info(
                "Orden %s (id=%s) status=%s",
                event_type, entity.get("id"), entity.get("ordStatus"),
            )
            if self.on_order_update:
                self.on_order_update(entity)

        elif entity_type == "position":
            self.positions[entity["id"]] = entity
            if self.on_position_update:
                self.on_position_update(entity)

        elif entity_type == "fill":
            self.fills[entity["id"]] = entity

            # Algunos fills no traen 'action' directamente; si tenemos la
            # orden padre ya sincronizada, la usamos para completarlo.
            if "action" not in entity and entity.get("orderId") in self.orders:
                entity = {**entity, "action": self.orders[entity["orderId"]].get("action")}

            logger.info(
                "Fill %s: id=%s qty=%s price=%s orderId=%s",
                event_type, entity.get("id"), entity.get("qty"),
                entity.get("price"), entity.get("orderId"),
            )
            if self.on_fill:
                self.on_fill(entity)

        else:
            logger.debug("Tipo de entidad sin manejar todavia: %s", entity_type)
