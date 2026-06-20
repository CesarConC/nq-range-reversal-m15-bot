from core.state import AccountState


def test_abre_posicion_long():
    state = AccountState()
    state.apply_fill("Buy", 2, 100, multiplier=2.0)
    assert state.position_qty == 2
    assert state.avg_entry_price == 100
    assert state.daily_realized_pnl == 0


def test_aumenta_posicion_recalcula_precio_medio():
    state = AccountState()
    state.apply_fill("Buy", 2, 100, multiplier=2.0)
    state.apply_fill("Buy", 1, 106, multiplier=2.0)
    assert state.position_qty == 3
    assert state.avg_entry_price == 102  # (100*2 + 106*1) / 3


def test_cierre_parcial_calcula_pnl_realizado():
    state = AccountState()
    state.apply_fill("Buy", 3, 102, multiplier=2.0)  # posicion long de 3 a 102
    state.apply_fill("Sell", 1, 110, multiplier=2.0)  # cierra 1 contrato con ganancia

    assert state.position_qty == 2
    assert state.avg_entry_price == 102  # no cambia, sigue quedando posicion
    assert state.daily_realized_pnl == (110 - 102) * 1 * 2.0  # 16.0


def test_fill_que_revierte_la_posicion():
    state = AccountState()
    state.apply_fill("Buy", 2, 102, multiplier=2.0)
    state.apply_fill("Sell", 5, 90, multiplier=2.0)  # cierra los 2 y abre 3 short

    assert state.position_qty == -3
    assert state.avg_entry_price == 90
    assert state.daily_realized_pnl == (90 - 102) * 2 * 2.0  # -48.0


def test_posicion_short_pnl_realizado():
    state = AccountState()
    state.apply_fill("Sell", 2, 21350, multiplier=2.0)  # short a 21350
    state.apply_fill("Buy", 2, 21300, multiplier=2.0)   # cierra con ganancia (bajo)

    assert state.position_qty == 0
    assert state.daily_realized_pnl == (21350 - 21300) * 2 * 2.0  # 200.0
