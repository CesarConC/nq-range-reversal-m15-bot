import asyncio

from account_data.user_socket import UserDataSocket


class FakeTradovateWebSocket:
    """Sustituye a TradovateWebSocket para testear UserDataSocket sin
    conectar de verdad. Solo necesita responder a request('user/syncrequest')."""

    def __init__(self, snapshot):
        self._snapshot = snapshot

    async def connect(self):
        pass

    async def request(self, endpoint, query="", body=None):
        assert endpoint == "user/syncrequest"
        return self._snapshot


def make_socket(snapshot=None):
    snapshot = snapshot or {"orders": [], "positions": [], "fills": []}
    orders_log, fills_log, positions_log = [], [], []

    socket = UserDataSocket(
        user_ws_url="wss://fake",
        access_token="token",
        on_order_update=orders_log.append,
        on_fill=fills_log.append,
        on_position_update=positions_log.append,
    )
    socket.ws = FakeTradovateWebSocket(snapshot)  # sustituye el ws real
    return socket, orders_log, fills_log, positions_log


def test_sync_carga_la_foto_inicial():
    snapshot = {
        "orders": [{"id": 1, "ordStatus": "Working"}],
        "positions": [{"id": 10, "netPos": 1}],
        "fills": [{"id": 100, "qty": 1, "price": 21300}],
    }
    socket, *_ = make_socket(snapshot)

    asyncio.run(socket.sync())

    assert socket.orders[1]["ordStatus"] == "Working"
    assert socket.positions[10]["netPos"] == 1
    assert socket.fills[100]["price"] == 21300


def test_evento_de_fill_dispara_callback_y_actualiza_estado():
    socket, _, fills_log, _ = make_socket()

    socket._handle_event({
        "e": "props",
        "d": {
            "entityType": "fill",
            "eventType": "Created",
            "entity": {"id": 555, "qty": 1, "price": 21320, "orderId": 1},
        },
    })

    assert 555 in socket.fills
    assert len(fills_log) == 1
    assert fills_log[0]["price"] == 21320


def test_evento_de_orden_actualiza_estado_y_dispara_callback():
    socket, orders_log, _, _ = make_socket()

    socket._handle_event({
        "e": "props",
        "d": {
            "entityType": "order",
            "eventType": "Updated",
            "entity": {"id": 1, "ordStatus": "Filled"},
        },
    })

    assert socket.orders[1]["ordStatus"] == "Filled"
    assert orders_log[0]["ordStatus"] == "Filled"


def test_evento_de_posicion_dispara_callback():
    socket, _, _, positions_log = make_socket()

    socket._handle_event({
        "e": "props",
        "d": {
            "entityType": "position",
            "eventType": "Updated",
            "entity": {"id": 10, "netPos": -1},
        },
    })

    assert socket.positions[10]["netPos"] == -1
    assert positions_log[0]["netPos"] == -1


def test_eventos_no_reconocidos_se_ignoran_sin_explotar():
    socket, orders_log, fills_log, positions_log = make_socket()

    socket._handle_event({"h": True})  # heartbeat, sin 'e'
    socket._handle_event({"e": "md", "d": {}})  # evento de otro dominio
    socket._handle_event({"e": "props", "d": {"entityType": "order", "entity": {}}})  # sin 'id'

    assert orders_log == [] and fills_log == [] and positions_log == []
