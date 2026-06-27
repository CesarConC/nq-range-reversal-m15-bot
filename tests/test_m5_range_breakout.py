from datetime import datetime, timedelta, timezone

import pytest

from strategy.m5_range_breakout import M5RangeBreakout
from tradovate.models import Candle


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

BASE = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def m1(o, h, l, c, minutes_offset=0):
    start = BASE + timedelta(minutes=minutes_offset)
    return Candle(
        timeframe="M1",
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open=o, high=h, low=l, close=c,
    )


def m5(o, h, l, c, minutes_offset=0):
    start = BASE + timedelta(minutes=minutes_offset)
    return Candle(
        timeframe="M5",
        open_time=start,
        close_time=start + timedelta(minutes=5),
        open=o, high=h, low=l, close=c,
    )


def strat_with_range(low=21300.0, high=21350.0):
    """Crea la estrategia con un rango M5 ya activo [low, high]."""
    s = M5RangeBreakout()
    s.on_m5_close(m5(o=(low + high) / 2, h=high, l=low, c=(low + high) / 2))
    return s


# ------------------------------------------------------------------ #
# Sin rango todavia
# ------------------------------------------------------------------ #

def test_sin_rango_m1_devuelve_none():
    s = M5RangeBreakout()
    assert s.on_m1_close(m1(21320, 21325, 21315, 21320)) is None


def test_on_m5_close_siempre_devuelve_none():
    s = M5RangeBreakout()
    assert s.on_m5_close(m5(21320, 21350, 21300, 21330)) is None


def test_on_m15_close_no_altera_estado():
    s = strat_with_range(21300, 21350)
    s.on_m15_close(m1(21320, 21325, 21315, 21320))
    assert s._range_high == 21350.0
    assert len(s._m1_seq) == 0


# ------------------------------------------------------------------ #
# Rango M5 y seguimiento
# ------------------------------------------------------------------ #

def test_m5_fija_rango_correctamente():
    s = M5RangeBreakout()
    s.on_m5_close(m5(21325, 21350, 21300, 21330))
    assert s._range_high == 21350.0
    assert s._range_low == 21300.0


def test_un_m1_dentro_no_dispara():
    s = strat_with_range(21300, 21350)
    assert s.on_m1_close(m1(21320, 21330, 21315, 21325, minutes_offset=1)) is None
    assert len(s._m1_seq) == 1


def test_dos_m1_dentro_no_disparan():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21320, minutes_offset=1))
    assert s.on_m1_close(m1(21318, 21328, 21310, 21315, minutes_offset=2)) is None
    assert len(s._m1_seq) == 2


# ------------------------------------------------------------------ #
# Señal LONG: 2 dentro + 1 cierra encima del rango
# ------------------------------------------------------------------ #

def test_long_signal_direccion_y_entry():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21325, minutes_offset=1))
    s.on_m1_close(m1(21320, 21328, 21312, 21318, minutes_offset=2))
    signal = s.on_m1_close(m1(21345, 21360, 21344, 21355, minutes_offset=3))

    assert signal is not None
    assert signal.direction == "LONG"
    assert signal.entry_price == 21355.0


def test_long_sl_en_low_primera_vela_secuencia():
    """El SL va en el minimo de la 1a vela M1 de la secuencia."""
    s = strat_with_range(21300, 21350)
    c1 = m1(21320, 21330, 21310, 21325, minutes_offset=1)   # low = 21310
    c2 = m1(21318, 21328, 21318, 21320, minutes_offset=2)
    s.on_m1_close(c1)
    s.on_m1_close(c2)
    signal = s.on_m1_close(m1(21348, 21358, 21347, 21355, minutes_offset=3))

    assert signal.stop_loss == 21310.0


def test_long_tp_calculado_con_rr_ratio():
    s = strat_with_range(21300, 21350)
    c1 = m1(21320, 21330, 21310, 21325, minutes_offset=1)   # low = 21310
    c2 = m1(21318, 21328, 21315, 21320, minutes_offset=2)
    s.on_m1_close(c1)
    s.on_m1_close(c2)
    signal = s.on_m1_close(m1(21348, 21360, 21347, 21355, minutes_offset=3))  # entry = 21355

    risk = 21355.0 - 21310.0   # 45 pts
    expected_tp = 21355.0 + risk * M5RangeBreakout.rr_ratio
    assert signal.take_profit == pytest.approx(expected_tp)


# ------------------------------------------------------------------ #
# Señal SHORT: 2 dentro + 1 cierra debajo del rango
# ------------------------------------------------------------------ #

def test_short_signal_direccion_y_entry():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21325, minutes_offset=1))
    s.on_m1_close(m1(21320, 21328, 21312, 21318, minutes_offset=2))
    signal = s.on_m1_close(m1(21305, 21306, 21290, 21295, minutes_offset=3))

    assert signal is not None
    assert signal.direction == "SHORT"
    assert signal.entry_price == 21295.0


def test_short_sl_en_high_primera_vela_secuencia():
    """El SL va en el maximo de la 1a vela M1 de la secuencia."""
    s = strat_with_range(21300, 21350)
    c1 = m1(21320, 21332, 21315, 21325, minutes_offset=1)   # high = 21332
    c2 = m1(21318, 21328, 21312, 21318, minutes_offset=2)
    s.on_m1_close(c1)
    s.on_m1_close(c2)
    signal = s.on_m1_close(m1(21305, 21306, 21290, 21295, minutes_offset=3))

    assert signal.stop_loss == 21332.0


def test_short_tp_calculado_con_rr_ratio():
    s = strat_with_range(21300, 21350)
    c1 = m1(21320, 21332, 21315, 21325, minutes_offset=1)   # high = 21332
    c2 = m1(21318, 21328, 21312, 21318, minutes_offset=2)
    s.on_m1_close(c1)
    s.on_m1_close(c2)
    signal = s.on_m1_close(m1(21305, 21306, 21290, 21295, minutes_offset=3))   # entry = 21295

    risk = 21332.0 - 21295.0   # 37 pts
    expected_tp = 21295.0 - risk * M5RangeBreakout.rr_ratio
    assert signal.take_profit == pytest.approx(expected_tp)


# ------------------------------------------------------------------ #
# Rotura prematura (sin las 2 velas dentro)
# ------------------------------------------------------------------ #

def test_rotura_con_0_dentro_no_dispara_y_reinicia():
    s = strat_with_range(21300, 21350)
    signal = s.on_m1_close(m1(21345, 21360, 21344, 21355, minutes_offset=1))
    assert signal is None
    assert len(s._m1_seq) == 0


def test_rotura_con_solo_1_dentro_no_dispara_y_reinicia():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21325, minutes_offset=1))  # 1 dentro
    signal = s.on_m1_close(m1(21345, 21360, 21344, 21355, minutes_offset=2))  # fuera
    assert signal is None
    assert len(s._m1_seq) == 0


def test_rotura_prematura_y_luego_patron_valido_dispara():
    """Despues de una rotura prematura, el proximo patron completo si genera señal."""
    s = strat_with_range(21300, 21350)

    # Primera secuencia: solo 1 dentro + rotura prematura -> nada
    s.on_m1_close(m1(21325, 21330, 21320, 21325, minutes_offset=1))
    s.on_m1_close(m1(21348, 21360, 21347, 21355, minutes_offset=2))
    assert len(s._m1_seq) == 0

    # Segunda secuencia completa: 2 dentro + rotura -> señal
    s.on_m1_close(m1(21320, 21330, 21315, 21320, minutes_offset=3))
    s.on_m1_close(m1(21318, 21328, 21312, 21318, minutes_offset=4))
    signal = s.on_m1_close(m1(21345, 21360, 21344, 21355, minutes_offset=5))

    assert signal is not None
    assert signal.direction == "LONG"


# ------------------------------------------------------------------ #
# Ventana deslizante (mas de 2 M1 dentro antes de la rotura)
# ------------------------------------------------------------------ #

def test_ventana_deslizante_conserva_solo_las_2_ultimas():
    s = strat_with_range(21300, 21350)
    c1 = m1(21320, 21330, 21310, 21320, minutes_offset=1)
    c2 = m1(21318, 21328, 21315, 21318, minutes_offset=2)
    c3 = m1(21322, 21332, 21317, 21322, minutes_offset=3)
    s.on_m1_close(c1)
    s.on_m1_close(c2)
    s.on_m1_close(c3)  # desliza: descarta c1

    assert len(s._m1_seq) == 2
    assert s._m1_seq[0] is c2
    assert s._m1_seq[1] is c3


def test_ventana_deslizante_sl_usa_segunda_vela_original():
    """Con 3 M1 dentro, el SL se basa en la 2a vela (nueva primera de la ventana)."""
    s = strat_with_range(21300, 21350)
    c1 = m1(21320, 21330, 21290, 21320, minutes_offset=1)   # low=21290 — debe descartarse
    c2 = m1(21318, 21328, 21315, 21318, minutes_offset=2)   # low=21315
    c3 = m1(21322, 21332, 21318, 21322, minutes_offset=3)   # low=21318
    s.on_m1_close(c1)
    s.on_m1_close(c2)
    s.on_m1_close(c3)

    signal = s.on_m1_close(m1(21348, 21358, 21347, 21355, minutes_offset=4))

    assert signal is not None
    assert signal.stop_loss == c2.low   # 21315, NO 21290 de c1


def test_ventana_deslizante_4_dentro_sigue_generando_senal():
    """4 M1 dentro del rango y la 5a rompe: sigue generando señal."""
    s = strat_with_range(21300, 21350)
    for i in range(4):
        s.on_m1_close(m1(21320, 21330, 21315, 21322, minutes_offset=i + 1))

    signal = s.on_m1_close(m1(21348, 21360, 21347, 21355, minutes_offset=5))
    assert signal is not None
    assert signal.direction == "LONG"


# ------------------------------------------------------------------ #
# Nuevo cierre de M5 reinicia todo
# ------------------------------------------------------------------ #

def test_nuevo_m5_cierra_secuencia_activa():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21325, minutes_offset=1))
    s.on_m1_close(m1(21318, 21328, 21312, 21318, minutes_offset=2))
    assert len(s._m1_seq) == 2

    s.on_m5_close(m5(21330, 21370, 21320, 21340, minutes_offset=5))

    assert len(s._m1_seq) == 0
    assert s._range_high == 21370.0
    assert s._range_low == 21320.0


def test_nuevo_m5_bloquea_senal_del_rango_anterior():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21325, minutes_offset=1))
    s.on_m1_close(m1(21318, 21328, 21312, 21318, minutes_offset=2))

    s.on_m5_close(m5(21330, 21370, 21320, 21340, minutes_offset=5))

    # Rotura del rango antiguo: ya no dispara (el rango ahora es [21320, 21370])
    signal = s.on_m1_close(m1(21348, 21360, 21347, 21355, minutes_offset=6))
    assert signal is None  # 21355 esta dentro del nuevo rango [21320, 21370]


# ------------------------------------------------------------------ #
# La secuencia se resetea tras emitir una señal
# ------------------------------------------------------------------ #

def test_secuencia_se_resetea_tras_senal():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21325, minutes_offset=1))
    s.on_m1_close(m1(21318, 21328, 21312, 21318, minutes_offset=2))
    signal1 = s.on_m1_close(m1(21348, 21360, 21347, 21355, minutes_offset=3))
    assert signal1 is not None

    # La siguiente vela fuera no genera otra señal
    signal2 = s.on_m1_close(m1(21360, 21365, 21359, 21362, minutes_offset=4))
    assert signal2 is None
    assert len(s._m1_seq) == 0


# ------------------------------------------------------------------ #
# Limites del rango (cierres exactos)
# ------------------------------------------------------------------ #

def test_cierre_exacto_en_range_high_es_inside():
    s = strat_with_range(21300, 21350)
    assert s.on_m1_close(m1(21345, 21352, 21344, 21350, minutes_offset=1)) is None
    assert len(s._m1_seq) == 1


def test_cierre_exacto_en_range_low_es_inside():
    s = strat_with_range(21300, 21350)
    assert s.on_m1_close(m1(21305, 21310, 21298, 21300, minutes_offset=1)) is None
    assert len(s._m1_seq) == 1


def test_cierre_un_tick_encima_del_high_es_long():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21320, minutes_offset=1))
    s.on_m1_close(m1(21318, 21328, 21312, 21318, minutes_offset=2))
    signal = s.on_m1_close(m1(21348, 21360, 21347, 21350.25, minutes_offset=3))
    assert signal is not None
    assert signal.direction == "LONG"


def test_cierre_un_tick_debajo_del_low_es_short():
    s = strat_with_range(21300, 21350)
    s.on_m1_close(m1(21320, 21330, 21315, 21320, minutes_offset=1))
    s.on_m1_close(m1(21318, 21328, 21312, 21318, minutes_offset=2))
    signal = s.on_m1_close(m1(21305, 21306, 21290, 21299.75, minutes_offset=3))
    assert signal is not None
    assert signal.direction == "SHORT"


# ------------------------------------------------------------------ #
# Multiples rangos M5 consecutivos
# ------------------------------------------------------------------ #

def test_dos_rangos_m5_consecutivos_el_segundo_genera_senal():
    s = M5RangeBreakout()

    # Primer rango M5: [21300, 21350]
    s.on_m5_close(m5(21325, 21350, 21300, 21330, minutes_offset=0))
    s.on_m1_close(m1(21320, 21330, 21315, 21325, minutes_offset=1))  # dentro
    # No llega a completar el patron

    # Segundo rango M5: [21320, 21380]
    s.on_m5_close(m5(21340, 21380, 21320, 21350, minutes_offset=5))
    s.on_m1_close(m1(21340, 21350, 21335, 21342, minutes_offset=6))   # dentro nuevo rango
    s.on_m1_close(m1(21342, 21348, 21338, 21345, minutes_offset=7))   # dentro nuevo rango
    signal = s.on_m1_close(m1(21375, 21385, 21374, 21382, minutes_offset=8))   # fuera por arriba

    assert signal is not None
    assert signal.direction == "LONG"
    assert signal.entry_price == 21382.0
