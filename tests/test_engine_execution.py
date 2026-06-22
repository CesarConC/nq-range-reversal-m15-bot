import asyncio
from datetime import datetime, timedelta, timezone

from core.engine import Engine
from strategy.my_strategy import MyStrategy
from risk.risk_manager import RiskManager, FundedAccountRules
from tradovate.models import Quote


def q(price):
    return Quote(symbol="MNQ", last=price)


class FakeOrderManager:
    def __init__(self):
        self.calls = []

    async def enter_from_signal(self, symbol, signal, qty):
        self.calls.append((symbol, signal, qty))
        return {"orderId": 1, "ok": True}


def _permissive_rules():
    return FundedAccountRules(
        initial_balance=50_000, max_drawdown=99_999,
        profit_target=99_999, consistency_pct=0.50, max_contracts=5,
        risk_pct=0.015, point_value=2.0,  # MNQ
    )


def _make_rm(rules=None):
    return RiskManager(rules or _permissive_rules())


def _feed_short_setup(engine, t0):
    """Reusa la misma secuencia de ticks validada en test_engine.py para
    producir exactamente una señal SHORT."""
    def tick(price, seconds):
        engine.on_quote(q(price), t0 + timedelta(seconds=seconds))

    tick(21320, 0)
    tick(21350, 300)
    tick(21300, 600)
    tick(21330, 840)
    tick(21355, 900)
    tick(21355, 960)
    tick(21320, 990)
    tick(21310, 1020)  # esta deberia disparar la señal


def test_engine_envia_la_orden_cuando_risk_aprueba():
    order_manager = FakeOrderManager()
    risk_manager = _make_rm()
    engine = Engine(
        strategy=MyStrategy(), symbol="MNQ",
        risk_manager=risk_manager, order_manager=order_manager,
    )

    async def run():
        _feed_short_setup(engine, datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc))
        await asyncio.sleep(0)  # deja correr la tarea programada con create_task

    asyncio.run(run())

    assert len(order_manager.calls) == 1
    symbol, signal, qty = order_manager.calls[0]
    assert symbol == "MNQ"
    assert signal.direction == "SHORT"
    # entry=21320 tp=21300 reward=20 risk=20/0.33≈60.6 sl≈21380.6
    # presupuesto=750, rpc=60.6*2=121.2 -> floor(750/121.2)=6, acotado a max_contracts=5
    assert qty == 5


def test_engine_no_envia_orden_si_risk_bloquea():
    order_manager = FakeOrderManager()
    risk_manager = _make_rm()
    risk_manager.daily_pnl = -100_000  # ya supero la perdida maxima del dia

    engine = Engine(
        strategy=MyStrategy(), symbol="MNQ",
        risk_manager=risk_manager, order_manager=order_manager,
    )

    async def run():
        _feed_short_setup(engine, datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc))
        await asyncio.sleep(0)

    asyncio.run(run())

    assert len(order_manager.calls) == 0


def test_on_fill_actualiza_estado_y_risk_manager():
    risk_manager = _make_rm()
    engine = Engine(strategy=MyStrategy(), symbol="MNQ", risk_manager=risk_manager)

    # abre 1 contrato short a 21320
    engine.on_fill({"action": "Sell", "qty": 1, "price": 21320})
    assert engine.state.position_qty == -1
    assert risk_manager.open_contracts == -1

    # lo cierra con ganancia (compra a 21300)
    engine.on_fill({"action": "Buy", "qty": 1, "price": 21300})
    assert engine.state.position_qty == 0
    assert engine.state.daily_realized_pnl == (21320 - 21300) * 1 * 2.0
    assert risk_manager.daily_pnl == (21320 - 21300) * 1 * 2.0
