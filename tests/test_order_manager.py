import asyncio

from execution.order_manager import OrderManager


class FakeRestClient:
    """Simula TradovateRestClient sin llamar a la API real, para poder
    testear OrderManager de forma aislada."""

    def __init__(self):
        self.posts = []  # guarda (path, body) de cada llamada para inspeccionar en los tests

    async def list_accounts(self):
        return [{"id": 999, "name": "DEMO12345"}]

    async def post(self, path, body):
        self.posts.append((path, body))
        return {"orderId": 111, "ok": True}

    async def get(self, path, params=None):
        return [{"id": 111, "accountId": 999, "ordStatus": "Working"}]


def run(coro):
    return asyncio.run(coro)


def test_initialize_descubre_la_cuenta():
    om = OrderManager(FakeRestClient(), device_id="bot-1")
    run(om.initialize())
    assert om.account_id == 999
    assert om.account_spec == "DEMO12345"


def test_no_se_puede_operar_sin_inicializar():
    om = OrderManager(FakeRestClient(), device_id="bot-1")
    try:
        run(om.place_market_order("MNQU6", "Buy", 1))
        assert False, "deberia haber lanzado RuntimeError"
    except RuntimeError:
        pass


def test_place_market_order_manda_el_body_correcto():
    rest = FakeRestClient()
    om = OrderManager(rest, device_id="bot-1")
    run(om.initialize())

    run(om.place_market_order("MNQU6", "Buy", 1))

    path, body = rest.posts[-1]
    assert path == "/order/placeorder"
    assert body["accountId"] == 999
    assert body["action"] == "Buy"
    assert body["orderType"] == "Market"
    assert body["isAutomated"] is True


def test_place_bracket_order_calcula_la_salida_contraria():
    rest = FakeRestClient()
    om = OrderManager(rest, device_id="bot-1")
    run(om.initialize())

    run(om.place_bracket_order("MNQU6", "Sell", 1, take_profit=21300, stop_loss=21450))

    path, body = rest.posts[-1]
    assert path == "/order/placeoso"
    assert body["action"] == "Sell"
    assert body["bracket1"]["action"] == "Buy"   # SHORT -> sale comprando
    assert body["bracket1"]["price"] == 21300
    assert body["bracket2"]["stopPrice"] == 21450


def test_list_open_orders_filtra_por_cuenta():
    rest = FakeRestClient()
    om = OrderManager(rest, device_id="bot-1")
    run(om.initialize())

    orders = run(om.list_open_orders())
    assert len(orders) == 1
    assert orders[0]["accountId"] == 999
