"""
Cliente WebSocket de bajo nivel para el protocolo de Tradovate.

Tradovate usa un framing estilo SockJS encima del websocket. Cada frame
que LLEGA del servidor empieza con un caracter que indica el tipo:

    'o'        -> open frame, se manda justo al abrirse la sesion
    'h'        -> heartbeat del servidor (mantiene viva la conexion)
    'c[...]'   -> close frame
    'a[...]'   -> array JSON de mensajes (respuestas a requests o eventos push)

Los mensajes que el cliente ENVIA van como texto plano, SIN prefijo,
con el formato:

    "<endpoint>\\n<id>\\n<query>\\n<body>"

Ejemplo real: enviar "authorize\\n2\\n\\n<accessToken>" autoriza la sesion.

Las respuestas del servidor (dentro de un frame 'a') son strings JSON con
forma {"s": <status>, "i": <id>, "d": <data>} cuando responden a un
request nuestro, o {"e": <evento>, "d": <data>} cuando son eventos push
(ej. una actualizacion de quote en vivo).

Nota: este protocolo no esta documentado al 100% en un solo lugar publico.
Si algo no calza al probarlo, compara contra el repo oficial
tradovate/example-api-js (clase TradovateSocket), que implementa el mismo
protocolo en JavaScript.
"""
import asyncio
import json
import logging
from typing import Callable, Optional

import websockets

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 2.5


class TradovateWebSocket:
    def __init__(
        self,
        url: str,
        access_token: str,
        on_event: Optional[Callable[[dict], None]] = None,
    ):
        self.url = url
        self.access_token = access_token
        self.on_event = on_event  # callback para mensajes push (quotes, sync de usuario, etc.)

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connected_evt = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._closing = False

    async def connect(self):
        self._ws = await websockets.connect(self.url, ping_interval=None)
        self._tasks.append(asyncio.create_task(self._read_loop()))
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))

        await asyncio.wait_for(self._connected_evt.wait(), timeout=10)
        await self._authorize()

    async def close(self):
        self._closing = True
        for t in self._tasks:
            t.cancel()
        if self._ws:
            await self._ws.close()

    async def _authorize(self):
        await self.request("authorize", body=self.access_token)
        logger.info("WebSocket autorizado correctamente (%s)", self.url)

    async def request(self, endpoint: str, query: str = "", body=None) -> dict:
        """Envia un request al socket y espera la respuesta correlacionada por id.
        body puede ser un string (ej. el token al autorizar) o un dict (se
        serializa a JSON automaticamente, ej. {"symbol": "MNQU6"})."""
        self._request_id += 1
        req_id = self._request_id

        if body is None:
            body_str = ""
        elif isinstance(body, str):
            body_str = body
        else:
            body_str = json.dumps(body)

        frame = f"{endpoint}\n{req_id}\n{query}\n{body_str}"

        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut

        await self._ws.send(frame)

        try:
            return await asyncio.wait_for(fut, timeout=10)
        finally:
            self._pending.pop(req_id, None)

    async def _heartbeat_loop(self):
        """Tradovate requiere que el cliente tambien mande heartbeats; si no,
        la conexion se cae silenciosamente tras un rato (reportado en su foro)."""
        try:
            while not self._closing:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                await self._ws.send("[]")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Heartbeat fallo, la conexion probablemente se cayo")

    async def _read_loop(self):
        try:
            async for raw in self._ws:
                self._handle_frame(raw)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("El read_loop del websocket termino con error")

    def _handle_frame(self, raw: str):
        if not raw:
            return

        frame_type, payload = raw[0], raw[1:]

        if frame_type == "o":
            self._connected_evt.set()

        elif frame_type == "h":
            pass  # heartbeat del servidor; no requiere accion explicita

        elif frame_type == "c":
            logger.warning("El servidor cerro la conexion: %s", payload)

        elif frame_type == "a":
            try:
                messages = json.loads(payload)
            except json.JSONDecodeError:
                logger.error("Frame 'a' invalido, no se pudo parsear: %s", payload[:200])
                return
            for raw_msg in messages:
                try:
                    msg = json.loads(raw_msg) if isinstance(raw_msg, str) else raw_msg
                except json.JSONDecodeError:
                    logger.error("Mensaje interno invalido: %s", raw_msg)
                    continue
                self._dispatch_message(msg)

        else:
            logger.debug("Frame de tipo desconocido: %s", raw[:100])

    def _dispatch_message(self, msg: dict):
        if "i" in msg:
            # Es la respuesta a un request que nosotros enviamos.
            req_id = msg["i"]
            fut = self._pending.get(req_id)
            if not fut or fut.done():
                return
            if msg.get("s") == 200:
                fut.set_result(msg.get("d"))
            else:
                fut.set_exception(RuntimeError(f"Request {req_id} fallo: {msg}"))

        elif "e" in msg:
            # Es un evento push (quote en vivo, fill, sync de cuenta, etc.)
            if self.on_event:
                self.on_event(msg)

        else:
            logger.debug("Mensaje sin 'i' ni 'e', se ignora: %s", msg)
